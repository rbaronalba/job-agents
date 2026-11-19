"""Contratos de los agentes de .claude/agents: quién usa Gmail y qué instrucciones de seguridad llevan.  python -m pytest src/test_agentes.py"""
import pytest

from . import db
from .testing.entorno import herramientas_de_agente, nombres_de_agentes, usa_gmail_directamente

AGENTES = db.RAIZ / ".claude" / "agents"
NECESARIAS = {"mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread", "mcp__claude_ai_Gmail__get_message",
              "mcp__claude_ai_Gmail__list_drafts", "mcp__claude_ai_Gmail__get_draft", "mcp__claude_ai_Gmail__create_draft",
              "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__list_labels", "mcp__claude_ai_Gmail__create_label",
              "mcp__claude_ai_Gmail__label_message"}


def leer(nombre: str) -> str:
    return (AGENTES / f"{nombre}.md").read_text(encoding="utf-8")


def test_los_agentes_existentes_son_los_revisados():
    assert nombres_de_agentes(AGENTES) == ["adaptador", "buscador", "correo", "espontaneas", "postulador"]


def test_correo_tiene_las_herramientas_de_gmail_y_bash():
    assert NECESARIAS <= herramientas_de_agente(AGENTES / "correo.md") and "Bash" in herramientas_de_agente(AGENTES / "correo.md")


def test_correo_consulta_el_modo_y_conoce_la_prueba():
    assert "src.cli modo" in leer("correo") and "prueba" in leer("correo")


@pytest.mark.parametrize("agente", ["adaptador", "espontaneas", "postulador"])
def test_solo_correo_y_buscador_usan_gmail_directamente(agente):
    assert usa_gmail_directamente(AGENTES / f"{agente}.md") is False


def test_espontaneas_delega_en_correo():
    assert "`correo`" in leer("espontaneas")


def test_espontaneas_nunca_pregunta_y_salta_la_empresa_que_lo_necesite():
    assert "nunca uses `AskUserQuestion`" in leer("espontaneas") and "salta esa empresa" in leer("espontaneas")


def test_buscador_no_guarda_nada_si_filtrar_falla():
    assert "Si `filtrar` falla" in leer("buscador")
