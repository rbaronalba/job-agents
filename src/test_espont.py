"""Clasificación, cola e informe de espontáneas, sin red.  python -m src.test_espont"""
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from src import cv, db, espont

ANILLOS = [["Alfa"], ["Beta", "Gamma"], ["Delta"]]
fila = lambda **k: {"empresa": "X", "estado": "pendiente", "ciudad": "Alfa", **k}


def test_validar():
    assert espont.validar_fila(fila()) == []                                   # fila antigua: válida, sin clasificar
    ok = dict(categoria="B", compatibilidad="media", senal="sin_vacante_publicada", destinatario="empleo")
    assert espont.validar_fila(fila(**ok)) == []
    assert espont.validar_fila(fila(**{**ok, "categoria": "A"}))               # A exige vacante confirmada
    assert espont.validar_fila(fila(**{**ok, "categoria": "A", "senal": "vacante_confirmada", "compatibilidad": "baja"})) == []  # independientes
    assert espont.validar_fila(fila(**{**ok, "estado": "enviada", "compatibilidad": "baja"}))   # baja no se envía
    assert espont.validar_fila(fila(**{**ok, "estado": "borrador", "categoria": "D"}))
    assert espont.validar_fila(fila(**{**ok, "senal": "quizá"}))
    assert espont.validar_fila(fila(categoria="C"))                            # faltan datos


def test_cola():
    base = dict(compatibilidad="alta", senal="necesidad_potencial", destinatario="rrhh")
    filas = [fila(empresa="sinclas"), fila(empresa="C-cor", categoria="C", **base),
             fila(empresa="B-sev", categoria="B", ciudad="Beta", **base), fila(empresa="B-cor", categoria="B", **base),
             fila(empresa="A-sev", categoria="A", ciudad="Gamma", **{**base, "senal": "vacante_confirmada"}),
             fila(empresa="D", categoria="D", **base), fila(empresa="baja", categoria="B", **{**base, "compatibilidad": "baja"}),
             fila(empresa="lejos", categoria="A", ciudad="Delta", **base), fila(empresa="env", estado="enviada"),
             fila(empresa="ret", estado="retenida")]
    orden = [f["empresa"] for f in espont.cola(filas, ANILLOS, 1, db.norm)]
    assert orden == ["A-sev", "B-cor", "B-sev", "C-cor", "sinclas"], orden    # A>B>C>sin; anillo desempata; sin D/baja/lejos/retenida
    assert espont.cola([], ANILLOS, 0, db.norm) == []                          # sin relleno


def test_informe():
    envs = [fila(empresa=f"E{i}", estado="enviada", fecha="2026-11-02", categoria="B", destinatario="general",
                 tecnologias="TecX; TecY") for i in range(12)]
    res = {f"E{i}": r for i, r in enumerate(["entrevista", "rechazo", None] + [None] * 8)}   # E11 sin fila en el Excel
    inf = espont.informe(envs + [fila(empresa="pend")], res)
    t = inf["total"]
    assert (t["enviadas"], t["entrevista"], t["rechazo"], t["sin_respuesta"]) == (12, 1, 1, 10)   # sin respuesta != rechazo
    assert inf["sin_fila_en_excel"] == 1 and inf["tecnologia"]["tecx"]["enviadas"] == 12
    assert espont.nivel_muestra(9) == "muestra muy pequeña" and espont.nivel_muestra(10) == "exploratorio"
    assert espont.nivel_muestra(19) == "exploratorio" and espont.nivel_muestra(20) == "descriptivo"
    assert "[exploratorio]" in espont.texto(inf) and "12 enviadas" in espont.texto(inf)
    sin = espont.informe(envs, None)                                            # Excel ausente: ni un cero ni una tasa
    assert sin["total"]["entrevista"] == 0 and sin["total"]["sin_respuesta"] == 0
    assert "seguimiento no disponible" in espont.texto(sin)


def test_perfiles():
    cvb = lambda **k: {"es": {"titular": "Dev | X", **k}, "en": {"titular": "Dev EN | X"}}
    # sin perfiles ni perfiles_cv: uno solo, con el CV base
    ps, av = cv.perfiles_cv({}, cvb())
    assert [(p["id"], p["cv"], p["defecto"], p["carpeta"]) for p in ps] == [("principal", "base", True, "cv/base")] and av == []
    assert ps[0]["asunto"] == {"es": "Dev", "en": "Dev EN"} and cv.cvs_fijos(cvb()) == [("base", "es"), ("base", "en")]
    # el número de perfiles lo da cv_base: un CV fijo por clave e idioma, y un perfil por clave sin perfiles_cv
    b = cvb(perfiles={"a": {"titular": "Alfa | q"}, "b": {"titular": "Beta | q"}})
    assert cv.cvs_fijos(b) == [("a", "es"), ("a", "en"), ("b", "es"), ("b", "en")]
    ps, av = cv.perfiles_cv({}, b)
    assert [p["id"] for p in ps] == ["a", "b"] and ps[0]["defecto"] and not ps[1]["defecto"] and ps[1]["asunto"]["es"] == "Beta"
    # perfiles_cv: dos perfiles de candidatura pueden compartir CV; cv inexistente avisa
    cfg = {"perfiles_cv": {"x": {"cv": "a", "cuando": "web", "asunto": {"es": "Frontend"}}, "y": {"cv": "a", "defecto": True},
                           "z": {"cv": "nope"}}}
    ps, av = cv.perfiles_cv(cfg, b)
    assert [p["carpeta"] for p in ps] == ["cv/a", "cv/a", "cv/nope"] and ps[0]["asunto"]["es"] == "Frontend"
    assert ps[1]["defecto"] and not ps[0]["defecto"] and len(av) == 1 and "nope" in av[0], av
    assert cv.perfiles_cv({"perfiles_cv": {"x": {"cv": "base"}}}, b)[1]                       # base con perfiles: aviso


def test_cli_solo_lectura():
    """CSV antiguo (8 columnas) y nuevo: las consultas funcionan y no tocan el archivo."""
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "e.csv"
        ruta.write_text("empresa,web,email,ciudad,sector,notas,estado,fecha\nAcme,https://a.es,rrhh@a.es,Alfa,Software,,pendiente,\n"
                        "Beta,https://b.es,info@b.es,Alfa,Software,,retenida,2026-01-01\n", encoding="utf-8")
        h = hashlib.sha256(ruta.read_bytes()).hexdigest()
        ejecutar = lambda *a: subprocess.run([sys.executable, "-m", "src.cli", *a], cwd=db.RAIZ, capture_output=True,
                                              text=True, encoding="utf-8")
        r = ejecutar("espontaneas-consulta", "--csv", str(ruta))
        c = json.loads(r.stdout.strip().splitlines()[-1])["clasificacion"]
        assert c["cola"] == ["Acme"] and c["retenidas_sin_evaluar"] == 1 and c["avisos"] == [], c
        r = ejecutar("espontaneas-informe", "--csv", str(ruta), "--excel", str(Path(d) / "no.xlsx"))
        assert r.returncode == 0 and "AVISO: no hay candidaturas.xlsx" in r.stdout, r.stderr
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == h
        ruta.write_text(ruta.read_text(encoding="utf-8").replace("estado,fecha", "estado,fecha,categoria,compatibilidad,senal,destinatario,tecnologias")
                        .replace(",pendiente,", ",pendiente,,A,alta,sin_evidencia,rrhh,").replace(",retenida,2026-01-01", ",retenida,2026-01-01,,,,,"), encoding="utf-8")
        c = json.loads(ejecutar("espontaneas-consulta", "--csv", str(ruta)).stdout.strip().splitlines()[-1])["clasificacion"]
        assert c["avisos"] and c["por_categoria"]["A"] == 1, c                  # A sin vacante confirmada: aviso, no se rompe
    # ponytail: el cruce con el Excel real se prueba a mano con `python -m src.cli espontaneas-informe`


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print(n, "OK")
