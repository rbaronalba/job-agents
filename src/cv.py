"""CV del candidato: CV maestro (cv/cv_base.yaml) + adaptación por oferta (JSON) -> HTML -> PDF verificado.

Adaptación (todo opcional salvo idioma):
  {"idioma": "es"|"en", "titular": str, "resumen": str,
   "skills": [[grupo, "a, b, c"], ...],          # sustituye los grupos de la base
   "bullets": {"<id de experiencia>": [...], ...},  # sustituye viñetas de un puesto (solo hechos de la base)
   "proyectos": ["<id de proyecto>", ...],       # ids y orden; por defecto proyectos_por_defecto
   "palabras_clave": ["Angular", "RxJS", ...]}   # para medir la coincidencia en el PDF
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pypdf import PdfReader, PdfWriter

from .db import RAIZ

BASE = RAIZ / "cv" / "cv_base.yaml"
PROFILE = RAIZ / "config" / "profile.yaml"
GUIONES_PROHIBIDOS = "—–"  # em dash, en dash


def componer(adapt: dict) -> tuple[dict, dict]:
    base = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    idioma = adapt.get("idioma", "es")
    cv = dict(base[idioma])
    perfil = adapt.get("perfil")
    if perfil:
        cv.update(cv["perfiles"][perfil])
    for k in ("titular", "resumen", "skills"):
        if adapt.get(k):
            cv[k] = adapt[k]
    exp = []
    for e in cv["experiencia"]:
        e = dict(e)
        if adapt.get("bullets", {}).get(e["id"]):
            e["bullets"] = adapt["bullets"][e["id"]]
        exp.append(e)
    cv["experiencia"] = exp
    por_id = {p["id"]: p for p in cv["proyectos"]}
    cv["proyectos"] = [por_id[i] for i in adapt.get("proyectos", cv["proyectos_por_defecto"]) if i in por_id]
    return cv, base["contacto"]


def html(adapt: dict) -> str:
    cv, contacto = componer(adapt)
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=True, undefined=StrictUndefined)
    return env.get_template("cv.html").render(cv=cv, c=contacto, s=cv["secciones"], idioma=adapt.get("idioma", "es"))


def _pdf_desde_html(contenido: str, destino: Path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pagina = nav.new_page()
        pagina.set_content(contenido, wait_until="load")
        pagina.pdf(path=str(destino), format="A4", print_background=True, display_header_footer=False,
                   prefer_css_page_size=True)
        nav.close()


def _metadatos(destino: Path, nombre: str, asunto: str):
    w = PdfWriter(clone_from=str(destino))
    w.add_metadata({"/Title": titulo_pdf(), "/Author": nombre, "/Subject": asunto, "/Creator": nombre, "/Producer": nombre})
    with open(destino, "wb") as f:
        w.write(f)


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def titulo_pdf() -> str:
    """"CV_<Nombre><Apellidos>", derivado de candidato.nombre en config/profile.yaml."""
    try:
        nombre = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["candidato"]["nombre"]
    except (FileNotFoundError, KeyError, TypeError):
        nombre = "Candidato"
    return "CV_" + "".join(p.capitalize() for p in _norm(nombre).split())


def nombre_pdf() -> str:
    return titulo_pdf() + ".pdf"


def verificar(pdf: Path, palabras_clave: list[str]) -> dict:
    lector = PdfReader(str(pdf))
    texto = "\n".join(p.extract_text() or "" for p in lector.pages)
    plano = _norm(texto)
    encontradas = [k for k in palabras_clave if re.search(rf"(?<![a-z0-9]){re.escape(_norm(k))}(?:e?s)?(?![a-z0-9])", plano)]  # admite plural
    faltan = [k for k in palabras_clave if k not in encontradas]
    meta = lector.metadata or {}
    return {
        "paginas": len(lector.pages),
        "coincidencia": round(100 * len(encontradas) / len(palabras_clave)) if palabras_clave else None,
        "faltan": faltan,
        "guiones_prohibidos": [c for c in GUIONES_PROHIBIDOS if c in texto],
        "titulo_pdf": meta.get("/Title"),
        "autor_pdf": meta.get("/Author"),
        "texto": texto,
    }


def generar(adapt: dict, carpeta: Path) -> dict:
    """Genera carpeta/<CV del candidato>.pdf y devuelve el informe de verificación."""
    textos = [adapt.get("titular", ""), adapt.get("resumen", ""), str(adapt.get("skills", "")), str(adapt.get("bullets", ""))]
    if any(g in t for t in textos for g in GUIONES_PROHIBIDOS):
        raise ValueError("La adaptación contiene guiones largos o medios; reescríbela sin ellos.")
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / nombre_pdf()
    contenido = html(adapt)
    _pdf_desde_html(contenido, destino)
    cv, contacto = componer(adapt)
    _metadatos(destino, contacto["nombre"], cv["titular"])
    return verificar(destino, adapt.get("palabras_clave", []))


if __name__ == "__main__":
    # Autocomprobación: los dos CV base salen en una página, con metadatos y sin guiones largos
    import tempfile
    contacto = yaml.safe_load(BASE.read_text(encoding="utf-8"))["contacto"]
    for idioma in ("es", "en"):
        inf = generar({"idioma": idioma, "palabras_clave": ["Angular", "TypeScript", "RxJS", "Jest", "Kubernetes"]},
                      Path(tempfile.mkdtemp()))
        assert inf["paginas"] == 1, (idioma, inf["paginas"])
        assert inf["titulo_pdf"] == titulo_pdf() and inf["autor_pdf"] == contacto["nombre"], inf
        assert not inf["guiones_prohibidos"]
        assert inf["coincidencia"] == 80 and inf["faltan"] == ["Kubernetes"], inf["faltan"]
        assert contacto["linkedin"] in inf["texto"]
    print("cv.py OK")
