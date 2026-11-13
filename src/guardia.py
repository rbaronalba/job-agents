"""Hook PreToolUse de las sesiones del orquestador (src/guardia.json, pasado con --settings).

Segunda barrera, en código, para lo que las reglas de permisos no pueden mirar (los argumentos). Lee del entorno que
fija src.diario: JOB_AGENTS_FASE, JOB_AGENTS_PRUEBA y JOB_AGENTS_DESTINO (destinatario validado del resumen).
- Modo prueba: ninguna escritura en Gmail.
- send_message: solo en la fase email, sin draftId, sin cc/bcc y con `to` exactamente igual a JOB_AGENTS_DESTINO;
  o en espontáneas (allí solo existe si el modo efectivo es auto: lo decide diario.permisos()).
Sin JOB_AGENTS_FASE (sesiones interactivas) no hace nada. Salida 2 = denegar (el motivo va por stderr al modelo).
"""
from __future__ import annotations

import json
import os
import sys

GMAIL = "mcp__claude_ai_Gmail__"
LECTURA = {"search_threads", "get_thread", "get_message", "list_drafts", "get_draft", "list_labels"}


def motivo(herramienta: str, entrada: dict, env=os.environ) -> str | None:
    fase = env.get("JOB_AGENTS_FASE")
    if not fase or not herramienta.startswith(GMAIL):
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
