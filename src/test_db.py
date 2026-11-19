"""Histórico SQLite: claves, fusión entre portales, estados, filtro de calidad y migraciones.  python -m pytest src/test_db.py"""
import sqlite3
from datetime import date

import pytest

from . import db

TALAN = {"empresa": "Talan Spain S.L.", "titulo": "Front-End Developer (Angular)", "portales": ["linkedin"],
         "urls": ["https://li/1"], "ids_externos": ["li:1"], "encaje": 70}


# --- clave y normalización -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    ("Desarrollador/a Frontend (m/f/d)", "desarrollador a frontend"),
    ("  Ángel   NÚÑEZ ", "angel nunez"),
    (None, ""),
])
def test_norm(texto, esperado):
    assert db.norm(texto) == esperado


@pytest.mark.parametrize("a, b", [(("Talan Spain S.L.", "Dev"), ("TALAN", "dev")), (("Acme, S.A.", "X"), ("acme", "x"))])
def test_clave_ignora_sufijos_legales_y_mayusculas(a, b):
    assert db.clave(*a) == db.clave(*b)


def test_semana_tiene_formato_iso():
    assert db.semana(date(2026, 11, 17)) == "2026-W47"


# --- guardar: deduplicación y fusión ---------------------------------------------------------------------------------
def test_guardar_una_oferta_nueva(con):
    oid, nueva = db.guardar(con, TALAN)
    assert nueva and oid.endswith("-001")


def test_guardar_el_mismo_puesto_en_otro_portal_se_fusiona(con):
    a, _ = db.guardar(con, TALAN)
    b, nueva = db.guardar(con, {"empresa": "TALAN", "titulo": "Front-End Developer", "portales": ["tecnoempleo"],
                                "urls": ["https://te/9"], "encaje": None})
    assert b == a and not nueva


def test_la_fusion_une_portales_y_urls_y_no_pisa_con_vacios(con):
    a, _ = db.guardar(con, TALAN)
    db.guardar(con, {"empresa": "TALAN", "titulo": "Front-End Developer", "portales": ["tecnoempleo"], "urls": ["https://te/9"], "encaje": None})
    f = con.execute("SELECT portales, urls, encaje FROM ofertas WHERE id = ?", (a,)).fetchone()
    assert f["portales"] == '["linkedin", "tecnoempleo"]' and f["urls"] == '["https://li/1", "https://te/9"]' and f["encaje"] == 70


def test_un_id_externo_ya_guardado_identifica_la_oferta(con):
    a, _ = db.guardar(con, TALAN)
    assert db.guardar(con, {"empresa": "Otra", "titulo": "X", "ids_externos": ["li:1"]}) == (a, False)


def test_guardar_serializa_los_requisitos(con):
    oid, _ = db.guardar(con, {"empresa": "A", "titulo": "T", "requisitos": ["Angular", "RxJS"]})
    assert con.execute("SELECT requisitos FROM ofertas WHERE id = ?", (oid,)).fetchone()[0] == '["Angular", "RxJS"]'


def test_al_fusionar_los_requisitos_nuevos_tambien_se_serializan(con):
    oid, _ = db.guardar(con, {"empresa": "A", "titulo": "T"})
    db.guardar(con, {"empresa": "A", "titulo": "T", "requisitos": ["Vue"]})
    assert con.execute("SELECT requisitos FROM ofertas WHERE id = ?", (oid,)).fetchone()[0] == '["Vue"]'


def test_la_numeracion_con_huecos_no_repite_ids(con):
    uno, _ = db.guardar(con, {"empresa": "Hueco", "titulo": "Uno"})
    dos, _ = db.guardar(con, {"empresa": "Hueco", "titulo": "Dos"})
    con.execute("DELETE FROM ofertas WHERE id = ?", (uno,))
    tres, nueva = db.guardar(con, {"empresa": "Hueco", "titulo": "Tres"})
    assert nueva and tres > dos


# --- estados ---------------------------------------------------------------------------------------------------------
def test_marcar_enviada_fija_la_fecha_y_anota(con):
    oid, _ = db.guardar(con, {"empresa": "A", "titulo": "T"})
    db.cambiar_estado(con, oid, "enviada", "por LinkedIn")
    f = con.execute("SELECT estado, enviada, notas FROM ofertas WHERE id = ?", (oid,)).fetchone()
    assert (f["estado"], f["enviada"], f["notas"]) == ("enviada", date.today().isoformat(), "por LinkedIn")


def test_las_notas_se_acumulan(con):
    oid, _ = db.guardar(con, {"empresa": "A", "titulo": "T", "notas": "antes"})
    db.cambiar_estado(con, oid, "descartada", "después")
    assert con.execute("SELECT notas FROM ofertas WHERE id = ?", (oid,)).fetchone()[0] == "antes; después"


def test_un_estado_que_no_existe_se_rechaza(con):
    with pytest.raises(ValueError, match="Estado no válido"):
        db.cambiar_estado(con, "x", "inventado")


def test_una_oferta_que_no_existe_se_rechaza(con):
    with pytest.raises(ValueError, match="No existe la oferta"):
        db.cambiar_estado(con, "2026-W00-001", "nueva")


def test_en_prueba_nunca_se_marca_enviada(con, monkeypatch):
    oid, _ = db.guardar(con, {"empresa": "A", "titulo": "T"})
    monkeypatch.setattr(db, "PRUEBA", True)
    with pytest.raises(SystemExit, match="nunca se envía"):
        db.cambiar_estado(con, oid, "enviada")


# --- filtro de calidad -----------------------------------------------------------------------------------------------
BASE_FILTRO = {"titulo": "Frontend", "eliminatorios": "", "encaje": 90}


@pytest.mark.parametrize("cambios, esperado", [
    ({"titulo": "Senior Angular Dev"}, "puesto Senior"),
    ({"titulo": "Sr. Frontend"}, "puesto Senior"),
    ({"eliminatorios": "presencial fuera"}, "eliminatorio: presencial fuera"),
    ({"encaje": 50}, "encaje 50 < 55"),
    ({"titulo": "JavaScript Developer"}, None),
    ({"titulo": "Full Stack Java & Angular"}, None),         # Java y .NET ya no excluyen
    ({"titulo": ".NET + Angular"}, None),
    ({"encaje": None}, None),                                # alertas sin texto: no se filtra por encaje
    ({"titulo": None}, None),
    ({"eliminatorios": None}, None),
])
def test_motivo_filtro(cambios, esperado):
    assert db.motivo_filtro({**BASE_FILTRO, **cambios}, 55) == esperado


# --- conexión y migraciones ------------------------------------------------------------------------------------------
def test_conectar_migra_las_columnas_de_contacto_de_bases_anteriores(tmp_path):
    ruta = tmp_path / "vieja.sqlite"
    db.conectar(ruta).close()
    antigua = sqlite3.connect(ruta)
    antigua.execute("ALTER TABLE ofertas DROP COLUMN contacto_fecha")
    antigua.commit()
    antigua.close()
    con = db.conectar(ruta)
    assert "contacto_fecha" in {r[1] for r in con.execute("PRAGMA table_info(ofertas)")}


def test_en_prueba_no_se_abre_el_historico_real(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PRUEBA", True)
    monkeypatch.setattr(db, "RUTA_REAL", tmp_path / "real.sqlite")
    with pytest.raises(SystemExit, match="no se toca el histórico real"):
        db.conectar(tmp_path / "real.sqlite")


def test_corta_deja_relativa_una_ruta_del_proyecto_y_absoluta_otra_ajena(tmp_path):
    assert db.corta(db.RAIZ / "src" / "db.py").as_posix() == "src/db.py"
    assert db.corta(tmp_path / "x.txt") == tmp_path / "x.txt"
