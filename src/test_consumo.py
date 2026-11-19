"""Consumo de tokens desde los transcripts de Claude Code.  python -m pytest src/test_consumo.py"""
import json
from pathlib import Path

import pytest

from . import consumo
from .testing.transcripts import agentes_cargados, asistente, escribir, resultado, usuario


@pytest.fixture
def sesion(tmp_path):
    """Analiza un transcript con las líneas dadas."""
    return lambda *lineas: consumo.analizar(escribir(tmp_path / "s.jsonl", list(lineas)))


# --- utilidades ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nombre, esperado", [
    ("mcp__claude_ai_Composio__COMPOSIO_SEARCH_TOOLS", "composio:SEARCH_TOOLS"),
    ("mcp__claude-in-chrome__navigate", "chrome:navigate"),
    ("mcp__claude_ai_Gmail__send_message", "gmail:send_message"),
    ("Bash", "Bash"),
])
def test_herramienta_abrevia_los_servidores_mcp(nombre, esperado):
    assert consumo._herramienta(nombre) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("<command-name>/buscar</command-name>", "/buscar"),
    ("  /diario --prueba", "/diario"),
    ("hola, ¿qué tal?", None),
])
def test_comando(texto, esperado):
    assert consumo._comando(texto) == esperado


def test_la_carpeta_de_transcripts_se_nombra_con_la_ruta_del_proyecto(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert consumo.proyecto_por_defecto(Path("C:/Users/x/Mi proyecto")) == tmp_path / ".claude" / "projects" / "C--Users-x-Mi-proyecto"


# --- analizar --------------------------------------------------------------------------------------------------------
def test_analizar_suma_tokens_y_calcula_las_unidades_equivalentes(sesion):
    s, _ = sesion(usuario("/buscar"), asistente("a", entrada=100, cache_w=1000, cache_r=10000, salida=20),
                  asistente("b", entrada=50, cache_w=0, cache_r=20000, salida=10))
    assert (s["in_tok"], s["cache_w"], s["cache_r"], s["out_tok"], s["llamadas"]) == (150, 1000, 30000, 30, 2)
    assert s["equiv"] == 150 + 1250 + 3000 + 150      # 1 por entrada, 1,25 caché escrita, 0,1 caché leída, 5 salida


def test_una_respuesta_en_streaming_cuenta_una_sola_vez(sesion):
    s, _ = sesion(asistente("a", entrada=100), asistente("a", entrada=100), asistente("a", entrada=100))
    assert s["llamadas"] == 1 and s["in_tok"] == 100


def test_las_lineas_corruptas_se_ignoran(sesion):
    s, _ = sesion("esto no es json", "{", asistente("a", entrada=7))
    assert s["in_tok"] == 7


def test_el_comando_es_el_primer_mensaje_de_usuario_que_no_es_meta(sesion):
    s, _ = sesion(usuario("<local-command-caveat>", meta=True), usuario("/adaptar"), usuario("/buscar"), asistente("a"))
    assert s["comando"] == "/adaptar"


def test_un_mensaje_sin_comando_es_un_chat(sesion):
    assert sesion(usuario("hola"), asistente("a"))[0]["comando"] == "chat"


def test_el_texto_de_usuario_puede_venir_en_bloques(sesion):
    mensaje = {"type": "user", "message": {"content": [{"type": "text", "text": "/post"}, "ruido"]}}
    assert sesion(mensaje, asistente("a"))[0]["comando"] == "/post"


def test_sin_mensajes_de_usuario_el_comando_es_desconocido(sesion):
    assert sesion(asistente("a"))[0]["comando"] == "?"


def test_marca_inicio_y_fin(sesion):
    s, _ = sesion(usuario("/buscar", ts="2026-11-17T10:00:00Z"), asistente("a", ts="2026-11-17T10:09:00Z"))
    assert (s["inicio"], s["fin"]) == ("2026-11-17T10:00:00Z", "2026-11-17T10:09:00Z")


def test_cuenta_llamadas_y_caracteres_por_herramienta(sesion):
    _, herr = sesion(asistente("a", herramientas=[("t1", "Bash"), ("t2", "mcp__claude-in-chrome__navigate")]),
                     resultado("t1", "12345"), resultado("t2", [{"type": "text", "text": "x"}]),
                     asistente("b", herramientas=[("t3", "Bash")]), resultado("t3", "ab"))
    assert herr["Bash"] == [2, 7] and herr["chrome:navigate"][0] == 1


def test_un_resultado_de_una_herramienta_desconocida_va_a_interrogante(sesion):
    _, herr = sesion(asistente("a"), resultado("no-existe", "abc"))
    assert herr == {"?": [0, 3]}


def test_cuenta_las_imagenes(sesion):
    s, _ = sesion(asistente("a", herramientas=[("t1", "mcp__claude-in-chrome__computer")]),
                  resultado("t1", [{"type": "image"}, {"type": "image"}, {"type": "text", "text": "x"}]))
    assert s["imagenes"] == 2


def test_percentiles_del_contexto(sesion):
    s, _ = sesion(asistente("a", entrada=10), asistente("b", entrada=20), asistente("c", entrada=30),
                  asistente("d", entrada=40), asistente("e", entrada=100))
    assert (s["ctx_p50"], s["ctx_p90"], s["ctx_max"]) == (30, 40, 100)


def test_el_modelo_es_el_mas_usado_sin_contar_los_sinteticos(sesion):
    s, _ = sesion(asistente("a", modelo="<synthetic>"), asistente("b", modelo="<synthetic>"), asistente("c", modelo="m1"),
                  asistente("d", modelo="m1"), asistente("e", modelo="m2"))
    assert s["modelo"] == "m1"


def test_una_sesion_sin_llamadas_queda_en_ceros(sesion):
    s, herr = sesion(usuario("/buscar"))
    assert (s["llamadas"], s["modelo"], s["ctx_p50"], s["ctx_p90"], s["ctx_max"], s["equiv"]) == (0, None, 0, 0, 0, 0) and herr == {}


# --- cargar e informe ------------------------------------------------------------------------------------------------
@pytest.fixture
def proyecto(tmp_path):
    """Una sesión principal con un subagente (con meta), otra sin llamadas y un subagente sin meta."""
    p = tmp_path / "proyecto"
    escribir(p / "s1.jsonl", [usuario("/buscar"), asistente("a", entrada=100)])
    escribir(p / "s2.jsonl", [usuario("/adaptar")])
    escribir(p / "s1" / "subagents" / "agent-aaaaaa.jsonl", [asistente("b", entrada=50)])
    (p / "s1" / "subagents" / "agent-aaaaaa.meta.json").write_text(json.dumps({"agentType": "buscador"}), encoding="utf-8")
    escribir(p / "s1" / "subagents" / "agent-bbbbbb.jsonl", [asistente("c", entrada=5)])
    escribir(p / "s1" / "subagents" / "agent-cccccc.jsonl", [usuario("sin llamadas")])
    return p


def test_cargar_importa_la_sesion_principal_y_sus_subagentes(proyecto, tmp_path):
    con = consumo.conectar(tmp_path / "c.sqlite")
    assert consumo.cargar(proyecto, con) == 1                      # s2 no tiene llamadas
    assert agentes_cargados(con) == ["?:bbbbbb", "buscador:aaaaaa", "principal"]


def test_cargar_dos_veces_no_duplica(proyecto, tmp_path):
    con = consumo.conectar(tmp_path / "c.sqlite")
    consumo.cargar(proyecto, con)
    consumo.cargar(proyecto, con)
    assert con.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0] == 3


def test_cargar_guarda_las_herramientas(tmp_path):
    p = tmp_path / "p"
    escribir(p / "s.jsonl", [usuario("/buscar"), asistente("a", herramientas=[("t", "Bash")]), resultado("t", "abc")])
    con = consumo.conectar(tmp_path / "c.sqlite")
    consumo.cargar(p, con)
    assert con.execute("SELECT herramienta, llamadas, chars FROM herramientas").fetchall() == [("Bash", 1, 3)]


def test_informe_lista_las_sesiones(proyecto, tmp_path, capsys):
    con = consumo.conectar(tmp_path / "c.sqlite")
    consumo.cargar(proyecto, con)
    consumo.informe(con)
    salida = capsys.readouterr().out
    assert "sesión" in salida and "principal" in salida and "buscador:aaaaaa" in salida and "/buscar" in salida


def test_informe_desde_filtra_por_fecha(proyecto, tmp_path, capsys):
    con = consumo.conectar(tmp_path / "c.sqlite")
    consumo.cargar(proyecto, con)
    consumo.informe(con, "2027-01-01")
    assert "principal" not in capsys.readouterr().out


def test_main_carga_y_luego_informa(proyecto, tmp_path, capsys):
    destino = str(tmp_path / "c.sqlite")
    consumo.main(["cargar", "--proyecto", str(proyecto), "--db", destino])
    assert "1 sesiones cargadas" in capsys.readouterr().out
    consumo.main(["informe", "--db", destino, "--desde", "2026-01-01"])
    assert "principal" in capsys.readouterr().out
