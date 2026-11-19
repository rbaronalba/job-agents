"""Ofertas directas de los ATS de las empresas (Greenhouse, Lever, Ashby, Personio, Recruitee, Workable).

Endpoints públicos de publicación de ofertas: sin cuenta, sin coste, solo lectura.
Catálogo: data/ats.csv (empresa,ats,slug,fuente). Salida en el formato de `src.cli filtrar`.

  python -m src.ats buscar [--salida data/tmp/candidatas_ats.json]
  python -m src.ats detectar            # busca el ATS de las webs de data/empresas.csv y lo añade al catálogo
  python -m src.ats detectar URL...     # o de URLs concretas
"""
import argparse
import csv
import html
import json
import re
import sys
import ipaddress
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CATALOGO = RAIZ / "data" / "ats.csv"
EMPRESAS = RAIZ / "data" / "empresas.csv"
UA = {"User-Agent": "Mozilla/5.0 (job-search personal script)"}

# Ubicaciones válidas (perfil: España o remoto) y títulos del perfil. El encaje fino lo hace el buscador.
UBICACION = re.compile(r"spain|españa|espana|madrid|barcelona|m[aá]laga|sevilla|seville|valencia|c[oó]rdoba|bilbao|"
                       r"granada|zaragoza|alicante|remote|remoto|anywhere|europe|emea|\beu\b", re.I)
TITULO = re.compile(r"front|angular|react|vue|javascript|typescript|full.?stack|software|developer|desarrollad|"
                    r"programador|web|\bai\b|\bia\b|machine learning|\bml\b|llm|data|datos|analytics", re.I)
# Gestión, prácticas y Senior fuera (Java/.NET ya no, 2026-11-17; ver src.db.motivo_filtro).
EXCLUIR = re.compile(r"\bsenior\b|\bsr\b|\blead\b|principal|staff|head of|manager|director|architect|arquitect|vp\b|"
                     r"intern\b|internship|becari|pr[aá]cticas|trainee|sales|account exec|recruit", re.I)


MAX_BYTES = 5_000_000
SLUG = re.compile(r"[A-Za-z0-9_-]{1,64}")   # va dentro de hosts y rutas: nada de puntos, barras ni @


def _publico(host: str) -> None:
    """Solo https hacia hosts públicos (SSRF). ponytail: no cubre DNS rebinding; para eso, fijar la IP resuelta."""
    for *_, (ip, *_) in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(ip).is_global:
            raise ValueError(f"{host} resuelve a una IP no pública")


class _Redir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlparse(newurl)
        if u.scheme != "https":
            raise urllib.error.URLError(f"redirección no https: {newurl}")
        _publico(u.hostname or "")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _leer(url: str, timeout: int, limite: int = MAX_BYTES) -> bytes:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError(f"solo https: {url}")
    _publico(u.hostname)
    with urllib.request.build_opener(_Redir).open(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        datos = r.read(limite + 1)
    if len(datos) > limite:
        raise ValueError(f"respuesta de más de {limite} bytes: {url}")
    return datos


def _get(url: str, xml: bool = False):
    datos = _leer(url, 20)
    if not xml:
        return json.loads(datos)
    if b"<!DOCTYPE" in datos.upper() or b"<!ENTITY" in datos.upper():   # billion laughs / XXE: sus feeds no llevan DTD
        raise ValueError("XML con DTD rechazado")
    return ET.fromstring(datos)


def _texto(h: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(h or ""))).strip()


def _fecha(v) -> str | None:
    """Fecha ISO (AAAA-MM-DD) de un timestamp en ms (Lever) o de un texto ISO; None si falta o no es una fecha válida."""
    if not v:
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc).date().isoformat()
        return datetime.fromisoformat(str(v)[:10]).date().isoformat()
    except (ValueError, OverflowError, OSError):   # basura del ATS: una fecha rota no debe tirar el tablero entero
        return None


def greenhouse(slug):
    for j in _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")["jobs"]:
        yield j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"], j["id"], _fecha(j.get("updated_at")), _texto(j.get("content"))


def lever(slug):
    for j in _get(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        cat = j.get("categories") or {}
        loc = " / ".join(filter(None, [cat.get("location"), *(cat.get("allLocations") or []), j.get("workplaceType")]))
        yield j["text"], loc, j["hostedUrl"], j["id"], _fecha(j.get("createdAt")), j.get("descriptionPlain") or ""


def ashby(slug):
    for j in _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"]:
        locs = [j.get("location") or "", *[s.get("location", "") for s in j.get("secondaryLocations") or []]]
        if j.get("isRemote"):
            locs.append("Remote")
        yield j["title"], " / ".join(filter(None, locs)), j["jobUrl"], j["id"], _fecha(j.get("publishedAt")), j.get("descriptionPlain") or ""


def personio(slug):
    raiz = _get(f"https://{slug}.jobs.personio.com/xml", xml=True)
    for p in raiz.iter("position"):
        g = lambda t: (p.findtext(t) or "").strip()
        offices = [g("office"), *[o.text or "" for o in p.iter("additionalOffice")]]
        desc = " ".join(_texto(d.findtext("value")) for d in p.iter("jobDescription"))
        yield g("name"), " / ".join(filter(None, offices)), f"https://{slug}.jobs.personio.com/job/{g('id')}", g("id"), _fecha(g("createdAt")), desc


def recruitee(slug):
    for j in _get(f"https://{slug}.recruitee.com/api/offers/")["offers"]:
        loc = " / ".join(filter(None, [j.get("location"), j.get("country"), "Remote" if j.get("remote") else ""]))
        yield j["title"], loc, j["careers_url"], j["id"], _fecha(j.get("published_at")), _texto(j.get("description"))


def workable(slug):
    for j in _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")["jobs"]:
        loc = " / ".join(filter(None, [j.get("city"), j.get("country"), "Remote" if j.get("telecommuting") else ""]))
        yield j["title"], loc, j.get("url") or f"https://apply.workable.com/{slug}/j/{j['shortcode']}/", j["shortcode"], _fecha(j.get("published_on")), ""


CONECTORES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "personio": personio,
              "recruitee": recruitee, "workable": workable}

# Enlaces que delatan el ATS en una página de empleo: (ats, regex con el slug en el grupo 1)
PATRONES = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_.%-]+)"),
    ("personio", r"([a-z0-9-]+)\.jobs\.personio\.(?:com|de)"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("workable", r"apply\.workable\.com/([a-z0-9_-]+)"),
]
NO_SLUG = {"embed", "api", "v1", "j", "jobs", "www", "careers", "static", "assets", "widget", "careers-analytics"}


def oferta(empresa, ats, titulo, ubicacion, url, jid, fecha, texto) -> dict:
    return {"empresa": empresa, "titulo": titulo.strip(), "ubicacion": ubicacion, "fecha_pub": fecha,
            "urls": [url], "ids_externos": [f"{ats}:{jid}"], "portales": [f"ats:{ats}"],
            "tipo_candidatura": "formulario_externo", "texto": texto[:6000]}


def relevante(titulo: str, ubicacion: str) -> bool:
    return bool(TITULO.search(titulo)) and not EXCLUIR.search(titulo) and bool(UBICACION.search(ubicacion or ""))


def catalogo() -> list[dict]:
    if not CATALOGO.exists():
        return []
    return list(csv.DictReader(CATALOGO.open(encoding="utf-8")))


def cmd_buscar(args):
    res, errores, total = [], [], 0
    for c in catalogo():
        fn = CONECTORES.get(c["ats"])
        if not fn:
            continue
        try:
            if not SLUG.fullmatch(c["slug"]):
                raise ValueError("slug no válido")
            filas = list(fn(c["slug"]))
        except Exception as e:   # noqa: BLE001 - un tablero caído o movido no para los demás
            errores.append(f"{c['empresa']} ({c['ats']}:{c['slug']}): {type(e).__name__} {e}"[:160])
            continue
        total += len(filas)
        res += [oferta(c["empresa"], c["ats"], *f) for f in filas if relevante(f[0], f[1])]
        time.sleep(0.3)   # cortesía con los servidores
    salida = json.dumps(res, ensure_ascii=False, indent=1)
    if args.salida:
        Path(args.salida).write_text(salida, encoding="utf-8")
    else:
        print(salida)
    print(json.dumps({"tableros": len(catalogo()), "ofertas_leidas": total, "relevantes": len(res), "errores": errores},
                     ensure_ascii=False), file=sys.stderr)


def detectar(url: str) -> tuple[str, str] | None:
    base = re.sub(r"^http://", "https://", url.rstrip("/"))
    if not base.startswith("https://"):
        base = "https://" + base
    for ruta in ("", "/careers", "/jobs", "/empleo", "/trabaja-con-nosotros", "/join-us", "/en/careers"):
        try:
            pagina = _leer(base + ruta, 12, 800_000).decode("utf-8", "ignore")
        except Exception:   # noqa: BLE001 - 404, timeout o SSL: probar la siguiente ruta
            continue
        for ats, pat in PATRONES:
            for slug in re.findall(pat, pagina, re.I):   # sin lower(): hay ATS con slug sensible a mayúsculas
                if slug.lower() not in NO_SLUG and SLUG.fullmatch(slug):
                    return ats, slug
    return adivinar(base)


def adivinar(url: str) -> tuple[str, str] | None:
    """Plan B para webs que cargan el enlace de empleo con JavaScript: probar el nombre del dominio como slug.
    ponytail: solo da por bueno un tablero con ofertas, para no apuntar a uno vacío de otra empresa homónima."""
    nombre = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].split(".")[0]
    for slug in dict.fromkeys([nombre, nombre.replace("-", ""), nombre.removesuffix("hr").removesuffix("app")]):
        for ats, fn in CONECTORES.items():
            time.sleep(0.3)   # cortesía: hasta 18 peticiones por empresa
            try:
                if next(iter(fn(slug)), None):
                    return ats, slug
            except Exception:   # noqa: BLE001 - 404 = no es ese ATS
                continue
    return None


def cmd_detectar(args):
    ya = {(c["ats"], c["slug"]) for c in catalogo()}
    if args.urls:
        objetivos = [(re.sub(r"^https?://(www\.)?", "", u).split(".")[0].capitalize(), u) for u in args.urls]
    else:
        filas = csv.DictReader(EMPRESAS.open(encoding="utf-8"))
        objetivos = [(f["empresa"], f["web"]) for f in filas if f.get("web")]
    nuevos = []
    for empresa, web in objetivos:
        r = detectar(web)
        if r and r not in ya:
            ya.add(r)
            nuevos.append({"empresa": empresa, "ats": r[0], "slug": r[1], "fuente": web})
    nuevo_archivo = not CATALOGO.exists()
    if not nuevo_archivo and not CATALOGO.read_bytes().endswith(b"\n"):   # editado a mano sin salto final
        with CATALOGO.open("ab") as f:
            f.write(b"\n")
    with CATALOGO.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["empresa", "ats", "slug", "fuente"])
        if nuevo_archivo:
            w.writeheader()
        w.writerows(nuevos)
    print(json.dumps({"revisadas": len(objetivos), "nuevos": nuevos}, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("buscar"); s.add_argument("--salida"); s.set_defaults(fn=cmd_buscar)
    s = sub.add_parser("detectar"); s.add_argument("urls", nargs="*"); s.set_defaults(fn=cmd_detectar)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
