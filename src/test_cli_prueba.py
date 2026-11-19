"""CLI en modo prueba: aislamiento, huella, listados compactos, preparar, pendientes y cv base.  python -m pytest src/test_cli_prueba.py"""
import pytest

from .cli import CAMPOS_LISTA
from .cv import nombre_pdf
from .testing.entorno import ids_por_estado, oferta_con_cv, csv_empresas, marcar_enviada_hoy, sello_arbol
from . import db


# --- modo prueba -----------------------------------------------------------------------------------------------------
def test_prueba_sin_base_alternativa_se_niega_a_abrir_el_historico_real(sandbox):
    r = sandbox.cli("listar", prueba=True, base=False)
    assert r.returncode != 0 and "no se toca el histórico real" in r.stdout + r.stderr


def test_modo_en_prueba_es_revision_y_borrador(sandbox):
    m = sandbox.json("modo", prueba=True)
    assert (m["portales"], m["espontaneas"], m["prueba"]) == ("revision", "borrador", True)
    assert "prueba" in m["empresas_csv"] and "prueba" in m["output"]


def test_en_prueba_enviada_nunca_se_envia(sandbox):
    oid = ids_por_estado(sandbox.base, "cv_adaptado")[0]
    antes = sandbox.json("huella")
    r = sandbox.cli("enviada", oid, "--origen", "LinkedIn", prueba=True)
    assert r.returncode != 0 and "nunca se envía" in r.stdout + r.stderr
    assert sandbox.json("huella") == antes


def test_en_prueba_estado_enviada_nunca_se_envia(sandbox):
    oid = ids_por_estado(sandbox.base, "cv_adaptado")[0]
    antes = sandbox.json("huella")
    r = sandbox.cli("estado", oid, "enviada", prueba=True)
    assert r.returncode != 0 and "nunca se envía" in r.stdout + r.stderr
    assert sandbox.json("huella") == antes


def test_cv_base_se_niega_en_prueba_y_no_toca_cv(sandbox):
    antes = sello_arbol(db.RAIZ / "cv")
    r = sandbox.cli("cv", "base", prueba=True)
    assert r.returncode != 0 and "no se ejecuta en modo prueba" in r.stdout + r.stderr
    assert sello_arbol(db.RAIZ / "cv") == antes


def test_excel_y_logs_de_prueba_van_a_la_carpeta_de_datos(sandbox):
    assert "ofertas" in sandbox.cli("excel", prueba=True).stdout.replace("\\", "/")
    sandbox.cli("resumen", prueba=True)
    assert len(list((sandbox.datos / "logs").glob("*.md"))) == 1


# --- huella ----------------------------------------------------------------------------------------------------------
def test_huella_es_estable_e_integra(sandbox):
    h = sandbox.json("huella")
    assert (h["integridad"], h["total"]) == ("ok", 5)
    assert sandbox.json("huella") == h


def test_estado_de_una_oferta_inexistente_falla_sin_tocar_nada(sandbox):
    antes = sandbox.json("huella")
    assert sandbox.cli("estado", "2026-W00-001", "nueva").returncode != 0
    assert sandbox.json("huella") == antes


def test_un_cambio_de_estado_cambia_la_huella(sandbox):
    antes = sandbox.json("huella")
    sandbox.cli("estado", ids_por_estado(sandbox.base, "nueva")[0], "descartada", prueba=True)
    despues = sandbox.json("huella")
    assert despues["sha256"] != antes["sha256"] and despues["por_estado"]["descartada"] == 1


# --- listar y oferta -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("estado", ["nueva", "cv_adaptado", "pendiente_revision", "enviada", "descartada"])
def test_listar_compacto_y_completo_tienen_los_mismos_ids_y_el_orden(sandbox, estado):
    compacto = sandbox.json("listar", "--estado", estado, "--json")
    completo = sandbox.json("listar", "--estado", estado, "--json", "--completo")
    assert [o["id"] for o in compacto] == [o["id"] for o in completo]


@pytest.mark.parametrize("estado, cuantas", [("nueva", 2), ("cv_adaptado", 2), ("enviada", 1)])
def test_listar_compacto_solo_lleva_los_campos_acordados(sandbox, estado, cuantas):
    compacto = sandbox.json("listar", "--estado", estado, "--json")
    assert len(compacto) == cuantas
    assert list(compacto[0]) == CAMPOS_LISTA and list(compacto[-1]) == CAMPOS_LISTA


def test_listar_no_modifica_la_base(sandbox):
    antes = sandbox.json("huella")
    sandbox.cli("listar", "--json", "--completo")
    assert sandbox.json("huella") == antes


def test_oferta_inexistente_falla(sandbox):
    assert sandbox.cli("oferta", "no-existe").returncode != 0


def test_oferta_con_campos_elegidos(sandbox):
    oid = sandbox.json("listar", "--json")[0]["id"]
    assert list(sandbox.json("oferta", oid, "--campos", "titulo,texto")) == ["id", "titulo", "texto"]


# --- preparar y perfil-formulario ------------------------------------------------------------------------------------
@pytest.fixture
def con_cv(sandbox):
    """Una oferta con CV adaptado y su PDF falso en la carpeta de salida de la prueba."""
    oid, semana = oferta_con_cv(sandbox.base)
    carpeta = sandbox.datos / "output" / semana / oid
    carpeta.mkdir(parents=True)
    (carpeta / nombre_pdf()).write_bytes(b"%PDF-1.4 prueba")
    return oid


def test_preparar_con_perfil_incluye_candidato_y_respuestas(sandbox, con_cv):
    datos = sandbox.json("preparar", con_cv, prueba=True)
    assert "candidato" in datos and "respuestas" in datos and datos["modo"] == "revision"


def test_preparar_sin_perfil_omite_candidato_y_deja_el_cv_en_la_carpeta_de_prueba(sandbox, con_cv):
    datos = sandbox.json("preparar", con_cv, "--sin-perfil", prueba=True)
    assert "candidato" not in datos and datos["modo"] == "revision" and "datos" in datos["cv"]


def test_preparar_con_y_sin_perfil_solo_difieren_en_candidato_y_respuestas(sandbox, con_cv):
    con = sandbox.json("preparar", con_cv, prueba=True)
    sin = sandbox.json("preparar", con_cv, "--sin-perfil", prueba=True)
    con.pop("candidato"), con.pop("respuestas")
    assert con == sin


def test_perfil_formulario_devuelve_lo_que_el_postulador_necesita(sandbox):
    pf = sandbox.json("perfil-formulario", prueba=True)
    assert set(pf) == {"candidato", "respuestas", "modo", "salario_minimo"} and pf["modo"] == "revision"


# --- pendientes: cupos con un perfil de cupos conocidos (30 total, 15 portales, 12 espontáneas) -----------------------
@pytest.fixture
def con_actividad_de_hoy(sandbox):
    """Una enviada por portal hoy y dos espontáneas hoy (X enviada, Y borrador), más antiguas y pendientes que no cuentan."""
    marcar_enviada_hoy(sandbox.base, ids_por_estado(sandbox.base, "enviada")[0])
    from datetime import date
    hoy = date.today().isoformat()
    csv_empresas(sandbox.datos / "empresas.csv", [f"X,,,,,,enviada,{hoy}", f"Y,,,,,,borrador,{hoy}",
                                                   "Z,,,,,,enviada,2020-01-01", "W,,,,,,pendiente,"])


def test_pendientes_lista_la_cola_por_encaje(sandbox, con_actividad_de_hoy):
    p = sandbox.json("pendientes", prueba=True)
    assert p["nuevas"] == ids_por_estado(sandbox.base, "nueva") and p["cv_adaptado"] == ids_por_estado(sandbox.base, "cv_adaptado")


def test_pendientes_cuenta_lo_enviado_hoy(sandbox, con_actividad_de_hoy):
    p = sandbox.json("pendientes", prueba=True)
    assert len(p["enviadas_hoy"]) == 1 and p["espontaneas_hoy"] == ["X", "Y"]


def test_pendientes_cupos_del_dia(sandbox, con_actividad_de_hoy):
    p = sandbox.json("pendientes", prueba=True)
    assert p["cupo_portales"] == 14       # min(15 de portales - 1 enviada, 30 en total - 3 enviadas hoy)
    assert p["cupo_espontaneas"] == 10    # min(12 de objetivo, 15 máximo, 30 - 1) - 2 espontáneas hoy
    assert p["prueba"] is True
