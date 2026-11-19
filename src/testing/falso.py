"""`claude` falso: lo que ejecuta claude.cmd en las pruebas del orquestador. Sin sesiones reales ni coste.

Apunta cada llamada en llamadas.jsonl (junto a este script, o en FALSO_LLAMADAS) y responde según FALSO_MODO.
"""
import json
import os
import sys
import threading
from pathlib import Path

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
leido = {}
hilo = threading.Thread(target=lambda: leido.setdefault("d", sys.stdin.read()), daemon=True)
hilo.start()
hilo.join(2)
registro = Path(os.environ.get("FALSO_LLAMADAS") or Path(__file__).with_name("llamadas.jsonl"))
with open(registro, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "prueba": os.environ.get("JOB_AGENTS_PRUEBA"),
                        "db": os.environ.get("JOB_AGENTS_DB"),
                        "stdin_cerrado": not hilo.is_alive() and leido.get("d") == ""}) + "\n")

modo = os.environ.get("FALSO_MODO", "ok")
fase = prompt.split()[0]
RESPUESTAS = {
    ("limite", "/buscar"): "You've hit your limit · resets 2:40pm",
    ("error_postular", "/postular"): "preparar falló: no tiene CV adaptado\nESTADO_FASE: error",
    ("sin_chrome", "/postular"): "Chrome no conectado. ESTADO_FASE: sin_chrome",
}
if modo == "max_turns":   # misma forma que la respuesta real de claude -p --max-turns 1 (validación del 12-nov)
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": None, "num_turns": 2,
                      "session_id": "falsa", "errors": ["Reached maximum number of turns (1)"]}))
    sys.exit(1)
if modo == "no_json":
    print("salida rota")
    print("fallo interno del CLI", file=sys.stderr)
    sys.exit(3)
texto = RESPUESTAS.get((modo, fase), f"hecho {fase}\nESTADO_FASE: ok")
print(json.dumps({"result": texto, "is_error": False, "session_id": "falsa", "num_turns": 1, "total_cost_usd": 0}))
