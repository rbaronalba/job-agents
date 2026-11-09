"""Histórico de ofertas en SQLite: deduplicación entre portales y estado de cada oferta."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA = RAIZ / "data" / "historico.sqlite"

ESTADOS = ["nueva", "cv_adaptado", "pendiente_revision", "enviada", "descartada"]

# Columnas que el buscador rellena (todas texto salvo encaje)
CAMPOS = ["empresa", "titulo", "ubicacion", "modalidad", "salario", "fecha_pub", "texto", "requisitos",
          "idioma", "tipo_candidatura", "encaje", "justificacion", "eliminatorios", "categoria",
          "carencias", "coincidencia_kw", "notas"]

ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS ofertas (
  id TEXT PRIMARY KEY,
  clave TEXT UNIQUE NOT NULL,
  portales TEXT NOT NULL DEFAULT '[]',
  urls TEXT NOT NULL DEFAULT '[]',
  ids_externos TEXT NOT NULL DEFAULT '[]',
  {", ".join(f"{c} {'INTEGER' if c == 'encaje' else 'TEXT'}" for c in CAMPOS)},
  estado TEXT NOT NULL DEFAULT 'nueva',
  semana TEXT NOT NULL,
  creada TEXT NOT NULL,
  actualizada TEXT NOT NULL,
  enviada TEXT
);
"""

# Se aplica sobre texto ya normalizado ("S.L." queda como "s l")
_SUFIJOS = r"\b(s l( u)?|s a( u)?|slu?|sau?|sociedad limitada|spain|espana|iberia|group|grupo|consulting|technologies|tech)\b"


def norm(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)          # (m/f/d), (híbrido)...
    t = re.sub(r"\b(h/m|m/f(/d)?|m/h|f/m/d)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def clave(empresa: str | None, titulo: str | None) -> str:
    # ponytail: empresa+título normalizados; si un portal reescribe el título no se une, revisar en Excel
    emp = " ".join(re.sub(_SUFIJOS, " ", norm(empresa)).split())
    return f"{emp}|{norm(titulo)}"


def semana(d: date | None = None) -> str:
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def conectar(ruta: Path = RUTA) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def _unir(lista_json: str, nuevos) -> str:
    lista = json.loads(lista_json or "[]")
    for n in nuevos or []:
        if n and n not in lista:
            lista.append(n)
    return json.dumps(lista, ensure_ascii=False)


def buscar(con, oferta: dict) -> sqlite3.Row | None:
    """Encuentra la oferta por clave o por cualquier id externo (p. ej. li:4478101920)."""
    fila = con.execute("SELECT * FROM ofertas WHERE clave = ?", (clave(oferta.get("empresa"), oferta.get("titulo")),)).fetchone()
    if fila:
        return fila
    for ext in oferta.get("ids_externos") or []:
        fila = con.execute("SELECT * FROM ofertas WHERE ids_externos LIKE ?", (f'%"{ext}"%',)).fetchone()
        if fila:
            return fila
    return None


def guardar(con, oferta: dict) -> tuple[str, bool]:
    """Inserta o fusiona una oferta. Devuelve (id, es_nueva). No pisa estado ni campos ya rellenos con vacíos."""
    ahora = datetime.now().isoformat(timespec="seconds")
    previa = buscar(con, oferta)
    if previa:
        cambios = {c: oferta[c] for c in CAMPOS if oferta.get(c) not in (None, "", [])}
        for c in ("requisitos",):
            if isinstance(cambios.get(c), (list, dict)):
                cambios[c] = json.dumps(cambios[c], ensure_ascii=False)
        cambios["portales"] = _unir(previa["portales"], oferta.get("portales"))
        cambios["urls"] = _unir(previa["urls"], oferta.get("urls"))
        cambios["ids_externos"] = _unir(previa["ids_externos"], oferta.get("ids_externos"))
        cambios["actualizada"] = ahora
        con.execute(f"UPDATE ofertas SET {', '.join(f'{k} = ?' for k in cambios)} WHERE id = ?",
                    [*cambios.values(), previa["id"]])
        return previa["id"], False

    sem = semana()
    # MAX y no COUNT: la semana puede tener huecos si se borraron filas
    n = con.execute("SELECT COALESCE(MAX(CAST(substr(id, -3) AS INTEGER)), 0) FROM ofertas WHERE semana = ?", (sem,)).fetchone()[0] + 1
    oid = f"{sem}-{n:03d}"
    valores = {c: oferta.get(c) for c in CAMPOS}
    if isinstance(valores["requisitos"], (list, dict)):
        valores["requisitos"] = json.dumps(valores["requisitos"], ensure_ascii=False)
    con.execute(
        f"INSERT INTO ofertas (id, clave, portales, urls, ids_externos, {', '.join(CAMPOS)}, estado, semana, creada, actualizada) "
        f"VALUES ({', '.join('?' * (len(CAMPOS) + 9))})",
        [oid, clave(oferta.get("empresa"), oferta.get("titulo")),
         _unir("[]", oferta.get("portales")), _unir("[]", oferta.get("urls")), _unir("[]", oferta.get("ids_externos")),
         *valores.values(), oferta.get("estado") or "nueva", sem, ahora, ahora])
    return oid, True


def cambiar_estado(con, oid: str, estado: str, nota: str | None = None):
    if estado not in ESTADOS:
        raise ValueError(f"Estado no válido: {estado}. Usa uno de {ESTADOS}")
    fila = con.execute("SELECT notas FROM ofertas WHERE id = ?", (oid,)).fetchone()
    if not fila:
        raise ValueError(f"No existe la oferta {oid}")
    notas = "; ".join(x for x in [fila["notas"], nota] if x)
    con.execute("UPDATE ofertas SET estado = ?, notas = ?, actualizada = ?, enviada = CASE WHEN ? = 'enviada' THEN ? ELSE enviada END WHERE id = ?",
                (estado, notas, datetime.now().isoformat(timespec="seconds"), estado, date.today().isoformat(), oid))


if __name__ == "__main__":
    # Autocomprobación: deduplicación entre portales y fusión de URLs
    con = conectar(Path(":memory:"))
    a, nueva = guardar(con, {"empresa": "Talan Spain S.L.", "titulo": "Front-End Developer (Angular)",
                             "portales": ["linkedin"], "urls": ["https://li/1"], "ids_externos": ["li:1"], "encaje": 70})
    assert nueva
    b, nueva = guardar(con, {"empresa": "TALAN", "titulo": "Front-End Developer", "portales": ["tecnoempleo"],
                             "urls": ["https://te/9"], "encaje": None})
    assert b == a and not nueva, (a, b)
    c, _ = guardar(con, {"empresa": "Otra", "titulo": "X", "ids_externos": ["li:1"]})
    assert c == a
    f = con.execute("SELECT * FROM ofertas").fetchone()
    assert json.loads(f["portales"]) == ["linkedin", "tecnoempleo"] and f["encaje"] == 70
    assert norm("Desarrollador/a Frontend (m/f/d)") == "desarrollador a frontend"
    cambiar_estado(con, a, "enviada", "test")
    assert con.execute("SELECT enviada FROM ofertas").fetchone()[0] == date.today().isoformat()
    # Con huecos en la numeración no debe repetir un id existente
    d, _ = guardar(con, {"empresa": "Hueco", "titulo": "Uno"})
    e, _ = guardar(con, {"empresa": "Hueco", "titulo": "Dos"})
    con.execute("DELETE FROM ofertas WHERE id = ?", (d,))
    g, nueva = guardar(con, {"empresa": "Hueco", "titulo": "Tres"})
    assert nueva and g > e, (d, e, g)
    print("db.py OK")
