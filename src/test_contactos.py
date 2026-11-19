"""Resultados desde candidaturas.xlsx, silencios, contactos y seguimiento.  python -m pytest src/test_contactos.py"""
from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

from . import cli, db
from .testing.entorno import escenario_contactos

HOY = date(2026, 11, 16)
CFG = {"encaje_minimo": 60, "seguimiento_dias": 12, "max_diario": 10}
XLSX = [{"Empresa": "Rech", "Puesto": "Frontend", "Fase": "Rechazado", "Notas": "Rechazo (12/11)"},
        {"Empresa": "Otra", "Puesto": "X", "Fase": "En curso", "Notas": "Ha respondido, entrevista el lunes", "Ref": "li:Entr"}]


@pytest.fixture
def escenario():
    """Seis candidaturas enviadas, ya sincronizadas con XLSX: Rech (rechazo), Entr (entrevista), Calla (silencio)."""
    con = db.conectar(Path(":memory:"))
    ids = escenario_contactos(con)
    cambios = cli.sincronizar(con, XLSX, HOY)
    estado = lambda e: con.execute("SELECT estado FROM ofertas WHERE id = ?", (ids[e],)).fetchone()[0]
    return con, ids, estado, cambios


def test_sincronizar_aplica_rechazo_entrevista_y_silencio(escenario):
    con, ids, estado, cambios = escenario
    assert (estado("Rech"), estado("Entr"), estado("Calla"), estado("Nueva")) == ("rechazo", "entrevista", "silencio_14d", "enviada"), cambios
    assert len(cambios) == 3


def test_sincronizar_nunca_retrocede(escenario):
    con, ids, estado, _ = escenario
    cli.sincronizar(con, [], date(2026, 12, 30))        # pasan más de 14 días sin noticias
    assert estado("Entr") == "entrevista" and estado("Rech") == "rechazo"


def test_contactar_a_quien_no_tiene_contacto_y_buen_encaje(escenario):
    con, *_ = escenario
    p = cli.contactos_pendientes(con, CFG, HOY)
    # Baja (encaje 40) queda fuera; Calla, en silencio, sigue entrando; orden: la enviada más reciente primero
    assert [o["empresa"] for o in p["contactar"]] == ["Nueva", "Seguir", "Calla"] and p["seguir"] == []


def test_seguimiento_a_los_13_dias_y_no_a_los_11(escenario):
    con, ids, *_ = escenario
    con.execute("UPDATE ofertas SET contacto = 'Ana | TA | url', contacto_fecha = '2026-11-04' WHERE id = ?", (ids["Seguir"],))
    con.execute("UPDATE ofertas SET contacto = 'no encontrado', contacto_fecha = '2026-11-15' WHERE id = ?", (ids["Nueva"],))
    p = cli.contactos_pendientes(con, CFG, HOY)
    assert [o["empresa"] for o in p["contactar"]] == ["Calla"] and [o["empresa"] for o in p["seguir"]] == ["Seguir"]
    assert cli.contactos_pendientes(con, CFG, date(2026, 11, 14))["seguir"] == []


@pytest.mark.parametrize("nota", ["x" * 301, "hola — adiós", "hola – adiós"])
def test_nota_de_contacto_invalida_se_rechaza(escenario, monkeypatch, nota):
    con, ids, *_ = escenario
    monkeypatch.setattr(db, "conectar", lambda ruta=None: con)        # monkeypatch lo restaura al acabar el test
    with pytest.raises(SystemExit):
        cli.cmd_contacto(Namespace(id=ids["Seguir"], persona=None, nota=nota, seguimiento=None))


def test_nota_de_contacto_de_300_caracteres_es_valida(escenario, monkeypatch, capsys):
    con, ids, *_ = escenario
    monkeypatch.setattr(db, "conectar", lambda ruta=None: con)
    cli.cmd_contacto(Namespace(id=ids["Seguir"], persona="Ana | TA | url", nota="x" * 300, seguimiento=None))
    assert con.execute("SELECT nota_contacto FROM ofertas WHERE id = ?", (ids["Seguir"],)).fetchone()[0] == "x" * 300


def test_embudo_de_la_escenario(escenario):
    con, ids, *_ = escenario
    con.execute("UPDATE ofertas SET contacto = 'Ana | TA | url' WHERE id = ?", (ids["Seguir"],))
    e = cli.embudo(con)
    assert e["total"]["enviadas"] == 6 and e["total"]["rechazo"] == 1 and e["contacto"]["sí"]["enviadas"] == 1, e


def test_embudo_de_espontaneas():
    esp = [{"Puesto": "Candidatura espontánea", "Fase": "Rechazado"},
           {"Puesto": "Candidatura espontánea", "Fase": "En curso", "Notas": "Ha respondido (04/11)"},
           {"Puesto": "Frontend", "Fase": "Rechazado"}]
    assert cli.embudo_espontaneas(esp) == {"enviadas": 2, "respuesta": 1, "entrevista": 0, "rechazo": 1}
    assert cli.embudo_espontaneas([]) == {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0}
