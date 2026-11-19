"""src.ats sin red: filtro, formato de salida, conectores de los 6 ATS, detección y plan B.  python -m pytest src/test_ats.py"""
import json

import pytest

from src import ats
from src.testing.entorno import Red


# --- filtro de ofertas -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("titulo, ubicacion, esperado", [
    ("Junior Frontend Engineer", "Madrid, Spain", True),
    ("JavaScript Developer", "Madrid", True),
    ("Full Stack Java Developer", "Madrid", True),                 # Java/.NET ya no excluyen
    ("Junior Data Scientist - Agentic AI", "Barcelona", True),
    ("FRONTEND DEVELOPER", "MADRID", True),                        # mayúsculas
    ("Angular Developer", "Remote - Europe", True),
    ("Frontend Developer", "Anywhere", True),
    ("Senior Angular Developer", "Remote - Europe", False),        # calidad: Senior fuera
    ("Sr. Frontend Developer", "Madrid", False),
    ("Lead React Developer", "Madrid", False),
    ("Engineering Manager", "Madrid", False),                      # gestión
    ("Head of Data", "Madrid", False),
    ("Frontend Intern", "Madrid", False),                          # prácticas
    ("Prácticas Desarrollador Web", "Madrid", False),
    ("Frontend Engineer", "Berlin, Germany", False),               # fuera de España y no remoto
    ("Account Executive", "Madrid", False),                        # no es del perfil
    ("", "Madrid", False),                                         # vacíos
    ("Frontend Developer", "", False),
    ("Frontend Developer", None, False),
])
def test_relevante(titulo, ubicacion, esperado):
    assert ats.relevante(titulo, ubicacion) is esperado


# --- formato de salida -----------------------------------------------------------------------------------------------
def test_oferta_contrato_de_salida():
    o = ats.oferta("Wallapop", "greenhouse", " Frontend Engineer ", "Barcelona", "https://x/1", 123, "2026-11-10", "texto")
    assert o["titulo"] == "Frontend Engineer"
    assert o["urls"] == ["https://x/1"] and o["fecha_pub"] == "2026-11-10" and o["ubicacion"] == "Barcelona"
    assert o["ids_externos"] == ["greenhouse:123"] and o["portales"] == ["ats:greenhouse"]
    assert set(o) >= {"empresa", "titulo", "urls", "ids_externos", "portales", "tipo_candidatura", "texto"}


def test_oferta_recorta_el_texto():
    assert len(ats.oferta("E", "lever", "T", "L", "u", 1, None, "x" * 10_000)["texto"]) == 6000


# --- fechas ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("valor, esperado", [
    (1763164800000, "2025-11-15"),            # Lever: milisegundos
    ("2026-11-10T08:00:00Z", "2026-11-10"),
    ("2026-11-10", "2026-11-10"),
    (None, None), ("", None), (0, None),
    ("basura", None), ("2026-13-45", None),   # no es una fecha
    (1e30, None), (-1e30, None),              # fuera de rango: no debe lanzar
])
def test_fecha(valor, esperado):
    assert ats._fecha(valor) == esperado


# --- slugs -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("slug, valido", [
    ("MiEmpresa", True), ("a-b_c", True), ("x" * 64, True),
    ("a.evil.com", False), ("a/b", False), ("a@b", False), ("a#", False), ("", False), ("x" * 65, False),
])
def test_slug(slug, valido):
    assert bool(ats.SLUG.fullmatch(slug)) is valido


# --- conectores: los 6 ATS -------------------------------------------------------------------------------------------
PAYLOADS = {
    "greenhouse": ("boards-api.greenhouse.io", json.dumps({"jobs": [
        {"title": "Dev", "location": {"name": "Madrid"}, "absolute_url": "https://g/1", "id": 7,
         "updated_at": "2026-11-10T08:00:00Z", "content": "&lt;p&gt;Hola&lt;/p&gt;"}]}), "7"),
    "lever": ("api.lever.co", json.dumps([
        {"text": "Dev", "categories": {"location": "Madrid", "allLocations": ["Madrid"]}, "workplaceType": "remote",
         "hostedUrl": "https://l/1", "id": "abc", "createdAt": 1763164800000, "descriptionPlain": "Hola"}]), "abc"),
    "ashby": ("api.ashbyhq.com", json.dumps({"jobs": [
        {"title": "Dev", "location": "Madrid", "isRemote": True, "secondaryLocations": [], "jobUrl": "https://a/1",
         "id": "u1", "publishedAt": "2026-11-10", "descriptionPlain": "Hola"}]}), "u1"),
    "personio": ("jobs.personio.com/xml", "<workzag-jobs><position><id>5</id><name>Dev</name><office>Madrid</office>"
                 "<createdAt>2026-11-10T08:00:00+00:00</createdAt><jobDescriptions><jobDescription><value>Hola</value>"
                 "</jobDescription></jobDescriptions></position></workzag-jobs>", "5"),
    "recruitee": ("recruitee.com/api/offers", json.dumps({"offers": [
        {"title": "Dev", "location": "Madrid", "country": "Spain", "remote": False, "careers_url": "https://r/1",
         "id": 9, "published_at": "2026-11-10", "description": "<b>Hola</b>"}]}), "9"),
    "workable": ("apply.workable.com/api", json.dumps({"jobs": [
        {"title": "Dev", "city": "Madrid", "country": "Spain", "telecommuting": False, "url": "https://w/1",
         "shortcode": "SC1", "published_on": "2026-11-10"}]}), "SC1"),
}


def test_hay_un_caso_por_cada_conector():
    assert set(PAYLOADS) == set(ats.CONECTORES)          # un conector nuevo obliga a añadir su caso


@pytest.mark.parametrize("nombre", ["greenhouse", "lever", "ashby", "personio", "recruitee", "workable"])
def test_conector(monkeypatch, nombre):
    trozo, cuerpo, jid = PAYLOADS[nombre]
    Red(monkeypatch, {trozo: cuerpo})
    filas = list(ats.CONECTORES[nombre]("acme"))
    assert len(filas) == 1
    titulo, ubicacion, url, ident, fecha, texto = filas[0]
    assert titulo == "Dev" and "Madrid" in ubicacion and str(ident) == jid and url.startswith("https://")
    assert fecha in (None, "2025-11-15", "2026-11-10")


def test_conector_rechaza_xml_con_dtd(monkeypatch):
    Red(monkeypatch, {"personio": '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'})
    with pytest.raises(ValueError, match="DTD"):
        list(ats.personio("acme"))


def test_conector_fecha_rota_no_tumba_el_tablero(monkeypatch):
    cuerpo = json.dumps({"jobs": [{"title": "Dev", "location": {"name": "Madrid"}, "absolute_url": "u", "id": 1,
                                   "updated_at": "basura", "content": ""}]})
    Red(monkeypatch, {"greenhouse": cuerpo})
    assert list(ats.greenhouse("acme"))[0][4] is None


# --- detección del ATS de una web ------------------------------------------------------------------------------------
@pytest.mark.parametrize("pagina, esperado", [
    ('<a href="https://boards.greenhouse.io/wallapop/jobs/1">', ("greenhouse", "wallapop")),
    ('<a href="https://job-boards.greenhouse.io/wallapop">', ("greenhouse", "wallapop")),
    ('<a href="https://job-boards.eu.greenhouse.io/wallapop?gh_jid=1">', ("greenhouse", "wallapop")),
    ('src="https://boards.greenhouse.io/embed/job_board?for=acme-co"', ("greenhouse", "acme-co")),
    ('<a href="https://jobs.lever.co/codeway/abc?lever-source=web">', ("lever", "codeway")),
    ('<a href="https://jobs.eu.lever.co/codeway">', ("lever", "codeway")),
    ('<a href="https://jobs.ashbyhq.com/acme">', ("ashby", "acme")),
    ('<a href="https://jobs.ashbyhq.com/MiEmpresa">', ("ashby", "MiEmpresa")),                    # el slug conserva mayúsculas
    ('<a href="https://ailylabs.jobs.personio.com/job/1">', ("personio", "ailylabs")),
    ('<a href="https://ailylabs.jobs.personio.de/">', ("personio", "ailylabs")),
    ('<a href="https://acme.recruitee.com/o/dev">', ("recruitee", "acme")),
    ('<a href="https://apply.workable.com/acme/j/ABC123/">', ("workable", "acme")),
    ('<A HREF="HTTPS://JOBS.LEVER.CO/Codeway">', ("lever", "Codeway")),                           # mayúsculas en todo
])
def test_detectar_cada_ats(monkeypatch, pagina, esperado):
    Red(monkeypatch, {"https://acme.es": pagina})
    assert ats.detectar("https://acme.es") == esperado


@pytest.mark.parametrize("pagina", [
    "<html>sin enlaces de empleo</html>",
    '<a href="https://example.com/jobs/1">',
    '<a href="https://boards.greenhouse.io/embed/">',              # 'embed' no es un slug
    '<a href="https://jobs.lever.co/a.b.c">',                      # un punto en el slug lo haría salir del host
    '<a href="https://boards.greenhouse.io/api/v1/">',             # 'api' tampoco
])
def test_detectar_ignora_lo_que_no_es_un_tablero(monkeypatch, pagina):
    Red(monkeypatch, {"https://acme.es": pagina})   # adivinar() probará los conectores y fallará (404)
    assert ats.detectar("https://acme.es") is None


def test_detectar_prueba_las_rutas_hasta_acertar(monkeypatch):
    red = Red(monkeypatch, {"acme.es/careers": '<a href="https://jobs.lever.co/acme">'})   # "" y otras rutas dan 404
    assert ats.detectar("https://acme.es") == ("lever", "acme")
    assert red.pedidas[:2] == ["https://acme.es", "https://acme.es/careers"]


@pytest.mark.parametrize("entrada", ["http://acme.es", "acme.es", "https://acme.es", "http://acme.es/"])
def test_detectar_solo_usa_https(monkeypatch, entrada):
    red = Red(monkeypatch)
    ats.detectar(entrada)
    assert red.pedidas[0] == "https://acme.es"       # la primera petición ya es https y sin barra final


def test_detectar_toma_el_primer_ats_y_no_sigue(monkeypatch):
    red = Red(monkeypatch, {"https://acme.es": '<a href="https://jobs.lever.co/uno"> <a href="https://jobs.ashbyhq.com/dos">'})
    assert ats.detectar("https://acme.es") == ("lever", "uno")
    assert len(red.pedidas) == 1


# --- plan B: adivinar el tablero por el nombre del dominio -----------------------------------------------------------
def test_adivinar_acepta_un_tablero_con_ofertas(monkeypatch):
    Red(monkeypatch, {"api.lever.co/v0/postings/acme": PAYLOADS["lever"][1]})
    assert ats.adivinar("https://www.acme.es") == ("lever", "acme")


def test_adivinar_rechaza_un_tablero_vacio(monkeypatch):
    Red(monkeypatch, {"boards-api.greenhouse.io": json.dumps({"jobs": []})})   # existe pero sin ofertas: otra empresa homónima
    assert ats.adivinar("https://acme.es") is None


def test_adivinar_prueba_variantes_del_nombre(monkeypatch):
    vistos = []

    def conector_falso(slug):
        vistos.append(slug)
        raise OSError("404")

    monkeypatch.setattr(ats, "CONECTORES", {"falso": conector_falso})
    assert ats.adivinar("https://www.mi-empresahr.com") is None
    assert vistos == ["mi-empresahr", "miempresahr", "mi-empresa"]   # nombre, sin guiones y sin el sufijo hr


# --- buscar: un tablero roto no para a los demás ---------------------------------------------------------------------
def test_buscar_sigue_tras_un_tablero_caido(monkeypatch, tmp_path, capsys):
    ruta = tmp_path / "ats.csv"
    ruta.write_text("empresa,ats,slug,fuente\nRota,lever,rota,x\nMala,lever,mal.slug,x\nBuena,greenhouse,buena,x\n", encoding="utf-8")
    monkeypatch.setattr(ats, "CATALOGO", ruta)
    buena = json.dumps({"jobs": [{"title": "Frontend Developer", "location": {"name": "Madrid"}, "absolute_url": "https://g/1",
                                  "id": 7, "updated_at": "2026-11-10", "content": ""}]})
    Red(monkeypatch, {"boards-api.greenhouse.io/v1/boards/buena": buena})
    salida = tmp_path / "c.json"
    ats.cmd_buscar(type("A", (), {"salida": str(salida)}))
    ofertas = json.loads(salida.read_text(encoding="utf-8"))
    assert len(ofertas) == 1
    assert ofertas[0]["empresa"] == "Buena" and ofertas[0]["ids_externos"] == ["greenhouse:7"]
    resumen = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert len(resumen["errores"]) == 2 and "slug no válido" in " ".join(resumen["errores"])
