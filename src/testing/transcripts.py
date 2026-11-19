"""Constructores de transcripts de Claude Code (.jsonl) para probar src.consumo. Sin asserts."""
from __future__ import annotations

import json
from pathlib import Path


def usuario(texto: str, *, meta: bool = False, ts: str = "2026-11-17T10:00:00Z") -> dict:
    return {"type": "user", "timestamp": ts, "isMeta": meta, "message": {"role": "user", "content": texto}}


def asistente(id_: str, *, entrada=100, cache_w=0, cache_r=0, salida=10, modelo="claude-x", herramientas=(), ts="2026-11-17T10:00:05Z") -> dict:
    """Respuesta del asistente con su uso; `herramientas` = [(tool_use_id, nombre)]."""
    contenido = [{"type": "tool_use", "id": i, "name": n} for i, n in herramientas]
    return {"type": "assistant", "timestamp": ts, "message": {
        "id": id_, "model": modelo, "content": contenido,
        "usage": {"input_tokens": entrada, "cache_creation_input_tokens": cache_w, "cache_read_input_tokens": cache_r, "output_tokens": salida}}}


def resultado(tool_use_id: str, contenido, ts: str = "2026-11-17T10:00:06Z") -> dict:
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": contenido}]}}


def escribir(ruta: Path, lineas: list) -> Path:
    """Escribe un .jsonl; las líneas que son texto se copian tal cual (para meter basura)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lineas) + "\n", encoding="utf-8")
    return ruta


def agentes_cargados(con) -> list[str]:
    return sorted(r[0] for r in con.execute("SELECT agente FROM sesiones"))
