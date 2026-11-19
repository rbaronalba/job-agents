"""Clasificación, cola, informe y perfiles de CV de las espontáneas, sin red.  python -m pytest src/test_espont.py"""
import pytest

from . import db, espont
from .testing.entorno import (ANILLOS, CLASIFICACION_VALIDA as OK, csv_antiguo, csv_clasificado, envios_para_el_informe,
                              fila, filas_de_la_cola, resultados_del_informe, sello)


# --- validar_fila ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("campos, valida", [
    ({}, True),                                                                              # fila antigua: sin clasificar
    (OK, True),
    ({**OK, "categoria": "A"}, False),                                                       # A exige vacante confirmada
    ({**OK, "categoria": "A", "senal": "vacante_confirmada", "compatibilidad": "baja"}, True),   # son independientes
    ({**OK, "estado": "enviada", "compatibilidad": "baja"}, False),                          # baja no se envía
    ({**OK, "estado": "borrador", "categoria": "D"}, False),
    ({**OK, "senal": "quizá"}, False),
    ({"categoria": "C"}, False),                                                             # faltan datos
])
def test_validar_fila(campos, valida):
    assert (espont.validar_fila(fila(**campos)) == []) is valida


# --- cola ------------------------------------------------------------------------------------------------------------
def test_cola_ordena_por_categoria_y_anillo_y_descarta_lo_que_no_toca():
    orden = espont.cola(filas_de_la_cola(), ANILLOS, 1, db.norm)
    # A > B > C > sin clasificar; el anillo desempata; sin D, compatibilidad baja, anillo lejano, enviadas ni retenidas
    assert [f["empresa"] for f in orden] == ["A-sev", "B-cor", "B-sev", "C-cor", "sinclas"]


def test_cola_sin_filas_no_rellena():
    assert espont.cola([], ANILLOS, 0, db.norm) == []


# --- informe ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def informe():
    return espont.informe(envios_para_el_informe(), resultados_del_informe())


def test_informe_distingue_sin_respuesta_de_rechazo(informe):
    t = informe["total"]
    assert (t["enviadas"], t["entrevista"], t["rechazo"], t["sin_respuesta"]) == (12, 1, 1, 10)


def test_informe_cuenta_las_enviadas_sin_fila_en_el_excel_y_las_tecnologias(informe):
    assert informe["sin_fila_en_excel"] == 1 and informe["tecnologia"]["tecx"]["enviadas"] == 12


def test_informe_en_texto_marca_el_nivel_de_la_muestra(informe):
    assert "[exploratorio]" in espont.texto(informe) and "12 enviadas" in espont.texto(informe)


@pytest.mark.parametrize("n, nivel", [(9, "muestra muy pequeña"), (10, "exploratorio"), (19, "exploratorio"), (20, "descriptivo")])
def test_nivel_de_muestra(n, nivel):
    assert espont.nivel_muestra(n) == nivel


def test_informe_sin_excel_no_inventa_ceros_ni_tasas():
    sin = espont.informe(envios_para_el_informe(), None)
    assert sin["total"]["entrevista"] == 0 and sin["total"]["sin_respuesta"] == 0
    assert "seguimiento no disponible" in espont.texto(sin)


# --- CLI de solo lectura: CSV antiguo (8 columnas) y nuevo -----------------------------------------------------------
def test_consulta_con_csv_antiguo_deja_la_cola_y_las_retenidas(sandbox, tmp_path):
    c = sandbox.json("espontaneas-consulta", "--csv", str(csv_antiguo(tmp_path / "e.csv")), base=False)["clasificacion"]
    assert c["cola"] == ["Acme"] and c["retenidas_sin_evaluar"] == 1 and c["avisos"] == []


def test_informe_sin_excel_avisa_y_no_falla(sandbox, tmp_path):
    r = sandbox.cli("espontaneas-informe", "--csv", str(csv_antiguo(tmp_path / "e.csv")), "--excel", str(tmp_path / "no.xlsx"), base=False)
    assert r.returncode == 0 and "AVISO: no hay candidaturas.xlsx" in r.stdout


def test_las_consultas_no_tocan_el_csv(sandbox, tmp_path):
    ruta = csv_antiguo(tmp_path / "e.csv")
    antes = sello([ruta])
    sandbox.cli("espontaneas-consulta", "--csv", str(ruta), base=False)
    sandbox.cli("espontaneas-informe", "--csv", str(ruta), "--excel", str(tmp_path / "no.xlsx"), base=False)
    assert sello([ruta]) == antes


def test_categoria_a_sin_vacante_confirmada_avisa_pero_no_rompe(sandbox, tmp_path):
    c = sandbox.json("espontaneas-consulta", "--csv", str(csv_clasificado(tmp_path / "e.csv")), base=False)["clasificacion"]
    assert c["avisos"] and c["por_categoria"]["A"] == 1
