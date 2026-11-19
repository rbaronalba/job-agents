"""CV: composición, plantilla, PDF verificado y perfiles.  python -m pytest src/test_cv.py

Usa cv/cv_base.example.yaml y un perfil temporal: nunca el CV ni el perfil reales. La generación de PDF usa Chromium (Playwright).
"""
from argparse import Namespace

import pytest

from . import cli, cv, db
from .testing.entorno import cv_ejemplo, preparar_cv

SKILLS = [["Frontend", "Angular, TypeScript, RxJS, Tests unitarios"]]
CLAVES = ["Angular", "TypeScript", "RxJS", "Test", "Kubernetes"]


@pytest.fixture
def base(tmp_path, monkeypatch):
    preparar_cv(tmp_path)
    monkeypatch.setattr(cv, "BASE", tmp_path / "cv_base.yaml")
    monkeypatch.setattr(cv, "PROFILE", tmp_path / "profile.yaml")
    return tmp_path


@pytest.fixture(scope="module")
def informes(tmp_path_factory):
    """Un CV en español y otro en inglés, generados una vez (Chromium tarda unos segundos)."""
    carpeta = preparar_cv(tmp_path_factory.mktemp("cv"))
    adaptacion = {"skills": SKILLS, "palabras_clave": CLAVES}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cv, "BASE", carpeta / "cv_base.yaml")
        mp.setattr(cv, "PROFILE", carpeta / "profile.yaml")
        return {"es": cv.generar({"idioma": "es", **adaptacion}, carpeta / "es"),
                "en": cv.generar({"idioma": "en", **adaptacion}, carpeta / "en")}


# --- nombre del PDF --------------------------------------------------------------------------------------------------
def test_el_nombre_del_pdf_sale_del_candidato(base):
    assert cv.titulo_pdf() == "CV_AnaMariaLopez" and cv.nombre_pdf() == "CV_AnaMariaLopez.pdf"


def test_sin_perfil_el_nombre_es_generico(base, monkeypatch):
    monkeypatch.setattr(cv, "PROFILE", base / "no-existe.yaml")
    assert cv.titulo_pdf() == "CV_Candidato"


# --- composición -----------------------------------------------------------------------------------------------------
def test_componer_sin_adaptacion_devuelve_el_cv_base(base):
    c, contacto = cv.componer({"idioma": "es"})
    assert c["experiencia"][0]["id"] == "job1" and contacto["nombre"] == "Nombre Apellidos"


def test_componer_sustituye_titular_resumen_y_skills(base):
    c, _ = cv.componer({"idioma": "es", "titular": "T", "resumen": "R", "skills": SKILLS})
    assert (c["titular"], c["resumen"], c["skills"]) == ("T", "R", SKILLS)


def test_componer_sustituye_las_vinetas_de_un_puesto(base):
    c, _ = cv.componer({"idioma": "es", "bullets": {"job1": ["nueva viñeta"]}})
    assert c["experiencia"][0]["bullets"] == ["nueva viñeta"]


def test_componer_elige_proyectos_por_id_e_ignora_los_desconocidos(base):
    c, _ = cv.componer({"idioma": "es", "proyectos": ["nope", "project1"]})
    assert len(c["proyectos"]) == 1 and c["proyectos"][0]["id"] == "project1"


def test_componer_con_perfil_aplica_su_titular(base):
    c, _ = cv.componer({"idioma": "es", "perfil": "ia"})
    assert c["titular"] == "IA es | Datos"


def test_la_plantilla_escapa_el_html_de_la_adaptacion(base):
    pagina = cv.html({"idioma": "es", "titular": "<script>alert(1)</script>"})
    assert "&lt;script&gt;" in pagina and "<script>alert(1)" not in pagina


# --- generar y verificar ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["a — b", "a – b"])
def test_generar_rechaza_guiones_largos_o_medios(base, tmp_path, texto):
    with pytest.raises(ValueError, match="guiones"):
        cv.generar({"idioma": "es", "resumen": texto}, tmp_path / "x")


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_el_cv_sale_en_una_pagina_con_metadatos(informes, idioma):
    inf = informes[idioma]
    assert inf["paginas"] == 1
    assert inf["titulo_pdf"] == "CV_AnaMariaLopez" and inf["autor_pdf"] == "Nombre Apellidos"
    assert inf["guiones_prohibidos"] == []


def test_el_pdf_lleva_el_contacto_del_cv(informes):
    assert "linkedin.com/in/tu-perfil" in informes["es"]["texto"]


def test_la_coincidencia_admite_plural_y_lista_lo_que_falta(informes):
    inf = informes["es"]
    assert inf["coincidencia"] == 80 and inf["faltan"] == ["Kubernetes"]      # "Test" encuentra "Tests"


def test_sin_palabras_clave_no_hay_coincidencia(base, tmp_path):
    assert cv.generar({"idioma": "es"}, tmp_path / "y")["coincidencia"] is None


def test_cv_base_genera_un_pdf_por_clave_e_idioma(base, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RAIZ", base)
    cli.cmd_cv(Namespace(id="base"))
    salida = capsys.readouterr().out
    assert "cv/ia/en/CV_AnaMariaLopez.pdf: 1 página(s)" in salida
    assert (base / "cv" / "ia" / "en" / "CV_AnaMariaLopez.pdf").exists()


# --- perfiles de CV --------------------------------------------------------------------------------------------------
def test_sin_perfiles_hay_uno_solo_con_el_cv_base():
    ps, avisos = cv.perfiles_cv({}, cv_ejemplo())
    assert len(ps) == 1 and avisos == []
    assert (ps[0]["id"], ps[0]["cv"], ps[0]["defecto"], ps[0]["carpeta"]) == ("principal", "base", True, "cv/base")


def test_el_asunto_sale_del_titular_y_hay_un_cv_fijo_por_idioma():
    ps, _ = cv.perfiles_cv({}, cv_ejemplo())
    assert ps[0]["asunto"] == {"es": "Dev", "en": "Dev EN"} and cv.cvs_fijos(cv_ejemplo()) == [("base", "es"), ("base", "en")]


def test_cv_base_con_perfiles_da_un_cv_fijo_por_clave_e_idioma():
    b = cv_ejemplo(perfiles={"a": {"titular": "Alfa | q"}, "b": {"titular": "Beta | q"}})
    assert cv.cvs_fijos(b) == [("a", "es"), ("a", "en"), ("b", "es"), ("b", "en")]


def test_un_perfil_por_clave_y_el_primero_es_el_de_defecto():
    ps, _ = cv.perfiles_cv({}, cv_ejemplo(perfiles={"a": {"titular": "Alfa | q"}, "b": {"titular": "Beta | q"}}))
    assert (ps[0]["id"], ps[1]["id"], len(ps)) == ("a", "b", 2)
    assert ps[0]["defecto"] is True and not ps[1]["defecto"] and ps[1]["asunto"]["es"] == "Beta"


def test_dos_perfiles_de_candidatura_pueden_compartir_cv_y_un_cv_inexistente_avisa():
    b = cv_ejemplo(perfiles={"a": {"titular": "Alfa | q"}, "b": {"titular": "Beta | q"}})
    cfg = {"perfiles_cv": {"x": {"cv": "a", "cuando": "web", "asunto": {"es": "Frontend"}}, "y": {"cv": "a", "defecto": True},
                           "z": {"cv": "nope"}}}
    ps, avisos = cv.perfiles_cv(cfg, b)
    assert (ps[0]["carpeta"], ps[1]["carpeta"], ps[2]["carpeta"]) == ("cv/a", "cv/a", "cv/nope")
    assert ps[0]["asunto"]["es"] == "Frontend" and ps[1]["defecto"] is True and not ps[0]["defecto"]
    assert len(avisos) == 1 and "nope" in avisos[0]


def test_cv_base_junto_a_perfiles_avisa():
    b = cv_ejemplo(perfiles={"a": {"titular": "Alfa | q"}})
    assert cv.perfiles_cv({"perfiles_cv": {"x": {"cv": "base"}}}, b)[1]
