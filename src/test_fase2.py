"""Robustez de resultados, ids externos, contactos y embudo, sin red.  python -m pytest src/test_fase2.py"""
from datetime import date
from pathlib import Path

import pytest

from . import cli, db
from .testing.entorno import enviadas

HOY = date(2026, 11, 17)


@pytest.fixture
def con():
    return db.conectar(Path(":memory:"))


def estado(con, oid):
    return con.execute("SELECT estado FROM ofertas WHERE id=?", (oid,)).fetchone()[0]


# --- resultado_de: una negación no es una respuesta ------------------------------------------------------------------
@pytest.mark.parametrize("notas", ["No ha respondido", "sin respuesta", "no responde", "Sin entrevista todavía", "nunca llamada",
                                   "ni respuesta", "NO HA RESPONDIDO", "", None])
def test_resultado_de_negaciones_no_cuentan(notas):
    assert cli.resultado_de("Enviada", notas) is None


@pytest.mark.parametrize("fase, notas, esperado", [
    ("Enviada", "ha respondido por email", "respuesta"),
    ("Enviada", "Entrevista el lunes", "entrevista"),
    ("Enviada", "Me han llamado para una videollamada", "entrevista"),
    ("Enviada", "no ha respondido, pero luego me llamó: entrevista el lunes", "entrevista"),
    ("Completado", "", "respuesta"),
    ("Rechazado", "", "rechazo"),
    ("Rechazado", "no ha respondido", "rechazo"),          # el rechazo manda sobre las notas
])
def test_resultado_de(fase, notas, esperado):
    assert cli.resultado_de(fase, notas) == esperado


# --- ids externos: '_' y '%' no son comodines ------------------------------------------------------------------------
def test_buscar_por_id_externo_exacto(con):
    a, _ = db.guardar(con, {"empresa": "Acme", "titulo": "Dev", "ids_externos": ["li:100"]})
    b, _ = db.guardar(con, {"empresa": "Acme Soft", "titulo": "Dev", "ids_externos": ["li:100_"]})
    assert a != b
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": ["li:100"]})["id"] == a
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": ["li:100_"]})["id"] == b


@pytest.mark.parametrize("ext", ["li:10_", "li:%", "li:1%", "%", "li:10"])
def test_buscar_comodines_no_unen_ofertas(con, ext):
    db.guardar(con, {"empresa": "Acme", "titulo": "Dev", "ids_externos": ["li:100"]})
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": [ext]}) is None


# --- sincronizar: sin Excel no se inventan silencios -----------------------------------------------------------------
def test_sincronizar_sin_excel_no_marca_silencios(con):
    oid = enviadas(con, ["Acme"])["Acme"]
    assert cli.sincronizar(con, None, HOY) == []
    assert estado(con, oid) == "enviada"


def test_sincronizar_excel_vacio_si_marca_silencios(con):
    oid = enviadas(con, ["Acme"])["Acme"]
    assert len(cli.sincronizar(con, [], HOY)) == 1 and estado(con, oid) == "silencio_14d"


def test_sincronizar_no_marca_silencio_antes_de_14_dias(con):
    oid = enviadas(con, ["Reciente"], dias=13)["Reciente"]
    assert cli.sincronizar(con, [], HOY) == [] and estado(con, oid) == "enviada"


def test_sincronizar_solo_avanza(con):
    oid = enviadas(con, ["Acme"])["Acme"]
    cli.sincronizar(con, [{"Empresa": "Acme", "Puesto": "Dev", "Fase": "Rechazado"}], HOY)
    assert estado(con, oid) == "rechazo"
    cli.sincronizar(con, [], date(2027, 1, 1))                         # 14 días después: no vuelve a silencio
    assert estado(con, oid) == "rechazo"


# --- contactos y embudo ----------------------------------------------------------------------------------------------
CFG = {"seguimiento_dias": 7, "encaje_minimo": 60, "max_diario": 10}


def test_contactar_incluye_los_silencios(con):
    enviadas(con, ["Silencio"])
    cli.sincronizar(con, [], HOY)
    assert [o["empresa"] for o in cli.contactos_pendientes(con, CFG, HOY)["contactar"]] == ["Silencio"]


def test_contactar_respeta_el_encaje_minimo(con):
    enviadas(con, ["Baja"], encaje=40)
    assert cli.contactos_pendientes(con, CFG, HOY)["contactar"] == []


def test_embudo_total_cuenta_por_estado(con):
    enviadas(con, ["A", "B", "C"])
    cli.sincronizar(con, [{"Empresa": "A", "Puesto": "Dev", "Fase": "Rechazado"}], HOY)
    assert cli.embudo_total(con) == {"enviadas": 3, "respuesta": 0, "entrevista": 0, "rechazo": 1, "silencio_14d": 2}


def test_embudo_total_vacio(con):
    assert cli.embudo_total(con) == {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0, "silencio_14d": 0}


def test_embudo_total_coincide_con_embudo(con):
    enviadas(con, ["A", "B"])
    cli.sincronizar(con, [], HOY)
    assert cli.embudo(con)["total"] == cli.embudo_total(con)
