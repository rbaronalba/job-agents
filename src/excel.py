"""Excel semanal de ofertas: data/ofertas/ofertas_AAAA-Www.xlsx.

SQLite manda; el Excel es una vista que se regenera. Si el candidato cambia a mano la columna Estado o Notas,
exportar() lo detecta (columnas ocultas con lo último exportado) y lo pasa a SQLite antes de reescribir.
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from . import db

CARPETA = db.EXCEL  # en modo prueba, data/tmp/prueba/ofertas: nunca se pisa el Excel real
HOJA = "Ofertas"
# (cabecera, campo en SQLite o None si se calcula, ancho)
COLUMNAS = [
    ("ID", "id", 13), ("Encaje", "encaje", 8), ("Estado", "estado", 18), ("Eliminatorios", "eliminatorios", 28),
    ("Empresa", "empresa", 24), ("Puesto", "titulo", 40), ("Ubicación", "ubicacion", 18), ("Modalidad", "modalidad", 11),
    ("Salario", "salario", 16), ("Publicada", "fecha_pub", 11), ("Portales", "portales", 14), ("Enlace", "urls", 12),
    ("Candidatura", "tipo_candidatura", 14), ("Idioma", "idioma", 7), ("Categoría", "categoria", 11),
    ("Justificación", "justificacion", 55), ("Carencias", "carencias", 30), ("Coincidencia KW", "coincidencia_kw", 10),
    ("Enviada", "enviada", 11), ("Notas", "notas", 45),
    ("_estado_exp", "estado", 1), ("_notas_exp", "notas", 1),   # ocultas: lo último exportado
]
CAB = [c[0] for c in COLUMNAS]
AZUL = "FF1F4E78"
COLOR_ESTADO = {"nueva": "FFDDEBF7", "cv_adaptado": "FFFFF2CC", "pendiente_revision": "FFFCE4D6",
                "enviada": "FFE2EFDA", "descartada": "FFD9D9D9"}


def ruta(semana: str) -> Path:
    return CARPETA / f"ofertas_{semana}.xlsx"


def importar_cambios(con, semana: str) -> list[str]:
    """Pasa a SQLite los Estado/Notas que el candidato haya cambiado a mano en el Excel."""
    r = ruta(semana)
    if not r.exists():
        return []
    ws = load_workbook(r)[HOJA]
    filas = ws.iter_rows(min_row=2, values_only=True)
    i = {c: CAB.index(c) for c in ("ID", "Estado", "Notas", "_estado_exp", "_notas_exp")}
    cambios = []
    for f in filas:
        oid = f[i["ID"]]
        if not oid:
            continue
        estado, exp = (f[i["Estado"]] or "").strip(), f[i["_estado_exp"]]
        if estado and estado != exp:
            if estado not in db.ESTADOS:
                cambios.append(f"{oid}: estado '{estado}' no válido, se ignora")
            else:
                db.cambiar_estado(con, oid, estado)
                cambios.append(f"{oid}: {exp} -> {estado} (editado en Excel)")
        notas = f[i["Notas"]] or ""
        if notas != (f[i["_notas_exp"]] or ""):
            con.execute("UPDATE ofertas SET notas = ? WHERE id = ?", (notas, oid))
            cambios.append(f"{oid}: notas editadas en Excel")
    con.commit()
    return cambios


def _valor(fila, campo):
    v = fila[campo]
    if campo == "portales":
        return ", ".join(json.loads(v or "[]"))
    if campo == "urls":
        urls = json.loads(v or "[]")
        return urls[0] if urls else None
    return v


def exportar(con, semana: str | None = None) -> tuple[Path, list[str]]:
    semana = semana or db.semana()
    cambios = importar_cambios(con, semana)
    filas = con.execute("SELECT * FROM ofertas WHERE semana = ? ORDER BY estado = 'descartada', encaje DESC", (semana,)).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = HOJA
    for n, (cab, _, ancho) in enumerate(COLUMNAS, start=1):
        c = ws.cell(row=1, column=n, value=cab)
        c.font = Font(bold=True, color="FFFFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = ancho
        if cab.startswith("_"):
            ws.column_dimensions[c.column_letter].hidden = True

    for r, fila in enumerate(filas, start=2):
        for n, (cab, campo, _) in enumerate(COLUMNAS, start=1):
            c = ws.cell(row=r, column=n, value=_valor(fila, campo))
            c.alignment = Alignment(vertical="top", wrap_text=cab in ("Justificación", "Eliminatorios", "Carencias", "Notas", "Puesto"))
        url = _valor(fila, "urls")
        if url:
            c = ws.cell(row=r, column=CAB.index("Enlace") + 1, value="Abrir")
            c.hyperlink, c.style = url, "Hyperlink"
        ws.cell(row=r, column=CAB.index("Estado") + 1).fill = PatternFill("solid", fgColor=COLOR_ESTADO.get(fila["estado"], "FFFFFFFF"))

    ultima = max(len(filas) + 1, 2)
    letra = lambda cab: ws.cell(row=1, column=CAB.index(cab) + 1).column_letter
    dv = DataValidation(type="list", formula1='"' + ",".join(db.ESTADOS) + '"', allow_blank=False)
    dv.add(f"{letra('Estado')}2:{letra('Estado')}{ultima + 200}")
    ws.add_data_validation(dv)
    enc = f"{letra('Encaje')}2:{letra('Encaje')}{ultima}"
    ws.conditional_formatting.add(enc, CellIsRule(operator="greaterThanOrEqual", formula=["70"], fill=PatternFill("solid", fgColor="FFC6EFCE")))
    ws.conditional_formatting.add(enc, CellIsRule(operator="between", formula=["50", "69"], fill=PatternFill("solid", fgColor="FFFFEB9C")))
    ws.conditional_formatting.add(enc, CellIsRule(operator="lessThan", formula=["50"], fill=PatternFill("solid", fgColor="FFFFC7CE")))
    ws.conditional_formatting.add(f"{letra('Eliminatorios')}2:{letra('Eliminatorios')}{ultima}",
                                  FormulaRule(formula=[f'LEN({letra("Eliminatorios")}2)>0'], font=Font(color="FFC00000", bold=True)))
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{letra('Notas')}{ultima}"

    CARPETA.mkdir(parents=True, exist_ok=True)
    destino = ruta(semana)
    try:
        wb.save(destino)
    except PermissionError:
        raise SystemExit(f"No puedo guardar {destino.name}: ciérralo en Excel y vuelve a ejecutar.")
    return destino, cambios


if __name__ == "__main__":
    # Autocomprobación: exportar, editar a mano el estado en el Excel, y que vuelva a SQLite
    import tempfile
    CARPETA = Path(tempfile.mkdtemp())
    con = db.conectar(Path(":memory:"))
    a, _ = db.guardar(con, {"empresa": "A", "titulo": "Front", "encaje": 80, "urls": ["https://x/1"], "portales": ["linkedin"]})
    b, _ = db.guardar(con, {"empresa": "B", "titulo": "Angular", "encaje": 40, "eliminatorios": "+5 años"})
    sem = db.semana()
    p, _ = exportar(con, sem)
    wb = load_workbook(p); ws = wb[HOJA]
    assert ws.cell(row=2, column=1).value == a, "orden por encaje"
    ws.cell(row=2, column=CAB.index("Estado") + 1, value="descartada")
    ws.cell(row=3, column=CAB.index("Notas") + 1, value="no me interesa")
    wb.save(p)
    _, cambios = exportar(con, sem)
    assert con.execute("SELECT estado FROM ofertas WHERE id = ?", (a,)).fetchone()[0] == "descartada", cambios
    assert con.execute("SELECT notas FROM ofertas WHERE id = ?", (b,)).fetchone()[0] == "no me interesa"
    _, cambios = exportar(con, sem)
    assert cambios == [], cambios   # sin ediciones nuevas no reimporta nada
    print("excel.py OK")
