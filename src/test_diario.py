"""Orquestador (src.diario) con un `claude` falso: fases, lotes, errores y seguridad.  python -m pytest src/test_diario.py"""
from types import SimpleNamespace

import pytest

from . import db
from .cli import modos
from .diario import SIN_PERFIL, _seguro, estado_de
from .testing.entorno import (argumento, base_vacia, con_chrome, estados, fases_lanzadas, ids_por_estado, json_de_fase,
                              lotes_lanzados, prompts, prompts_sin)


# --- un día completo en modo prueba (se ejecuta una vez y se comprueba por partes) -----------------------------------
@pytest.fixture(scope="module")
def dia(sandbox_del_modulo):
    sb = sandbox_del_modulo
    antes = sb.json("huella")
    salida, llamadas = sb.diario_prueba()
    return SimpleNamespace(sb=sb, salida=salida, llamadas=llamadas, huella_antes=antes, cv=ids_por_estado(sb.base, "cv_adaptado"))


def test_dia_completo_lanza_las_fases_en_orden(dia):
    assert fases_lanzadas(dia.llamadas) == ["/buscar", "/adaptar", "/postular", "/espontaneas", "/post"]


def test_postular_recibe_todos_los_cv_adaptados_en_un_lote(dia):
    assert dia.llamadas[2]["argv"][1].startswith("/postular " + " ".join(dia.cv))


def test_espontaneas_recibe_el_cupo_completo_del_dia(dia):
    assert dia.llamadas[3]["argv"][1].startswith("/espontaneas 12 ")


def test_solo_postular_y_espontaneas_usan_chrome(dia):
    assert con_chrome(dia.llamadas) == [False, False, True, True, False]


def test_todas_las_sesiones_usan_la_copia_del_historico(dia):
    assert [l["db"] for l in dia.llamadas] == [str(dia.sb.datos / "historico.sqlite")] * 5
    assert [l["prueba"] for l in dia.llamadas] == ["1"] * 5


@pytest.mark.parametrize("marca", ["MODO PRUEBA", "ESTADO_FASE"])
def test_todos_los_prompts_llevan_la_marca(dia, marca):
    assert prompts_sin(dia.llamadas, marca) == []


def test_seguimiento_vacio_y_email_no_enviado_en_prueba(dia):
    fases, _ = dia.sb.ultima_ejecucion()
    assert estados(fases)["seguimiento"] == "vacia" and "email de resumen no enviado" in dia.salida


def test_la_base_de_origen_no_cambia_en_prueba(dia):
    assert dia.sb.json("huella") == dia.huella_antes


# --- lotes, topes y paradas ------------------------------------------------------------------------------------------
def test_lotes_de_uno(sandbox):
    cv = ids_por_estado(sandbox.base, "cv_adaptado")
    _, ll = sandbox.diario_prueba("--lote", "1", "--fases", "postular")
    assert lotes_lanzados(ll) == [["/postular", cv[0]], ["/postular", cv[1]]]


def test_max_ofertas_limita_postular_y_espontaneas(sandbox):
    cv = ids_por_estado(sandbox.base, "cv_adaptado")
    _, ll = sandbox.diario_prueba("--max-ofertas", "1", "--fases", "postular,espontaneas")
    assert lotes_lanzados(ll) == [["/postular", cv[0]], ["/espontaneas", "1"]]


def test_sin_chrome_no_se_intenta_espontaneas(sandbox):
    salida, ll = sandbox.diario_prueba("--fases", "postular,espontaneas", FALSO_MODO="sin_chrome")
    assert fases_lanzadas(ll) == ["/postular"] and "Chrome no disponible" in salida


def test_limite_de_uso_en_buscar_no_lanza_nada_mas(sandbox):
    salida, ll = sandbox.diario_prueba(FALSO_MODO="limite")
    assert fases_lanzadas(ll) == ["/buscar"] and salida.count("omitida") == 6   # adaptar, postular, espontaneas, seguimiento, contactos y post


def test_fases_vacias_no_arrancan_ninguna_sesion(sandbox, tmp_path):
    salida, ll = sandbox.diario("--prueba", "--origen-db", str(base_vacia(tmp_path)), "--fases", "adaptar,postular")
    assert ll == [] and salida.count("vacia") == 2


def test_simular_no_lanza_claude(sandbox):
    salida, ll = sandbox.diario_prueba("--simular")
    assert ll == [] and "simulado" in salida


def test_el_stdin_de_las_sesiones_queda_cerrado(sandbox):
    _, ll = sandbox.diario_prueba("--fases", "buscar", stdin_abierto=True)
    assert [l["stdin_cerrado"] for l in ll] == [True]


def test_modo_real_manda_el_resumen_en_un_archivo(sandbox):
    _, ll = sandbox.diario_real("--fases", "postular,resumen")
    assert fases_lanzadas(ll) == ["/postular", "Lee"] and "email_resumen.md" in ll[-1]["argv"][1]
    assert [l["prueba"] for l in ll] == [None, None]


@pytest.mark.parametrize("variable, esperado", [(None, ["/diario"]), ("nuevo", [])])
def test_diario_bat_elige_la_sesion_unica_o_src_diario(sandbox, variable, esperado):
    assert prompts(sandbox.diario_bat(JOB_AGENTS_DIARIO=variable)) == esperado


# --- errores del CLI de Claude ---------------------------------------------------------------------------------------
def test_error_max_turns_se_registra_con_su_motivo(sandbox):
    sandbox.diario_prueba("--fases", "buscar", FALSO_MODO="max_turns")
    fases, carpeta = sandbox.ultima_ejecucion()
    f = fases[0]
    assert (f["estado"], f["codigo_salida"], f["is_error"]) == ("error", 1, True)
    assert f["subtype"] == "error_max_turns" and f["errors"] == ["Reached maximum number of turns (1)"]
    assert "Reached maximum number of turns" in f["detalle"]
    assert json_de_fase(carpeta, "buscar")["_diagnostico"]["codigo_salida"] == 1


def test_salida_que_no_es_json_conserva_salida_stderr_y_codigo(sandbox):
    sandbox.diario_prueba("--fases", "buscar", FALSO_MODO="no_json")
    f = sandbox.ultima_ejecucion()[0][0]
    assert (f["estado"], f["codigo_salida"], f["subtype"]) == ("error", 3, "salida_no_json")
    assert "fallo interno del CLI" in f["stderr"] and "fallo interno del CLI" in f["detalle"]


# --- seguridad del orquestador ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("envio", [{}, {"modo": "revision"}, {"modo": "auto", "espontaneas_modo": "envia"},
                                   {"modo": "Auto", "espontaneas_modo": "borrador"}])
def test_modos_nunca_supone_un_modo(envio):
    with pytest.raises(SystemExit):
        modos({"envio": envio})


def test_modos_acepta_auto_y_borrador():
    assert modos({"envio": {"modo": "auto", "espontaneas_modo": "borrador"}})["portales"] == "auto"


def test_con_el_modo_roto_no_se_lanza_postular_ni_espontaneas(sandbox, crear_diario, monkeypatch):
    from .testing.entorno import CliFalso
    d = crear_diario(prueba=True, fases=["postular", "espontaneas"])
    monkeypatch.setattr(d, "cli", CliFalso(fallan=("modo",)))
    d.postular()
    d.espontaneas()
    assert sandbox.llamadas() == []
    assert [(f["fase"], f["estado"]) for f in d.fases] == [("postular", "error"), ("espontaneas", "error")]
    assert "src.cli modo falló" in d.fases[0]["detalle"] and "src.cli modo falló" in d.fases[1]["detalle"]


def test_una_tanda_de_postular_con_error_detiene_la_fase(sandbox):
    _, ll = sandbox.diario_prueba("--lote", "1", "--fases", "postular", FALSO_MODO="error_postular")
    assert fases_lanzadas(ll) == ["/postular"]


def test_el_postulador_no_puede_leer_ni_editar_el_perfil(sandbox):
    _, ll = sandbox.diario_prueba("--lote", "1", "--fases", "postular")
    assert SIN_PERFIL in argumento(ll[0], "--disallowedTools")


def test_seguimiento_se_lanza_desde_la_raiz_y_delega_en_correo(sandbox, crear_diario, monkeypatch):
    d = crear_diario(fases=["seguimiento"])
    monkeypatch.setattr(d, "pendientes", lambda: {"candidaturas_sync": "candidaturas-sync"})
    d.seguimiento()
    ll = sandbox.llamadas()
    assert len(ll) == 1 and ll[0]["cwd"] == str(db.RAIZ)
    assert "candidaturas-sync/.claude/commands/revisar.md" in ll[0]["argv"][1] and "subagente correo" in ll[0]["argv"][1]


def test_el_resumen_por_email_delega_en_correo(sandbox):
    _, ll = sandbox.diario_real("--fases", "resumen")
    assert len(ll) == 1 and "subagente correo" in ll[0]["argv"][1] and "email_resumen.md" in ll[0]["argv"][1]


# --- utilidades ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    ("ESTADO_FASE: **error** — modo prueba activo", "error"),
    ("hecho\nESTADO_FASE: ok", "ok"),
    ("**ESTADO_FASE:** sin_chrome", "sin_chrome"),
    ("ESTADO_FASE: `vacio`", "vacio"),
    ("ESTADO_FASE: ok al principio\n...\nESTADO_FASE: error", "error"),      # manda la última
    ("ESTADO_FASE: pasos 1.1 y 1.2 completados", None),                       # valor desconocido: no cuenta
    ("ESTADO_FASE", None),
    ("sin marca", None),
    ("", None),
])
def test_estado_de(texto, esperado):
    assert estado_de(texto) == esperado


@pytest.mark.parametrize("malo", ['a"b', "a&b", "a|b", "a\nb", "50%"])
def test_seguro_rechaza_argumentos_peligrosos_para_cmd(malo):
    with pytest.raises(ValueError):
        _seguro(malo)


@pytest.mark.parametrize("bueno", ["/buscar", "Lee C:/x/y.md", "texto normal con acentos: áéí"])
def test_seguro_deja_pasar_texto_normal(bueno):
    assert _seguro(bueno) == bueno
