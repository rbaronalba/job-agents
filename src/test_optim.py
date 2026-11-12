"""Pruebas de la optimización de tokens: python -m src.test_optim

Trabaja sobre una base temporal y, si existe, sobre una COPIA del histórico (data/tmp/historico_copia.sqlite).
Nunca abre el histórico real en escritura.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import db

COPIA = db.RAIZ / "data" / "tmp" / "historico_copia.sqlite"


def cli(*args, prueba=False, base=None, ok=True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOB_AGENTS_")}
    env["PYTHONIOENCODING"] = "utf-8"
    if base:
        env["JOB_AGENTS_DB"] = str(base)
    if prueba:
        env["JOB_AGENTS_PRUEBA"] = "1"
    r = subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=db.RAIZ, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    assert (r.returncode == 0) == ok, (args, r.returncode, r.stdout[-500:], r.stderr[-500:])
    return r.stdout + r.stderr


def base_sintetica() -> Path:
    ruta = Path(tempfile.mkdtemp()) / "h.sqlite"
    con = db.conectar(ruta)
    for i, (emp, tit, enc, est) in enumerate([("A", "Front Angular", 80, "nueva"), ("B", "React Dev", 60, "nueva"),
                                              ("C", "Full Stack", 70, "cv_adaptado"), ("D", "Angular", 90, "cv_adaptado"),
                                              ("E", "Vue", 50, "enviada")]):
        db.guardar(con, {"empresa": emp, "titulo": tit, "encaje": enc, "estado": est, "texto": "x" * 2000,
                         "requisitos": ["Angular"], "urls": [f"https://e/{i}"], "portales": ["linkedin"],
                         "justificacion": "j", "tipo_candidatura": "easy_apply", "fecha_pub": f"2026-11-0{i + 1}"})
    con.commit()
    return ruta


def paso0():
    # Modo prueba sin base alternativa: se niega a abrir el histórico real
    out = cli("listar", prueba=True, ok=False)
    assert "no se toca el histórico real" in out, out
    base = base_sintetica()
    m = json.loads(cli("modo", prueba=True, base=base))
    assert m["portales"] == "revision" and m["espontaneas"] == "borrador" and m["prueba"], m
    assert "prueba" in m["empresas_csv"] and "prueba" in m["output"], m
    # huella: misma base -> misma huella; un cambio de estado la cambia
    h1 = json.loads(cli("huella", base=base))
    assert h1["integridad"] == "ok" and h1["total"] == 5, h1
    assert json.loads(cli("huella", base=base)) == h1
    cli("estado", "2026-W00-001", "nueva", base=base, ok=False)          # id inexistente: falla y no toca nada
    assert json.loads(cli("huella", base=base)) == h1
    con = db.conectar(base)
    oid = con.execute("SELECT id FROM ofertas WHERE estado = 'nueva' LIMIT 1").fetchone()[0]
    con.close()
    cli("estado", oid, "descartada", prueba=True, base=base)
    h2 = json.loads(cli("huella", base=base))
    assert h2["sha256"] != h1["sha256"] and h2["por_estado"]["descartada"] == 1, h2
    # Excel y logs en modo prueba van a data/tmp/prueba, no a data/ofertas ni logs/
    out = cli("excel", prueba=True, base=base)
    assert "data/tmp/prueba/ofertas" in out.replace("\\", "/"), out
    cli("resumen", prueba=True, base=base)
    assert any((db.RAIZ / "data" / "tmp" / "prueba" / "logs").glob("*.md"))
    print("paso 0 OK")
    return base


def paso1(base: Path):
    from .cli import CAMPOS_LISTA
    from .cv import nombre_pdf
    bases = [base] + ([COPIA] if COPIA.exists() else [])
    for b in bases:
        h = json.loads(cli("huella", base=b))
        for estado in ("nueva", "cv_adaptado", "pendiente_revision", "enviada", "descartada"):
            compacto = cli("listar", "--estado", estado, "--json", base=b)
            completo = cli("listar", "--estado", estado, "--json", "--completo", base=b)
            c, f = json.loads(compacto), json.loads(completo)
            assert [o["id"] for o in c] == [o["id"] for o in f], f"{b.name} {estado}: ids u orden distintos"
            assert all(list(o) == CAMPOS_LISTA for o in c)
            if b == COPIA and f:
                print(f"  {estado:18} {len(f):3} ofertas: --completo {len(completo.encode()):7} B -> compacto {len(compacto.encode()):6} B "
                      f"({100 - 100 * len(compacto.encode()) // len(completo.encode())}% menos)")
        if b == COPIA:
            oid = json.loads(cli("listar", "--estado", "cv_adaptado", "--json", base=b))[0]["id"]
            o = json.loads(cli("oferta", oid, base=b))
            assert o["id"] == oid and "texto" in o and isinstance(o["urls"], list), list(o)
            print(f"  oferta {oid}: {len(cli('oferta', oid, base=b).encode())} B")
        assert json.loads(cli("huella", base=b)) == h, f"{b.name}: la huella cambió"
    cli("oferta", "no-existe", base=base, ok=False)
    oid1 = json.loads(cli("listar", "--json", base=base))[0]["id"]
    assert list(json.loads(cli("oferta", oid1, "--campos", "titulo,texto", base=base))) == ["id", "titulo", "texto"]
    # preparar con y sin perfil (en prueba: CV falso en data/tmp/prueba/output, nada fuera)
    con = db.conectar(base)
    oid, sem = con.execute("SELECT id, semana FROM ofertas WHERE estado = 'cv_adaptado'").fetchone()
    con.close()
    carpeta = db.RAIZ / "data" / "tmp" / "prueba" / "output" / sem / oid
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre_pdf()).write_bytes(b"%PDF-1.4 prueba")
    con_perfil = json.loads(cli("preparar", oid, prueba=True, base=base))
    sin_perfil = json.loads(cli("preparar", oid, "--sin-perfil", prueba=True, base=base))
    assert "candidato" in con_perfil and "respuestas" in con_perfil and con_perfil["modo"] == "revision"
    assert "candidato" not in sin_perfil and sin_perfil["modo"] == "revision" and "prueba" in sin_perfil["cv"]
    assert {k: v for k, v in con_perfil.items() if k not in ("candidato", "respuestas")} == sin_perfil
    pf = json.loads(cli("perfil-formulario", prueba=True, base=base))
    assert set(pf) == {"candidato", "respuestas", "modo"} and pf["modo"] == "revision"
    print("paso 1 OK")


FALSO = '''import json, os, sys, threading
from pathlib import Path
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
leido = {}
hilo = threading.Thread(target=lambda: leido.setdefault("d", sys.stdin.read()), daemon=True)
hilo.start(); hilo.join(2)
with open(Path(__file__).with_name("llamadas.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "prueba": os.environ.get("JOB_AGENTS_PRUEBA"),
                        "db": os.environ.get("JOB_AGENTS_DB"),
                        "stdin_cerrado": not hilo.is_alive() and leido.get("d") == ""}) + "\\n")
modo = os.environ.get("FALSO_MODO", "ok")
fase = prompt.split()[0]
if modo == "max_turns":   # misma forma que la respuesta real de claude -p --max-turns 1 (validación del 12-nov)
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": None, "num_turns": 2,
                      "session_id": "falsa", "errors": ["Reached maximum number of turns (1)"]}))
    sys.exit(1)
if modo == "no_json":
    print("salida rota")
    print("fallo interno del CLI", file=sys.stderr)
    sys.exit(3)
if modo == "limite" and fase == "/buscar":
    texto = "You've hit your limit · resets 2:40pm"
elif modo == "sin_chrome" and fase == "/postular":
    texto = "Chrome no conectado. ESTADO_FASE: sin_chrome"
else:
    texto = f"hecho {fase}\\nESTADO_FASE: ok"
print(json.dumps({"result": texto, "is_error": False, "session_id": "falsa", "num_turns": 1, "total_cost_usd": 0}))
'''


def claude_falso() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "falso.py").write_text(FALSO, encoding="utf-8")
    (d / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0falso.py" %*\r\n', encoding="utf-8")
    return d


def diario(falso: Path, *args, modo="ok", env_extra=None, stdin_abierto=False) -> tuple[str, list[dict]]:
    (falso / "llamadas.jsonl").unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("JOB_AGENTS_")}
    env.update(PATH=f"{falso}{os.pathsep}{env['PATH']}", FALSO_MODO=modo, PYTHONIOENCODING="utf-8", **(env_extra or {}))
    # stdin_abierto: el orquestador hereda un stdin abierto y vacío (como en una consola o el Programador de tareas)
    p = subprocess.Popen([sys.executable, "-m", "src.diario", *args], cwd=db.RAIZ, env=env,
                         stdin=subprocess.PIPE if stdin_abierto else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    salida = p.stdout.read()
    p.wait()
    if p.stdin:
        p.stdin.close()
    llamadas = [json.loads(l) for l in (falso / "llamadas.jsonl").read_text(encoding="utf-8").splitlines()] \
        if (falso / "llamadas.jsonl").exists() else []
    return salida, llamadas


def paso2(base: Path):
    from .diario import _seguro
    hoy = __import__("datetime").date.today().isoformat()
    # pendientes: cupos con una enviada hoy por portal y dos espontáneas hoy (perfil de ejemplo: 30 total, 15 portales,
    # objetivo 12 espontáneas)
    con = db.conectar(base)
    nuevas = [r[0] for r in con.execute("SELECT id FROM ofertas WHERE estado = 'nueva' ORDER BY encaje DESC")]
    cv = [r[0] for r in con.execute("SELECT id FROM ofertas WHERE estado = 'cv_adaptado' ORDER BY encaje DESC")]
    env_id = con.execute("SELECT id FROM ofertas WHERE estado = 'enviada'").fetchone()[0]
    db.cambiar_estado(con, env_id, "enviada")
    con.commit(); con.close()
    csv = db.RAIZ / "data" / "tmp" / "prueba" / "empresas.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text(f"empresa,web,email,ciudad,sector,notas,estado,fecha\nX,,,,,,enviada,{hoy}\nY,,,,,,borrador,{hoy}\n"
                   "Z,,,,,,enviada,2020-01-01\nW,,,,,,pendiente,\n", encoding="utf-8")
    p = json.loads(cli("pendientes", prueba=True, base=base))
    assert p["nuevas"] == nuevas and p["cv_adaptado"] == cv, p
    assert len(p["enviadas_hoy"]) == 1 and p["espontaneas_hoy"] == ["X", "Y"], p
    assert p["cupo_portales"] == 14 and p["cupo_espontaneas"] == 10 and p["prueba"], p
    if COPIA.exists():
        pc = json.loads(cli("pendientes", base=COPIA))
        print(f"  copia del histórico: {len(pc['nuevas'])} nuevas, {len(pc['cv_adaptado'])} cv_adaptado, "
              f"{len(pc['enviadas_hoy'])} enviadas hoy, cupo portales {pc['cupo_portales']}")
    for malo in ('a"b', "a&b", "a|b", "a\nb", "50%"):
        try:
            _seguro(malo)
            raise AssertionError(malo)
        except ValueError:
            pass

    falso = claude_falso()
    h_base = json.loads(cli("huella", base=base))
    # A) día completo en prueba: 4 sesiones (buscar, adaptar, 1 lote de postular, espontáneas); sin email ni seguimiento
    out, ll = diario(falso, "--prueba", "--origen-db", str(base))
    fases = [l["argv"][1].split()[0] for l in ll]
    assert fases == ["/buscar", "/adaptar", "/postular", "/espontaneas"], (fases, out)
    assert ll[2]["argv"][1].startswith("/postular " + " ".join(cv)), ll[2]["argv"][1]
    assert ll[3]["argv"][1].startswith("/espontaneas 10"), ll[3]["argv"][1]   # objetivo 12 menos 2 de hoy
    assert all(("--chrome" in l["argv"]) == (f in ("/postular", "/espontaneas")) for l, f in zip(ll, fases))
    assert all(l["prueba"] == "1" and "prueba" in l["db"] and Path(l["db"]) != base for l in ll), ll
    assert all("MODO PRUEBA" in l["argv"][1] and "ESTADO_FASE" in l["argv"][1] for l in ll)
    assert "seguimiento  vacia" in out and "email de resumen no enviado" in out, out
    assert json.loads(cli("huella", base=base)) == h_base, "la base de origen cambió en --prueba"
    # B) lotes de 1 y tope de ofertas
    _, ll = diario(falso, "--prueba", "--origen-db", str(base), "--lote", "1", "--fases", "postular")
    assert [l["argv"][1].split()[:2] for l in ll] == [["/postular", cv[0]], ["/postular", cv[1]]], ll
    _, ll = diario(falso, "--prueba", "--origen-db", str(base), "--max-ofertas", "1", "--fases", "postular,espontaneas")
    assert [l["argv"][1].split()[:2] for l in ll] == [["/postular", cv[0]], ["/espontaneas", "1"]], ll
    # C) sin Chrome: no se intenta espontáneas
    out, ll = diario(falso, "--prueba", "--origen-db", str(base), "--fases", "postular,espontaneas", modo="sin_chrome")
    assert [l["argv"][1].split()[0] for l in ll] == ["/postular"] and "Chrome no disponible" in out, out
    # D) límite de uso en buscar: no se lanza nada más
    out, ll = diario(falso, "--prueba", "--origen-db", str(base), modo="limite")
    assert [l["argv"][1].split()[0] for l in ll] == ["/buscar"] and out.count("omitida") >= 4, out
    # E) fases vacías: sin nuevas ni CVs ni cupo no arranca ninguna sesión
    vacia = Path(tempfile.mkdtemp()) / "v.sqlite"
    db.conectar(vacia).close()
    out, ll = diario(falso, "--prueba", "--origen-db", str(vacia), "--fases", "adaptar,postular")
    assert ll == [] and out.count("vacia") == 2, out
    # F) modo real (sin prueba) sobre una base sintética: hay email final y se le pasa un archivo, no el texto
    out, ll = diario(falso, "--fases", "postular,resumen", env_extra={"JOB_AGENTS_DB": str(base)})
    assert [l["argv"][1].split()[0] for l in ll] == ["/postular", "Lee"] and "email_resumen.md" in ll[-1]["argv"][1], ll
    assert all(l["prueba"] is None for l in ll)
    # G) simular no lanza Claude
    out, ll = diario(falso, "--prueba", "--simular", "--origen-db", str(base))
    assert ll == [] and "simulado" in out, out
    # H) diario.bat: sin la variable, la línea de siempre (/diario); con JOB_AGENTS_DIARIO=nuevo, src.diario
    for var, esperado in ((None, ["/diario"]), ("nuevo", [])):
        (falso / "llamadas.jsonl").unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("JOB_AGENTS_")}
        env.update(PATH=f"{falso}{os.pathsep}{env['PATH']}", PYTHONIOENCODING="utf-8")
        if var:
            env["JOB_AGENTS_DIARIO"] = var
        subprocess.run(["cmd", "/c", str(db.RAIZ / "diario.bat"), "--prueba", "--simular", "--origen-db", str(base)],
                       cwd=db.RAIZ, env=env, capture_output=True)
        ll = [json.loads(l) for l in (falso / "llamadas.jsonl").read_text(encoding="utf-8").splitlines()] \
            if (falso / "llamadas.jsonl").exists() else []
        assert [l["argv"][1] for l in ll] == esperado, (var, ll)
    assert "simulado" in (db.RAIZ / "logs" / "diario.log").read_text(encoding="utf-8")
    print("paso 2 OK")


def d4_stdin(base: Path):
    falso = claude_falso()
    _, ll = diario(falso, "--prueba", "--origen-db", str(base), "--fases", "buscar", stdin_abierto=True)
    assert ll and all(l["stdin_cerrado"] for l in ll), ll
    print("D4 stdin OK (simulada)")


def ultimo_diario() -> tuple[list[dict], Path]:
    d = max((db.RAIZ / "data" / "tmp" / "prueba" / "logs" / "diario").iterdir(), key=lambda p: p.stat().st_mtime)
    return json.loads((d / "diario.json").read_text(encoding="utf-8")), d


def d5_errores(base: Path):
    falso = claude_falso()
    # Error real de claude -p (forma de --max-turns): result vacío, errors con el motivo, código 1
    out, _ = diario(falso, "--prueba", "--origen-db", str(base), "--fases", "buscar", modo="max_turns")
    fases, carpeta = ultimo_diario()
    f = fases[0]
    assert f["estado"] == "error" and f["codigo_salida"] == 1 and f["is_error"] is True, f
    assert f["subtype"] == "error_max_turns" and f["errors"] == ["Reached maximum number of turns (1)"], f
    assert "Reached maximum number of turns" in f["detalle"], f
    fase_json = json.loads(next(carpeta.glob("*-buscar-*.json")).read_text(encoding="utf-8"))
    assert fase_json["_diagnostico"]["codigo_salida"] == 1 and fase_json["errors"], fase_json
    # Salida que no es JSON: se conservan salida, stderr y código
    out, _ = diario(falso, "--prueba", "--origen-db", str(base), "--fases", "buscar", modo="no_json")
    f = ultimo_diario()[0][0]
    assert f["estado"] == "error" and f["codigo_salida"] == 3 and f["subtype"] == "salida_no_json", f
    assert "fallo interno del CLI" in f["stderr"] and "fallo interno del CLI" in f["detalle"], f
    print("D5 errores OK (simulada)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    shutil.rmtree(db.RAIZ / "data" / "tmp" / "prueba", ignore_errors=True)
    base = paso0()
    paso1(base)
    paso2(base)
    d4_stdin(base)
    d5_errores(base)
