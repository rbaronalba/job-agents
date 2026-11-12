"""Consumo real de tokens a partir de los transcripts de Claude Code -> data/consumo.sqlite.

  python -m src.consumo cargar  [--proyecto DIR]   Importa (o reimporta) todas las sesiones del proyecto
  python -m src.consumo informe [--desde AAAA-MM-DD]  Tabla por sesión (sesión principal + subagentes)

Solo lee metadatos (usage, nombres de herramientas, tamaños); nunca guarda texto de los mensajes.
Unidades equivalentes ("equiv"): entrada 1, caché escrita 1,25, caché leída 0,1, salida 5 (ratios de precio de la API).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path

from .db import RAIZ

RUTA = RAIZ / "data" / "consumo.sqlite"
PESOS = {"in_tok": 1, "cache_w": 1.25, "cache_r": 0.1, "out_tok": 5}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sesiones (
  session_id TEXT, agente TEXT, padre TEXT, inicio TEXT, fin TEXT, comando TEXT, modelo TEXT,
  llamadas INT, in_tok INT, cache_w INT, cache_r INT, out_tok INT, equiv REAL, imagenes INT,
  ctx_p50 INT, ctx_p90 INT, ctx_max INT, PRIMARY KEY (session_id, agente));
CREATE TABLE IF NOT EXISTS herramientas (
  session_id TEXT, agente TEXT, herramienta TEXT, llamadas INT, chars INT,
  PRIMARY KEY (session_id, agente, herramienta));
"""


def proyecto_por_defecto(raiz: Path = RAIZ) -> Path:
    # Claude Code nombra la carpeta con la ruta del proyecto y todo lo no alfanumérico como "-"
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(raiz))


def _herramienta(nombre: str) -> str:
    nombre = re.sub(r"^mcp__claude_ai_Composio__COMPOSIO_", "composio:", nombre)
    nombre = re.sub(r"^mcp__claude-in-chrome__", "chrome:", nombre)
    return re.sub(r"^mcp__claude_ai_Gmail__", "gmail:", nombre)


def _comando(texto: str) -> str | None:
    m = re.search(r"<command-name>(/[\w-]+)", texto) or re.match(r"\s*(/[\w-]+)", texto)
    return m.group(1) if m else None


def analizar(ruta: Path) -> tuple[dict, dict]:
    """Devuelve (fila de sesión, {herramienta: [llamadas, chars]}) de un .jsonl."""
    vistos, ctx, modelos, comando = set(), [], {}, None
    s = {"in_tok": 0, "cache_w": 0, "cache_r": 0, "out_tok": 0, "imagenes": 0, "inicio": None, "fin": None}
    herr, id2 = {}, {}
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("timestamp"):
            s["inicio"] = s["inicio"] or d["timestamp"]
            s["fin"] = d["timestamp"]
        m = d.get("message") or {}
        contenido = m.get("content")
        if d.get("type") == "user" and comando is None and not d.get("isMeta"):
            texto = contenido if isinstance(contenido, str) else " ".join(
                c.get("text", "") for c in contenido or [] if isinstance(c, dict) and c.get("type") == "text")
            if texto.strip():
                comando = _comando(texto) or "chat"
        if d.get("type") == "assistant":
            for c in contenido or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    h = _herramienta(c["name"])
                    herr.setdefault(h, [0, 0])[0] += 1
                    id2[c["id"]] = h
            u = m.get("usage")
            if u and m.get("id") not in vistos:   # una respuesta en streaming llega en varias líneas con el mismo id
                vistos.add(m.get("id"))
                s["in_tok"] += u.get("input_tokens") or 0
                s["cache_w"] += u.get("cache_creation_input_tokens") or 0
                s["cache_r"] += u.get("cache_read_input_tokens") or 0
                s["out_tok"] += u.get("output_tokens") or 0
                ctx.append((u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                           + (u.get("cache_read_input_tokens") or 0))
                modelos[m.get("model")] = modelos.get(m.get("model"), 0) + 1
        elif d.get("type") == "user" and isinstance(contenido, list):
            for c in contenido:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    r = c.get("content")
                    if isinstance(r, list):
                        s["imagenes"] += sum(1 for x in r if isinstance(x, dict) and x.get("type") == "image")
                    h = id2.get(c.get("tool_use_id"), "?")
                    herr.setdefault(h, [0, 0])[1] += len(r) if isinstance(r, str) else len(json.dumps(r, ensure_ascii=False))
    ctx.sort()
    s.update({
        "comando": comando or "?", "llamadas": len(ctx),
        "modelo": max((k for k in modelos if k != "<synthetic>"), key=modelos.get, default=None),
        "ctx_p50": int(statistics.median(ctx)) if ctx else 0,
        "ctx_p90": ctx[int(0.9 * (len(ctx) - 1))] if ctx else 0, "ctx_max": ctx[-1] if ctx else 0,
    })
    s["equiv"] = round(sum(s[k] * w for k, w in PESOS.items()))
    return s, herr


def conectar(ruta: Path = RUTA) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)
    return con


def guardar(con, session_id: str, agente: str, padre: str | None, s: dict, herr: dict):
    con.execute("DELETE FROM herramientas WHERE session_id = ? AND agente = ?", (session_id, agente))
    cols = ["inicio", "fin", "comando", "modelo", "llamadas", "in_tok", "cache_w", "cache_r", "out_tok", "equiv",
            "imagenes", "ctx_p50", "ctx_p90", "ctx_max"]
    con.execute(f"INSERT OR REPLACE INTO sesiones (session_id, agente, padre, {', '.join(cols)}) "
                f"VALUES (?, ?, ?, {', '.join('?' * len(cols))})", [session_id, agente, padre, *(s[c] for c in cols)])
    con.executemany("INSERT INTO herramientas VALUES (?, ?, ?, ?, ?)",
                    [(session_id, agente, h, n, ch) for h, (n, ch) in herr.items()])


def cargar(proyecto: Path, con) -> int:
    n = 0
    for f in sorted(proyecto.glob("*.jsonl")):
        s, herr = analizar(f)
        if not s["llamadas"]:
            continue
        guardar(con, f.stem, "principal", None, s, herr)
        n += 1
        for sub in sorted((proyecto / f.stem / "subagents").glob("*.jsonl")):
            meta = sub.with_suffix(".meta.json")
            tipo = json.loads(meta.read_text(encoding="utf-8")).get("agentType", "?") if meta.exists() else "?"
            ss, sh = analizar(sub)
            if ss["llamadas"]:
                guardar(con, f.stem, f"{tipo}:{sub.stem[-6:]}", f.stem, ss, sh)
    con.commit()
    return n


def informe(con, desde: str | None = None):
    filas = con.execute(
        "SELECT session_id, agente, substr(inicio, 1, 16), comando, llamadas, equiv, cache_r, out_tok, imagenes, ctx_p50, ctx_p90 "
        "FROM sesiones WHERE inicio >= ? ORDER BY (SELECT inicio FROM sesiones p WHERE p.session_id = sesiones.session_id "
        "AND p.agente = 'principal'), agente != 'principal', agente", (desde or "",)).fetchall()
    print(f"{'sesión':8} {'agente':18} {'inicio':16} {'cmd':10} {'llam':>5} {'equiv':>8} {'cache_r':>8} {'out':>6} {'img':>4} {'p50':>5} {'p90':>5}")
    for sid, ag, ini, cmd, ll, eq, cr, out, img, p50, p90 in filas:
        print(f"{sid[:8]:8} {ag[:18]:18} {ini or '':16} {cmd[:10]:10} {ll:5} {eq/1e6:7.2f}M {cr/1e6:7.1f}M {out/1e3:5.0f}k "
              f"{img:4} {p50//1000:4}k {p90//1000:4}k")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m src.consumo", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=["cargar", "informe"])
    p.add_argument("--proyecto", type=Path, help="Carpeta de transcripts (por defecto la de este proyecto)")
    p.add_argument("--desde")
    p.add_argument("--db", type=Path, default=RUTA)
    a = p.parse_args(argv)
    con = conectar(a.db)
    if a.accion == "cargar":
        print(f"{cargar(a.proyecto or proyecto_por_defecto(), con)} sesiones cargadas en {a.db}")
    else:
        informe(con, a.desde)


if __name__ == "__main__":
    main()
