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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    shutil.rmtree(db.RAIZ / "data" / "tmp" / "prueba", ignore_errors=True)
    paso1(paso0())
