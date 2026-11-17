"""Candidaturas espontáneas: validación de la clasificación, cola priorizada e informe de resultados.

Solo lógica pura (sin red ni escritura). El CSV de empresas sigue siendo el de siempre: las columnas nuevas son
opcionales y una fila antigua (sin ellas) es válida y cuenta como "sin clasificar". Los resultados (respuesta,
entrevista, rechazo) viven SOLO en candidaturas.xlsx; aquí nunca se guardan ni se duplican.
"""
import re
from collections import defaultdict
from datetime import date

CATEGORIAS = ("A", "B", "C", "D")
COMPATIBILIDAD = ("alta", "media", "baja")
# Distinguir "no hay vacante" (se miró y no hay) de "no sé" (no se pudo comprobar): no son lo mismo.
SENALES = ("vacante_confirmada", "necesidad_potencial", "sin_vacante_publicada", "sin_evidencia")
DESTINATARIOS = ("empleo", "rrhh", "general")
COLUMNAS_NUEVAS = ("categoria", "compatibilidad", "senal", "destinatario", "tecnologias")
ENVIADOS = ("enviada", "borrador")
UMBRAL_MUY_PEQUENA, UMBRAL_DESCRIPTIVA = 10, 20


def validar_fila(f: dict) -> list[str]:
    """Errores de coherencia de una fila del CSV (lista vacía = válida). Una fila sin categoría no se valida."""
    v = lambda c: (f.get(c) or "").strip()
    cat, comp, senal, dest = v("categoria"), v("compatibilidad"), v("senal"), v("destinatario")
    e = []
    for valor, validos, nombre in ((cat, CATEGORIAS, "categoria"), (comp, COMPATIBILIDAD, "compatibilidad"),
                                   (senal, SENALES, "senal"), (dest, DESTINATARIOS, "destinatario")):
        if valor and valor not in validos:
            e.append(f"{nombre} '{valor}' no válida")
    if not cat:
        return e
    if not senal:
        e.append("falta senal")
    if cat in "ABC" and not (comp and dest):
        e.append("A/B/C exigen compatibilidad y destinatario")
    if cat == "A" and senal != "vacante_confirmada":
        e.append("categoría A exige senal vacante_confirmada (una hipótesis nunca pasa de C)")
    if v("estado") in ENVIADOS and (cat == "D" or comp == "baja"):
        e.append("enviada/borrador con categoría D o compatibilidad baja")
    return e


def _anillo(ciudad: str, anillos: list[list[str]], norm) -> int | None:
    c = norm(ciudad)
    for i, ciudades in enumerate(anillos):
        if any(norm(x) in c for x in ciudades if norm(x)):
            return i
    return None


def cola(filas: list[dict], anillos: list[list[str]], actual: int, norm) -> list[dict]:
    """Empresas por procesar, en orden: A, B, C, sin clasificar; dentro de cada una, el anillo más cercano primero.
    Excluye D, compatibilidad baja y anillos posteriores al actual. No rellena: devuelve solo lo que cumple."""
    salida = []
    for f in filas:
        if (f.get("estado") or "").strip() not in ("", "pendiente"):
            continue
        cat, comp = (f.get("categoria") or "").strip(), (f.get("compatibilidad") or "").strip()
        if cat == "D" or comp == "baja":
            continue
        anillo = _anillo(f.get("ciudad") or "", anillos, norm)
        if anillo is not None and anillo > actual:
            continue
        salida.append((("ABC".find(cat) if cat in ("A", "B", "C") else 3, 99 if anillo is None else anillo,
                        f.get("empresa") or ""), f))
    return [f for _, f in sorted(salida, key=lambda x: x[0])]


def nivel_muestra(n: int) -> str:
    return "muestra muy pequeña" if n < UMBRAL_MUY_PEQUENA else "exploratorio" if n < UMBRAL_DESCRIPTIVA else "descriptivo"


def _grupo() -> dict:
    return {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0, "sin_respuesta": 0}


def _dimensiones(f: dict) -> dict[str, list[str]]:
    sector = re.split(r"[,(/]", (f.get("sector") or "").lower())[0].strip() or "?"
    techs = [t.strip().lower() for t in re.split(r"[;,]", f.get("tecnologias") or "") if t.strip()] or ["?"]
    semana = "?"
    try:
        y, w, _ = date.fromisoformat((f.get("fecha") or "")[:10]).isocalendar()
        semana = f"{y}-S{w:02d}"
    except ValueError:
        pass
    return {"semana": [semana], "categoria": [(f.get("categoria") or "").strip() or "sin_clasificar"],
            "compatibilidad": [(f.get("compatibilidad") or "").strip() or "sin_clasificar"],
            "senal": [(f.get("senal") or "").strip() or "sin_clasificar"],
            "destinatario": [(f.get("destinatario") or "").strip() or "sin_clasificar"],
            "sector": [sector], "tecnologia": techs}


def informe(filas: list[dict], resultados: dict[str, str | None] | None) -> dict:
    """Envíos del CSV (estado enviada) cruzados con el resultado que dice el Excel.
    `resultados`: empresa -> respuesta|entrevista|rechazo|None (None = fila sin resultado). None en vez de dict =
    Excel no disponible: no se calcula ninguna tasa (no es "cero respuestas")."""
    envios = [f for f in filas if (f.get("estado") or "").strip() == "enviada"]
    grupos = defaultdict(lambda: defaultdict(_grupo))
    total, sin_fila = _grupo(), 0
    for f in envios:
        nombre = f.get("empresa") or ""
        if resultados is None:
            r = "?"
        elif nombre not in resultados:
            sin_fila += 1
            r = "sin_respuesta"
        else:
            r = resultados[nombre] or "sin_respuesta"
        celdas = [total] + [grupos[d][v] for d, vs in _dimensiones(f).items() for v in vs]
        for g in celdas:
            g["enviadas"] += 1
            if r != "?":
                g[r] += 1
    return {"seguimiento_disponible": resultados is not None, "sin_fila_en_excel": sin_fila,
            "total": total, **{d: dict(v) for d, v in grupos.items()}}


def _fila(nombre: str, g: dict, seguimiento: bool) -> str:
    n = g["enviadas"]
    pct = lambda x: f"{x} ({100 * x / n:.0f}%)" if n else "0"
    if not seguimiento:
        return f"{nombre:28} {n:4} enviadas  seguimiento no disponible"
    resp = g["respuesta"] + g["entrevista"] + g["rechazo"]
    return (f"{nombre:28} {n:4} enviadas  respondidas {pct(resp)}  entrevistas {pct(g['entrevista'])}  "
            f"rechazos {pct(g['rechazo'])}  sin respuesta {pct(g['sin_respuesta'])}  [{nivel_muestra(n)}]")


def texto(inf: dict) -> str:
    seg = inf["seguimiento_disponible"]
    out = [_fila("TOTAL", inf["total"], seg),
           "Sin respuesta no es rechazo. Respondidas = respuesta + entrevista + rechazo (según candidaturas.xlsx)."]
    if not seg:
        out.append("AVISO: no hay candidaturas.xlsx legible; no se calculan tasas.")
    if inf["sin_fila_en_excel"]:
        out.append(f"AVISO: {inf['sin_fila_en_excel']} envíos sin fila en el Excel (cuentan como sin respuesta).")
    for dim in ("semana", "categoria", "compatibilidad", "senal", "destinatario", "sector", "tecnologia"):
        if dim in inf:
            out.append(f"\n-- por {dim} --")
            filas = sorted(inf[dim].items(), key=lambda x: (-x[1]["enviadas"], x[0]))
            tope = 10 if dim in ("sector", "tecnologia") else len(filas)   # texto libre: se corta la cola larga
            out += [_fila(k, g, seg) for k, g in filas[:tope]]
            if len(filas) > tope:
                out.append(f"(+{len(filas) - tope} más, en --json)")
    return "\n".join(out)
