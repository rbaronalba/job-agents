"""Permisos por fase, hook de Gmail, resumen por email y ya_postuladas (vulnerabilidades 1-4).

Sin sesiones reales: las comprobaciones con Claude de verdad están en `python -m src.test_seguridad` (cuesta dinero).
python -m pytest src/test_permisos.py
"""
import subprocess
import sys
from itertools import product

import pytest

from . import cli, db
from .diario import GMAIL_ESCRITURA, GMAIL_LECTURA, REALES, gmail_permisos, permisos
from .guardia import motivo
from .testing.entorno import CliFalso, argumento, excel_malo, gmail_en, menciones, respuestas_resumen, xlsx

G = "mcp__claude_ai_Gmail__"
FASES = ["buscar", "adaptar", "postular", "espontaneas", "seguimiento", "email"]
ESPONTANEAS = [None, "borrador", "auto"]
TODAS = list(product(FASES, ESPONTANEAS))


def partes(texto: str) -> set[str]:
    return set(texto.split(","))


# --- 1. Gmail: permisos mínimos por fase y modo ----------------------------------------------------------------------
@pytest.mark.parametrize("fase, espontaneas, lectura, escritura", [
    ("buscar", None, GMAIL_LECTURA, []),
    ("adaptar", None, GMAIL_LECTURA, []),
    ("postular", None, GMAIL_LECTURA, []),
    ("seguimiento", None, GMAIL_LECTURA, []),
    ("espontaneas", None, GMAIL_LECTURA, ["create_draft"]),
    ("espontaneas", "borrador", GMAIL_LECTURA, ["create_draft"]),
    ("espontaneas", "auto", GMAIL_LECTURA, ["create_draft", "send_message", "label_message", "create_label"]),
    ("email", None, [], ["send_message"]),                      # el email solo envía
])
def test_gmail_en_produccion(fase, espontaneas, lectura, escritura):
    assert gmail_permisos(fase, False, espontaneas) == (lectura, escritura)


@pytest.mark.parametrize("fase, espontaneas", TODAS)
def test_gmail_en_prueba_es_solo_lectura(fase, espontaneas):
    assert gmail_permisos(fase, True, espontaneas) == (GMAIL_LECTURA, [])


@pytest.mark.parametrize("prueba", [True, False])
@pytest.mark.parametrize("fase, espontaneas", TODAS)
def test_las_listas_de_permisos_reflejan_lo_que_gmail_permite(fase, espontaneas, prueba):
    lectura, escritura = gmail_permisos(fase, prueba, espontaneas)
    permitidas, prohibidas = permisos(fase, prueba, espontaneas)
    assert gmail_en(permitidas) == set(lectura) | set(escritura)
    assert gmail_en(prohibidas) == set(GMAIL_ESCRITURA) - set(escritura)      # lo que no se concede se prohíbe
    assert partes(permitidas) & partes(prohibidas) == set()
    assert "mcp__claude_ai_Gmail" not in partes(permitidas)                   # nunca el servidor entero


@pytest.mark.parametrize("prueba", [True, False])
@pytest.mark.parametrize("fase, espontaneas", TODAS)
def test_siempre_prohibidas_las_herramientas_que_nadie_atiende(fase, espontaneas, prueba):
    assert {"AskUserQuestion", "PowerShell", "NotebookEdit"} <= partes(permisos(fase, prueba, espontaneas)[1])


# --- 2/3. Modo prueba: nada real se toca -----------------------------------------------------------------------------
@pytest.mark.parametrize("fase", FASES)
def test_prueba_prohibe_candidaturas(fase):
    permitidas, prohibidas = permisos(fase, True)
    assert "Bash(python -m candidaturas:*)" in partes(prohibidas) and menciones(permitidas, "candidaturas") == []


@pytest.mark.parametrize("herramienta, ruta", list(product(["Edit", "Write"], REALES)))
def test_prueba_prohibe_escribir_archivos_reales(herramienta, ruta):
    assert f"{herramienta}(//**/{ruta})" in partes(permisos("postular", True)[1])


def test_los_archivos_reales_protegidos_incluyen_lo_esencial():
    assert {"data/empresas.csv", "data/historico.sqlite", "config/**", "cv/**", "candidaturas-sync/**"} <= set(REALES)


@pytest.mark.parametrize("fase", FASES)
def test_produccion_permite_candidaturas_y_no_prohibe_editar(fase):
    permitidas, prohibidas = permisos(fase, False)
    assert "Bash(python -m candidaturas:*)" in partes(permitidas)
    assert menciones(prohibidas, "Edit(//") == [] and menciones(prohibidas, "Write(//") == []


# --- hook src.guardia: lo que los permisos no ven (los argumentos) ---------------------------------------------------
def env(**extra):
    return {"JOB_AGENTS_FASE": "email", "JOB_AGENTS_DESTINO": "yo@ejemplo.es", **extra}


def test_el_resumen_solo_se_envia_al_destino_validado():
    assert motivo(G + "send_message", {"to": ["Yo@Ejemplo.es"]}, env()) is None


@pytest.mark.parametrize("entrada", [{"to": ["otro@ejemplo.es"]}, {"to": ["yo@ejemplo.es", "otro@x.es"]},
                                     {"to": ["yo@ejemplo.es"], "bcc": ["o@x.es"]}, {"to": ["yo@ejemplo.es"], "cc": ["o@x.es"]},
                                     {"draftId": "r1"}, {}])
def test_el_resumen_a_otro_destino_o_con_copias_se_rechaza(entrada):
    assert motivo(G + "send_message", entrada, env())


def test_sin_destino_validado_no_se_envia():
    assert motivo(G + "send_message", {"to": ["yo@ejemplo.es"]}, env(JOB_AGENTS_DESTINO=""))


@pytest.mark.parametrize("fase", ["buscar", "adaptar", "postular", "seguimiento"])
def test_send_message_solo_existe_en_email_y_espontaneas(fase):
    assert motivo(G + "send_message", {"to": ["yo@ejemplo.es"]}, env(JOB_AGENTS_FASE=fase))


@pytest.mark.parametrize("operacion", ["create_draft", "send_message", "label_message", "label_thread", "create_label"])
def test_en_prueba_ninguna_escritura_de_gmail(operacion):
    assert motivo(G + operacion, {"to": ["yo@ejemplo.es"]}, env(JOB_AGENTS_PRUEBA="1", JOB_AGENTS_FASE="espontaneas"))


def test_en_prueba_la_lectura_sigue_permitida():
    assert motivo(G + "search_threads", {}, env(JOB_AGENTS_PRUEBA="1")) is None


def test_fuera_del_orquestador_la_guardia_no_actua():
    assert motivo(G + "send_message", {"to": ["a@b.es"]}, {}) is None


def test_la_guardia_deniega_una_entrada_ilegible():
    r = subprocess.run([sys.executable, "-m", "src.guardia"], input="no json", capture_output=True, text=True, cwd=db.RAIZ,
                       env={"JOB_AGENTS_FASE": "email", "PATH": ""})
    assert r.returncode == 2 and "ilegible" in r.stderr


# --- el orquestador pasa el hook, la fase y el destinatario validado -------------------------------------------------
@pytest.fixture
def resumen(sandbox, crear_diario, monkeypatch):
    """Ejecuta la fase de resumen con el `Diario.cli` indicado; devuelve (diario, llamadas del claude falso)."""
    def ejecutar(cli_falso):
        d = crear_diario(fases=["resumen"])
        monkeypatch.setattr(d, "pendientes", lambda: {"enviadas_hoy": [], "espontaneas_hoy": []})
        monkeypatch.setattr(d, "cli", cli_falso)
        d.resumen()
        return d, sandbox.llamadas()
    return ejecutar


def test_el_resumen_se_lanza_con_el_hook_y_el_destinatario(resumen):
    d, ll = resumen(CliFalso(respuestas_resumen("yo@ejemplo.es")))
    assert len(ll) == 1
    assert argumento(ll[0], "--settings") == "src/guardia.json"
    assert G + "send_message" in argumento(ll[0], "--allowedTools")
    assert "yo@ejemplo.es" in (d.dir_logs / "email_resumen.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("email", ["yo@ejemplo.es, otro@x.es", ""])
def test_el_resumen_no_se_lanza_sin_un_unico_destinatario_valido(resumen, email):
    d, ll = resumen(CliFalso(respuestas_resumen(email)))
    assert ll == [] and d.fases[-1]["estado"] == "error" and "destinatario" in d.fases[-1]["detalle"]


def test_el_resumen_no_se_lanza_con_el_modo_roto(resumen):
    d, ll = resumen(CliFalso(respuestas_resumen("yo@ejemplo.es"), fallan=("modo",)))
    assert ll == [] and d.fases[-1]["estado"] == "error"


# --- ya_postuladas: un Excel ausente, corrupto o ilegible es un error, nunca "cero candidaturas" ---------------------
@pytest.fixture
def con_excel(monkeypatch):
    return lambda ruta: monkeypatch.setattr(cli, "ruta_candidaturas", lambda: ruta)


def test_ya_postuladas_lee_claves_e_ids(tmp_path, con_excel):
    con_excel(xlsx(tmp_path / "c.xlsx", "Candidaturas", [["Empresa", "Puesto", "Ref"], ["Acme", "Front", "li:9"]]))
    claves, ids = cli.ya_postuladas()
    assert ids == {"li:9"} and len(claves) == 1


@pytest.mark.parametrize("tipo, texto", [("ausente", "No existe"), ("corrupto", "No se puede leer"),
                                          ("sin_hoja", "No se puede leer"), ("sin_columnas", "No se puede leer")])
def test_ya_postuladas_rechaza_un_excel_malo(tmp_path, con_excel, tipo, texto):
    con_excel(excel_malo(tmp_path, tipo))
    with pytest.raises(SystemExit) as error:
        cli.ya_postuladas()
    assert texto in str(error.value) and "Nada filtrado" in str(error.value)


def test_ya_postuladas_sin_candidaturas_sync_no_tiene_nada_que_comprobar(con_excel):
    con_excel(None)
    assert cli.ya_postuladas() == (set(), set())
