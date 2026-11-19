"""Excel semanal de ofertas: exportar, editar a mano Estado/Notas y volver a SQLite.  python -m pytest src/test_excel.py"""
import pytest
from openpyxl import Workbook

from . import db, excel
from .testing.entorno import celda_excel, editar_excel


@pytest.fixture
def ofertas(con, carpeta_excel):
    """A (encaje 80), B (encaje 40 con eliminatorio) y C descartada con encaje 99: orden esperado A, B, C."""
    a, _ = db.guardar(con, {"empresa": "A", "titulo": "Front", "encaje": 80, "urls": ["https://x/1"], "portales": ["linkedin"]})
    b, _ = db.guardar(con, {"empresa": "B", "titulo": "Angular", "encaje": 40, "eliminatorios": "+5 años"})
    c, _ = db.guardar(con, {"empresa": "C", "titulo": "Vue", "encaje": 99, "estado": "descartada"})
    return {"a": a, "b": b, "c": c, "semana": db.semana(), "con": con}


def estado(con, oid):
    return con.execute("SELECT estado FROM ofertas WHERE id = ?", (oid,)).fetchone()[0]


def notas(con, oid):
    return con.execute("SELECT notas FROM ofertas WHERE id = ?", (oid,)).fetchone()[0]


# --- exportar --------------------------------------------------------------------------------------------------------
def test_exportar_ordena_por_encaje_y_deja_las_descartadas_al_final(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    assert (celda_excel(ruta, "ID", 2), celda_excel(ruta, "ID", 3), celda_excel(ruta, "ID", 4)) == (ofertas["a"], ofertas["b"], ofertas["c"])


def test_exportar_pone_el_enlace_y_los_portales(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    assert celda_excel(ruta, "Enlace", 2) == "Abrir" and celda_excel(ruta, "Portales", 2) == "linkedin"


def test_exportar_sin_semana_usa_la_actual(ofertas):
    ruta, _ = excel.exportar(ofertas["con"])
    assert ruta.name == f"ofertas_{ofertas['semana']}.xlsx"


def test_exportar_una_semana_vacia_genera_la_hoja_con_cabecera(con, carpeta_excel):
    ruta, cambios = excel.exportar(con, "2020-W01")
    assert cambios == [] and celda_excel(ruta, "ID", 1) == "ID" and celda_excel(ruta, "ID", 2) is None


def test_exportar_con_el_excel_abierto_pide_cerrarlo(ofertas, monkeypatch):
    def denegado(self, destino):
        raise PermissionError
    monkeypatch.setattr(Workbook, "save", denegado)
    with pytest.raises(SystemExit, match="ciérralo en Excel"):
        excel.exportar(ofertas["con"], ofertas["semana"])


# --- ediciones a mano ------------------------------------------------------------------------------------------------
def test_importar_sin_excel_previo_no_cambia_nada(ofertas):
    assert excel.importar_cambios(ofertas["con"], "2020-W01") == []


def test_el_estado_editado_en_excel_vuelve_a_sqlite(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    editar_excel(ruta, "Estado", 2, "descartada")
    _, cambios = excel.exportar(ofertas["con"], ofertas["semana"])
    assert estado(ofertas["con"], ofertas["a"]) == "descartada"
    assert cambios == [f"{ofertas['a']}: nueva -> descartada (editado en Excel)"]


def test_las_notas_editadas_en_excel_vuelven_a_sqlite(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    editar_excel(ruta, "Notas", 3, "no me interesa")
    _, cambios = excel.exportar(ofertas["con"], ofertas["semana"])
    assert notas(ofertas["con"], ofertas["b"]) == "no me interesa" and cambios == [f"{ofertas['b']}: notas editadas en Excel"]


def test_un_estado_invalido_en_excel_se_ignora_y_se_avisa(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    editar_excel(ruta, "Estado", 2, "inventado")
    _, cambios = excel.exportar(ofertas["con"], ofertas["semana"])
    assert estado(ofertas["con"], ofertas["a"]) == "nueva" and cambios == [f"{ofertas['a']}: estado 'inventado' no válido, se ignora"]


def test_una_fila_sin_id_se_ignora(ofertas):
    ruta, _ = excel.exportar(ofertas["con"], ofertas["semana"])
    editar_excel(ruta, "ID", 2, None)
    editar_excel(ruta, "Estado", 2, "descartada")
    _, cambios = excel.exportar(ofertas["con"], ofertas["semana"])
    assert cambios == [] and estado(ofertas["con"], ofertas["a"]) == "nueva"


def test_sin_ediciones_no_se_reimporta_nada(ofertas):
    excel.exportar(ofertas["con"], ofertas["semana"])
    assert excel.exportar(ofertas["con"], ofertas["semana"])[1] == []
