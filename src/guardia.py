"""Hook PreToolUse de las sesiones del orquestador (src/guardia.json, pasado con --settings).

Segunda barrera, en código, para lo que las reglas de permisos no pueden mirar (los argumentos). Lee del entorno que
fija src.diario: JOB_AGENTS_FASE, JOB_AGENTS_PRUEBA y JOB_AGENTS_DESTINO (destinatario validado del resumen).
- Modo prueba: ninguna escritura en Gmail.
- send_message: solo en la fase email, sin draftId, sin cc/bcc y con `to` exactamente igual a JOB_AGENTS_DESTINO;
  o en espontáneas (allí solo existe si el modo efectivo es auto: lo decide diario.permisos()).
- Composio (que también puede enviar correo): solo en la fase buscar, solo herramientas JOB_SEARCH_* y sin red en su bash.
- Espontáneas con envío: el destinatario debe ser una fila de empresas.csv cuyo dominio coincida con el de su web.
- Chrome: navegar solo a dominios conocidos (portales, ATS) o a los de las ofertas y empresas guardadas; sin JS de red.
- WebFetch: nunca a IPs ni a hosts internos.
Sin JOB_AGENTS_FASE (sesiones interactivas) no hace nada. Salida 2 = denegar (el motivo va por stderr al modelo).
"""
from __future__ import annotations

import csv
import ipaddress
import json
import os
import re
import sqlite3
import sys
from urllib.parse import urlparse

from . import db

GMAIL = "mcp__claude_ai_Gmail__"
COMPOSIO = "mcp__claude_ai_Composio__"
CHROME = "mcp__claude-in-chrome__"
# Dominios de portales y ATS: lo mismo que .claude/settings.json (ClaudeInChromeDomain); los demás salen de la BD
DOMINIOS = ("linkedin.com", "infojobs.net", "tecnoempleo.com", "google.com", "greenhouse.io", "lever.co", "ashbyhq.com",
            "personio.com", "personio.de", "recruitee.com", "workable.com", "myworkdayjobs.com", "smartrecruiters.com",
            "teamtailor.com", "breezy.hr", "bamboohr.com", "jobvite.com", "icims.com", "join.com", "softgarden.io")
RED = re.compile(r"curl|wget|\bnc\b|ncat|\bssh\b|\bscp\b|ftp|https?://|python|node|perl|ruby|base64|/dev/tcp|\bsh\b|bash",
                 re.I)
JS_RED = re.compile(r"fetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|window\.open|location\s*[=.]|\.href\s*=|import\s*\(",
                    re.I)
LECTURA = {"search_threads", "get_thread", "get_message", "list_drafts", "get_draft", "list_labels"}


def _host(url: str) -> str:
    return (urlparse(url if "//" in url else "//" + url).hostname or "").lower().rstrip(".")


def _de(host: str, dominio: str) -> bool:
    return host == dominio or host.endswith("." + dominio)


def _filas_empresas() -> list[dict]:
    try:
        with open(db.EMPRESAS, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _hosts_guardados(env) -> set[str]:
    """Hosts de las URL de las ofertas (BD, solo lectura) y de las webs de empresas.csv. Fallo = conjunto vacío."""
    hosts = {_host(f.get("web") or "") for f in _filas_empresas()}
    try:
        ruta = env.get("JOB_AGENTS_DB") or db.RUTA
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        for (urls,) in con.execute("SELECT urls FROM ofertas"):
            hosts |= {_host(u) for u in json.loads(urls or "[]")}
        con.close()
    except Exception:   # noqa: BLE001 - sin BD no hay hosts dinámicos: solo los fijos
        pass
    return hosts - {""}


def hosts_de_ofertas(ids: list[str], env=os.environ) -> set[str]:
    """Hosts de las URL de unas ofertas concretas (para permitir a Chrome solo esos dominios en un lote)."""
    try:
        con = sqlite3.connect(f"file:{env.get('JOB_AGENTS_DB') or db.RUTA}?mode=ro", uri=True)
        filas = con.execute(f"SELECT urls FROM ofertas WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        con.close()
    except Exception:   # noqa: BLE001
        return set()
    return {_host(u) for (urls,) in filas for u in json.loads(urls or "[]")} - {""}


def _interno(host: str) -> bool:
    if host in ("localhost", "") or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


def correo_valido(a: str, filas: list[dict]) -> bool:
    """El destinatario consta en empresas.csv y su dominio es el de la web de esa fila (no basta lo que diga una web)."""
    a = a.strip().lower()
    dom = a.rpartition("@")[2]
    return bool(dom) and any((f.get("email") or "").strip().lower() == a and _de(dom, _host(f.get("web") or "").removeprefix("www."))
                             for f in filas if f.get("web"))


def _composio(op: str, entrada: dict) -> str | None:
    if op in ("COMPOSIO_SEARCH_TOOLS", "COMPOSIO_GET_TOOL_SCHEMAS"):
        return None
    if op == "COMPOSIO_MULTI_EXECUTE_TOOL":
        slugs = [str(t.get("tool_slug", "")) for t in entrada.get("tools") or []]
        if slugs and all(s.startswith("JOB_SEARCH_") for s in slugs):
            return None
        return f"guardia: Composio solo ejecuta herramientas JOB_SEARCH_* (recibido {slugs})"
    if op == "COMPOSIO_REMOTE_BASH_TOOL":
        return "guardia: bash de Composio con red o intérprete no permitido" if RED.search(str(entrada.get("command", ""))) else None
    return f"guardia: {op} no permitida"


def motivo(herramienta: str, entrada: dict, env=os.environ) -> str | None:
    fase = env.get("JOB_AGENTS_FASE")
    if not fase:
        return None
    if herramienta.startswith(COMPOSIO):
        return _composio(herramienta[len(COMPOSIO):], entrada) if fase == "buscar" else f"guardia: Composio no se usa en la fase {fase}"
    if herramienta == "WebFetch":
        return "guardia: WebFetch a un host interno" if _interno(_host(str(entrada.get("url", "")))) else None
    if herramienta.startswith(CHROME):
        op = herramienta[len(CHROME):]
        if op == "javascript_tool" and JS_RED.search(str(entrada.get("text") or entrada.get("code") or entrada)):
            return "guardia: javascript_tool con red o navegación no permitido"
        url = str(entrada.get("url") or "")
        if op in ("navigate", "tabs_create_mcp") and url and url != "about:blank":
            h = _host(url)
            if _interno(h) or not (any(_de(h, d) for d in DOMINIOS) or h in _hosts_guardados(env)):
                return f"guardia: Chrome no navega a {h or url} (no es un portal ni consta en las ofertas o empresas)"
        return None
    if not herramienta.startswith(GMAIL):
        return None
    if herramienta in env.get("JOB_AGENTS_GUARDIA_PRUEBA", "").split(","):   # solo para comprobar que el hook se aplica
        return f"guardia: {herramienta} bloqueada a propósito (prueba del hook)"
    op = herramienta[len(GMAIL):]
    if op in LECTURA:
        return None
    if env.get("JOB_AGENTS_PRUEBA") == "1":
        return f"guardia: modo prueba, {op} no permitido"
    if op == "send_message":
        if fase == "espontaneas":
            to = entrada.get("to") or []
            if len(to) != 1 or entrada.get("cc") or entrada.get("bcc") or not correo_valido(str(to[0]), _filas_empresas()):
                return f"guardia: {to} no es un correo de empresas.csv con el dominio de su web (sin cc ni bcc)"
            return None
        destino = env.get("JOB_AGENTS_DESTINO", "").strip().lower()
        to = [str(t).strip().lower() for t in entrada.get("to") or []]
        if fase != "email" or not destino:
            return f"guardia: send_message no permitido en la fase {fase}"
        if entrada.get("draftId") or entrada.get("cc") or entrada.get("bcc") or to != [destino]:
            return f"guardia: el resumen solo se envía a {destino}, sin borrador, cc ni bcc"
    return None


def main():
    try:
        d = json.load(sys.stdin)
        m = motivo(d.get("tool_name", ""), d.get("tool_input") or {})
    except Exception as e:   # noqa: BLE001 - si no se puede evaluar, se deniega
        m = f"guardia: entrada ilegible ({e})"
    if m:
        print(m, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
