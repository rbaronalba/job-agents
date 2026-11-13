"""Histórico de ofertas en SQLite: deduplicación entre portales y estado de cada oferta."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_REAL = RAIZ / "data" / "historico.sqlite"
# JOB_AGENTS_DB: usar otra base (copia para ensayos). JOB_AGENTS_PRUEBA=1: modo prueba, nunca envía ni toca datos reales.
RUTA = Path(os.environ["JOB_AGENTS_DB"]).resolve() if os.environ.get("JOB_AGENTS_DB") else RUTA_REAL
PRUEBA = os.environ.get("JOB_AGENTS_PRUEBA") == "1"
# En prueba, todo lo que se escribe (Excel, CVs, logs, CSV de espontáneas) va a data/tmp/prueba/
_DATOS = RAIZ / "data" / "tmp" / "prueba" if PRUEBA else None
OUTPUT = _DATOS / "output" if PRUEBA else RAIZ / "output"
LOGS = _DATOS / "logs" if PRUEBA else RAIZ / "logs"
EXCEL = _DATOS / "ofertas" if PRUEBA else RAIZ / "data" / "ofertas"
EMPRESAS = _DATOS / "empresas.csv" if PRUEBA else RAIZ / "data" / "empresas.csv"

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


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or RUTA
    if PRUEBA and ruta.resolve() == RUTA_REAL.resolve():
        raise SystemExit("Modo prueba sin JOB_AGENTS_DB: no se toca el histórico real. Apunta JOB_AGENTS_DB a una copia.")
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


HUELLA_CAMPOS = "id, estado, encaje, justificacion, notas, enviada, clave, portales, urls, ids_externos"


def huella(ruta: Path | None = None) -> dict:
    """Huella de solo lectura del histórico: si no cambia, no se ha perdido ni alterado ninguna oferta."""
    con = sqlite3.connect(f"file:{(ruta or RUTA).as_posix()}?mode=ro", uri=True)
    filas = con.execute(f"SELECT {HUELLA_CAMPOS} FROM ofertas ORDER BY id").fetchall()
    return {
        "ruta": str(ruta or RUTA),
        "integridad": con.execute("PRAGMA integrity_check").fetchone()[0],
        "total": len(filas),
        "por_estado": dict(con.execute("SELECT estado, COUNT(*) FROM ofertas GROUP BY estado ORDER BY estado").fetchall()),
        "sha256": hashlib.sha256(json.dumps(filas, ensure_ascii=False).encode()).hexdigest()[:16],
    }


def cambiar_estado(con, oid: str, estado: str, nota: str | None = None):
    if estado not in ESTADOS:
        raise ValueError(f"Estado no válido: {estado}. Usa uno de {ESTADOS}")
    if PRUEBA and estado == "enviada":
        raise SystemExit("Modo prueba: nunca se envía, así que no se puede marcar ninguna oferta como enviada.")
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
