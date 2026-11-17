"""Resultados desde candidaturas.xlsx, silencios, contactos y seguimiento (python -m src.test_contactos)."""
import contextlib
import io
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path

from . import cli, db


def main():
    con = db.conectar(Path(":memory:"))
    ids = {}
    for emp, enc, env in (("Rech", 80, "2026-11-10"), ("Entr", 80, "2026-11-10"), ("Calla", 80, "2026-11-01"),
                          ("Nueva", 70, "2026-11-15"), ("Baja", 40, "2026-11-15"), ("Seguir", 90, "2026-11-03")):
        ids[emp], _ = db.guardar(con, {"empresa": emp, "titulo": "Frontend", "encaje": enc, "ids_externos": [f"li:{emp}"]})
        con.execute("UPDATE ofertas SET estado = 'enviada', enviada = ? WHERE id = ?", (env, ids[emp]))
    hoy = date(2026, 11, 16)
    xlsx = [{"Empresa": "Rech", "Puesto": "Frontend", "Fase": "Rechazado", "Notas": "Rechazo (12/11)"},
            {"Empresa": "Otra", "Puesto": "X", "Fase": "En curso", "Notas": "Ha respondido, entrevista el lunes", "Ref": "li:Entr"}]
    cambios = cli.sincronizar(con, xlsx, hoy)
    estado = lambda e: con.execute("SELECT estado FROM ofertas WHERE id = ?", (ids[e],)).fetchone()[0]
    assert (estado("Rech"), estado("Entr"), estado("Calla"), estado("Nueva")) == \
        ("rechazo", "entrevista", "silencio_14d", "enviada"), cambios
    # Nunca retrocede: una entrevista no vuelve a silencio aunque pasen 14 días
    cli.sincronizar(con, [], date(2026, 12, 30))
    assert estado("Entr") == "entrevista" and estado("Rech") == "rechazo"
    con.execute("UPDATE ofertas SET estado = 'enviada' WHERE id IN (?, ?)", (ids["Nueva"], ids["Seguir"]))

    cfg = {"encaje_minimo": 60, "seguimiento_dias": 12, "max_diario": 10}
    p = cli.contactos_pendientes(con, cfg, hoy)
    assert [o["empresa"] for o in p["contactar"]] == ["Nueva", "Seguir", "Calla"] and p["seguir"] == [], p   # Baja: encaje 40; Calla (silencio_14d) sigue sin contacto y entra
    con.execute("UPDATE ofertas SET contacto = 'Ana | TA | url', contacto_fecha = '2026-11-04' WHERE id = ?", (ids["Seguir"],))
    con.execute("UPDATE ofertas SET contacto = 'no encontrado', contacto_fecha = '2026-11-15' WHERE id = ?", (ids["Nueva"],))
    p = cli.contactos_pendientes(con, cfg, hoy)
    assert [o["empresa"] for o in p["contactar"]] == ["Calla"] and [o["empresa"] for o in p["seguir"]] == ["Seguir"], p   # 13 días: toca seguimiento
    assert cli.contactos_pendientes(con, cfg, date(2026, 11, 14))["seguir"] == []           # 11 días: aún no

    # contacto: máximo 300 caracteres y sin guiones largos
    db_real, db.RUTA = db.RUTA, Path(":memory:")
    try:
        cli.db.conectar = lambda ruta=None, c=con: c
        for nota in ("x" * 301, "hola — adiós"):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.cmd_contacto(Namespace(id=ids["Seguir"], persona=None, nota=nota, seguimiento=None))
                raise AssertionError(nota)
            except SystemExit:
                pass
    finally:
        db.RUTA = db_real
    e = cli.embudo(con)
    assert e["total"]["enviadas"] == 6 and e["total"]["rechazo"] == 1 and e["contacto"]["sí"]["enviadas"] == 1, e
    esp = [{"Puesto": "Candidatura espontánea", "Fase": "Rechazado"},
           {"Puesto": "Candidatura espontánea", "Fase": "En curso", "Notas": "Ha respondido (04/11)"},
           {"Puesto": "Frontend", "Fase": "Rechazado"}]
    assert cli.embudo_espontaneas(esp) == {"enviadas": 2, "respuesta": 1, "entrevista": 0, "rechazo": 1}
    print("test_contactos OK")


if __name__ == "__main__":
    sys.exit(main())
