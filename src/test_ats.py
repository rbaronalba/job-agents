"""Comprobaciones sin red de src.ats: filtro, formato de salida y detección de slugs.  python -m src.test_ats"""
import re

from src import ats


def test_relevante():
    assert ats.relevante("Junior Frontend Engineer", "Madrid, Spain")
    assert not ats.relevante("Senior Angular Developer", "Remote - Europe")  # filtro de calidad: Senior fuera
    assert ats.relevante("JavaScript Developer", "Madrid") and ats.relevante("Full Stack Java Developer", "Madrid")
    assert ats.relevante("Junior Data Scientist - Agentic AI", "Barcelona")
    assert not ats.relevante("Engineering Manager", "Madrid")                # gestión
    assert not ats.relevante("Frontend Intern", "Madrid")                    # prácticas
    assert not ats.relevante("Frontend Engineer", "Berlin, Germany")         # fuera de España y no remoto
    assert not ats.relevante("Account Executive", "Madrid")                  # no es del perfil


def test_oferta():
    o = ats.oferta("Wallapop", "greenhouse", " Frontend Engineer ", "Barcelona", "https://x/1", 123, "2026-11-10", "texto")
    assert o["titulo"] == "Frontend Engineer"
    assert o["ids_externos"] == ["greenhouse:123"] and o["portales"] == ["ats:greenhouse"]
    assert set(o) >= {"empresa", "titulo", "urls", "ids_externos"}   # lo que necesitan filtrar y guardar


def test_patrones():
    casos = {
        '<a href="https://boards.greenhouse.io/wallapop/jobs/1">': ("greenhouse", "wallapop"),
        '<a href="https://jobs.lever.co/codeway/abc">': ("lever", "codeway"),
        '<a href="https://ailylabs.jobs.personio.com/job/1">': ("personio", "ailylabs"),
        '<a href="https://jobs.ashbyhq.com/acme">': ("ashby", "acme"),
    }
    for pagina, esperado in casos.items():
        hallado = next((a, m) for a, pat in ats.PATRONES for m in re.findall(pat, pagina) if m not in ats.NO_SLUG)
        assert hallado == esperado, (pagina, hallado)


def test_fecha():
    assert ats._fecha(1763164800000) == "2025-11-15"
    assert ats._fecha("2026-11-10T08:00:00Z") == "2026-11-10"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
