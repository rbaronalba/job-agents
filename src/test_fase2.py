"""Pruebas offline de la fase 2 de seguridad y robustez: python -m src.test_fase2"""
import json
import sqlite3
import tempfile
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path

from . import cli, db


def main():
    # Una negación no es una respuesta ni una entrevista
    r = cli.resultado_de
    for notas in ("No ha respondido", "sin respuesta", "no responde", "Sin entrevista todavía", "nunca llamada", "ni respuesta"):
        assert r("Enviada", notas) is None, notas
    assert r("Enviada", "ha respondido por email") == "respuesta"
    assert r("Enviada", "Entrevista el lunes") == "entrevista"
    assert r("Enviada", "no ha respondido, pero luego me llamó: entrevista el lunes") == "entrevista"
    assert r("Rechazado", "") == "rechazo"

    con = db.conectar(Path(":memory:"))
    hace = (date.today() - timedelta(days=30)).isoformat()
    a, _ = db.guardar(con, {"empresa": "Acme", "titulo": "Dev", "ids_externos": ["li:100"]})
    b, _ = db.guardar(con, {"empresa": "Acme Soft", "titulo": "Dev", "ids_externos": ["li:100_"]})
    assert a != b
    # '_' y '%' no son comodines: li:10_ no encuentra li:100
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": ["li:10_"]}) is None
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": ["li:%"]}) is None
    assert db.buscar(con, {"empresa": "X", "titulo": "Y", "ids_externos": ["li:100"]})["id"] == a

    # Sin Excel (None) no se inventan silencios; con Excel vacío, sí
    for oid in (a, b):
        con.execute("UPDATE ofertas SET estado='enviada', enviada=? WHERE id=?", (hace, oid))
    assert cli.sincronizar(con, None, date.today()) == []
    assert con.execute("SELECT COUNT(*) FROM ofertas WHERE estado='enviada'").fetchone()[0] == 2
    assert len(cli.sincronizar(con, [], date.today())) == 2

    # Los silencios siguen en 'contactar'; el total del embudo sale de un COUNT
    cfg = {"seguimiento_dias": 7, "encaje_minimo": 0, "max_diario": 10}
    con.execute("UPDATE ofertas SET encaje=90")
    assert len(cli.contactos_pendientes(con, cfg)["contactar"]) == 2
    assert cli.embudo_total(con)["enviadas"] == 2 and cli.embudo_total(con)["silencio_14d"] == 2
    print("test_fase2: OK")


if __name__ == "__main__":
    main()
