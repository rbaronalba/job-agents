"""CLI de job-agents: python -m src.cli <comando>

  filtrar     De una lista de ofertas candidatas (JSON), devuelve solo las no vistas ni ya postuladas
  guardar     Guarda o fusiona ofertas (JSON) en el histórico
  listar      Lista ofertas por estado
  estado      Cambia el estado de una oferta
  cv          Genera el CV adaptado de una oferta y lo verifica
  preparar    Deja el CV de una oferta listo para subir y muestra los datos del formulario
  enviada     Marca una oferta como enviada (y la registra en candidaturas-sync)
  excel       Importa cambios manuales del Excel semanal y lo regenera
  resumen     Resumen de la ejecución (consola y logs/)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from . import db

RAIZ = db.RAIZ


def perfil() -> dict:
    ruta = RAIZ / "config" / "profile.yaml"
    if not ruta.exists():
        raise SystemExit("Falta config/profile.yaml. Copia config/profile.example.yaml y rellénalo.")
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def leer_json(ruta: str):
    texto = sys.stdin.read() if ruta == "-" else Path(ruta).read_text(encoding="utf-8")
    datos = json.loads(texto)
    return datos if isinstance(datos, list) else [datos]


def ya_postuladas() -> tuple[set[str], set[str]]:
    """Claves empresa|puesto e ids de LinkedIn del Excel de candidaturas-sync."""
    carpeta = perfil().get("candidaturas_sync")
    if not carpeta:
        return set(), set()
    raiz = (RAIZ / carpeta).resolve()
    excel = raiz / "candidaturas.xlsx"
    cfg = raiz / "config.toml"
    if cfg.exists():
        import tomllib
        ruta = Path(tomllib.loads(cfg.read_text(encoding="utf-8")).get("excel", "candidaturas.xlsx")).expanduser()
        excel = ruta if ruta.is_absolute() else raiz / ruta
    if not excel.exists():
        print(f"Aviso: no encuentro {excel}; no se comprueban candidaturas ya enviadas.", file=sys.stderr)
        return set(), set()

    from openpyxl import load_workbook
    ws = load_workbook(excel, read_only=True, data_only=True)["Candidaturas"]
    filas = ws.iter_rows(values_only=True)
    cab = list(next(filas))
    i_emp, i_pue, i_ref = cab.index("Empresa"), cab.index("Puesto"), cab.index("Ref")
    claves, ids = set(), set()
    for f in filas:
        if f[i_emp]:
            claves.add(db.clave(f[i_emp], f[i_pue]))
        if f[i_ref] and str(f[i_ref]).startswith("li:"):
            ids.add(str(f[i_ref]))
    return claves, ids


def cmd_filtrar(args):
    con = db.conectar()
    claves, ids = ya_postuladas()
    nuevas, saltadas = [], []
    for o in leer_json(args.archivo):
        motivo = None
        if db.buscar(con, o):
            motivo = "ya vista"
        elif db.clave(o.get("empresa"), o.get("titulo")) in claves or set(o.get("ids_externos") or []) & ids:
            motivo = "ya postulada (candidaturas.xlsx)"
        (saltadas if motivo else nuevas).append({**o, "_motivo": motivo} if motivo else o)
    print(json.dumps({"nuevas": nuevas, "saltadas": [f"{o.get('empresa')} | {o.get('titulo')} ({o['_motivo']})" for o in saltadas]},
                     ensure_ascii=False, indent=1))


def cmd_guardar(args):
    con = db.conectar()
    res = {"nuevas": [], "fusionadas": []}
    for o in leer_json(args.archivo):
        if not o.get("empresa") or not o.get("titulo"):
            print(f"Ignorada (sin empresa o título): {o.get('urls')}", file=sys.stderr)
            continue
        oid, nueva = db.guardar(con, o)
        res["nuevas" if nueva else "fusionadas"].append(f"{oid} {o['empresa']} | {o['titulo']} ({o.get('encaje')})")
    con.commit()
    print(json.dumps(res, ensure_ascii=False, indent=1))


def cmd_listar(args):
    con = db.conectar()
    sql, params = "SELECT * FROM ofertas WHERE 1=1", []
    if args.estado:
        sql += " AND estado = ?"; params.append(args.estado)
    if args.semana:
        sql += " AND semana = ?"; params.append(args.semana)
    if args.min_encaje is not None:
        sql += " AND encaje >= ?"; params.append(args.min_encaje)
    filas = [dict(r) for r in con.execute(sql + " ORDER BY encaje DESC", params)]
    if args.json:
        print(json.dumps(filas, ensure_ascii=False, indent=1))
        return
    for f in filas:
        print(f"{f['id']}  {f['encaje'] or '-':>3}  {f['estado']:<18} {f['empresa']} | {f['titulo']} | {f['ubicacion'] or ''}")
    print(f"\n{len(filas)} ofertas")


def cmd_estado(args):
    con = db.conectar()
    db.cambiar_estado(con, args.id, args.estado, args.nota)
    con.commit()
    print(f"{args.id} -> {args.estado}")


def cmd_cv(args):
    from . import cv
    if args.id == "base":
        for idioma in ("es", "en"):
            inf = cv.generar({"idioma": idioma}, RAIZ / "output" / "base" / idioma)
            print(f"output/base/{idioma}/{cv.NOMBRE_PDF}: {inf['paginas']} página(s)")
        return
    con = db.conectar()
    oferta = con.execute("SELECT semana, titulo FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not oferta:
        raise SystemExit(f"No existe la oferta {args.id}")
    adapt = json.loads(Path(args.adaptacion).read_text(encoding="utf-8"))
    # El titular del CV debe llevar el título exacto del puesto (sin etiquetas tipo "(m/f/d)" o "(remoto)")
    if db.norm(oferta["titulo"]) not in db.norm(adapt.get("titular", "")):
        raise SystemExit(f"CV NO válido: el titular debe incluir el título del puesto '{oferta['titulo']}'")
    carpeta = RAIZ / "output" / oferta["semana"] / args.id
    inf = cv.generar(adapt, carpeta)
    (carpeta / "adaptacion.json").write_text(json.dumps(adapt, ensure_ascii=False, indent=1), encoding="utf-8")
    problemas = []
    if inf["paginas"] > 1:
        problemas.append(f"{inf['paginas']} páginas (recorta viñetas o proyectos)")
    if inf["guiones_prohibidos"]:
        problemas.append("contiene guiones largos o medios")
    print(json.dumps({k: v for k, v in inf.items() if k != "texto"}, ensure_ascii=False))
    if problemas:
        raise SystemExit("CV NO válido: " + "; ".join(problemas))
    con.execute("UPDATE ofertas SET coincidencia_kw = ?, carencias = COALESCE(?, carencias) WHERE id = ?",
                (f"{inf['coincidencia']}%" if inf["coincidencia"] is not None else None,
                 ", ".join(adapt["carencias"]) if adapt.get("carencias") else None, args.id))
    db.cambiar_estado(con, args.id, "cv_adaptado")
    con.commit()
    print(f"{args.id} -> cv_adaptado ({carpeta.relative_to(RAIZ)})")


def cmd_preparar(args):
    """Deja el CV en output/SUBIR/<id>/ (carpeta fácil de elegir en el diálogo de Windows) y devuelve lo necesario para postular."""
    import shutil
    con = db.conectar()
    o = con.execute("SELECT * FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not o:
        raise SystemExit(f"No existe la oferta {args.id}")
    origen = RAIZ / "output" / o["semana"] / args.id
    cv = origen / "CV_Candidato.pdf"
    if not cv.exists():
        raise SystemExit(f"{args.id} no tiene CV adaptado; ejecuta /adaptar primero")
    subir = RAIZ / "output" / "SUBIR" / args.id
    subir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cv, subir / cv.name)
    carta = origen / "carta.txt"
    p = perfil()
    print(json.dumps({
        "id": o["id"], "empresa": o["empresa"], "titulo": o["titulo"], "portales": json.loads(o["portales"]),
        "urls": json.loads(o["urls"]), "tipo_candidatura": o["tipo_candidatura"],
        "cv": str(subir / cv.name), "carta": carta.read_text(encoding="utf-8") if carta.exists() else None,
        "candidato": p["candidato"], "respuestas": p.get("respuestas", {}), "modo": p["envio"]["modo"],
    }, ensure_ascii=False, indent=1))


def registrar_en_seguimiento(o, origen: str) -> str:
    """Añade la candidatura a candidaturas.xlsx (candidaturas-sync) cuando el portal no manda correo de confirmación."""
    import subprocess
    carpeta = perfil().get("candidaturas_sync")
    if not carpeta:
        return "sin candidaturas_sync configurado"
    raiz = (RAIZ / carpeta).resolve()
    url = (json.loads(o["urls"]) or [None])[0]
    cmd = [sys.executable, "-m", "candidaturas", "nueva", "--empresa", o["empresa"], "--puesto", o["titulo"],
           "--origen", origen, "--nota", f"Enviada por job-agents ({o['id']})"] + (["--enlace", url] if url else [])
    r = subprocess.run(cmd, cwd=raiz, capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or r.stderr).strip()


def cmd_enviada(args):
    con = db.conectar()
    o = con.execute("SELECT * FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not o:
        raise SystemExit(f"No existe la oferta {args.id}")
    db.cambiar_estado(con, args.id, "enviada", f"Enviada por {args.origen}")
    con.commit()
    print(f"{args.id} -> enviada")
    # LinkedIn manda "se ha enviado tu solicitud" y candidaturas-sync la detecta sola
    if args.origen.lower() != "linkedin":
        print("Seguimiento:", registrar_en_seguimiento(o, args.origen))
    import shutil
    shutil.rmtree(RAIZ / "output" / "SUBIR" / args.id, ignore_errors=True)


def cmd_excel(args):
    from . import excel
    con = db.conectar()
    destino, cambios = excel.exportar(con, args.semana)
    for c in cambios:
        print(c)
    print(f"Excel actualizado: {destino.relative_to(RAIZ)}")


def cmd_resumen(args):
    con = db.conectar()
    hoy = date.today().isoformat()
    q = lambda sql, *p: con.execute(sql, p).fetchone()[0]
    lineas = [
        f"# Resumen {datetime.now():%Y-%m-%d %H:%M}",
        f"- Ofertas nuevas hoy: {q('SELECT COUNT(*) FROM ofertas WHERE creada >= ? AND estado != ?', hoy, 'descartada')}",
        f"- Descartadas hoy (idioma, fraude o cerradas): {q('SELECT COUNT(*) FROM ofertas WHERE creada >= ? AND estado = ?', hoy, 'descartada')}",
        f"- CVs adaptados pendientes de enviar: {q('SELECT COUNT(*) FROM ofertas WHERE estado = ?', 'cv_adaptado')}",
        f"- Pendientes de tu revisión: {q('SELECT COUNT(*) FROM ofertas WHERE estado = ?', 'pendiente_revision')}",
        f"- Candidaturas enviadas hoy: {q('SELECT COUNT(*) FROM ofertas WHERE enviada = ?', hoy)}",
    ]
    if args.errores:
        lineas.append(f"- Errores: {args.errores}")
    texto = "\n".join(lineas)
    print(texto)
    logs = RAIZ / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / f"{hoy}.md", "a", encoding="utf-8") as f:
        f.write(texto + "\n\n")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m src.cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("filtrar"); s.add_argument("archivo", help="JSON o - para stdin"); s.set_defaults(fn=cmd_filtrar)
    s = sub.add_parser("guardar"); s.add_argument("archivo", help="JSON o - para stdin"); s.set_defaults(fn=cmd_guardar)

    s = sub.add_parser("listar")
    s.add_argument("--estado", choices=db.ESTADOS)
    s.add_argument("--semana")
    s.add_argument("--min-encaje", type=int)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_listar)

    s = sub.add_parser("estado")
    s.add_argument("id"); s.add_argument("estado", choices=db.ESTADOS); s.add_argument("--nota")
    s.set_defaults(fn=cmd_estado)

    s = sub.add_parser("cv", help="Genera CV_Candidato.pdf para una oferta (o 'base')")
    s.add_argument("id", help="ID de oferta o 'base'")
    s.add_argument("adaptacion", nargs="?", help="JSON de adaptación (obligatorio salvo con 'base')")
    s.set_defaults(fn=cmd_cv)

    s = sub.add_parser("preparar", help="Copia el CV a output/SUBIR/<id>/ y muestra datos para postular")
    s.add_argument("id")
    s.set_defaults(fn=cmd_preparar)

    s = sub.add_parser("enviada", help="Marca enviada y la registra en candidaturas-sync si hace falta")
    s.add_argument("id")
    s.add_argument("--origen", required=True, help="LinkedIn, InfoJobs, Tecnoempleo, Web empresa...")
    s.set_defaults(fn=cmd_enviada)

    s = sub.add_parser("excel", help="Importa cambios manuales y regenera el Excel semanal")
    s.add_argument("--semana", help="AAAA-Www (por defecto la actual)")
    s.set_defaults(fn=cmd_excel)

    s = sub.add_parser("resumen"); s.add_argument("--errores"); s.set_defaults(fn=cmd_resumen)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
