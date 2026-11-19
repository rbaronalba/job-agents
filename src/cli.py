"""CLI de job-agents: python -m src.cli <comando>

  filtrar     De una lista de ofertas candidatas (JSON), devuelve solo las no vistas ni ya postuladas
  guardar     Guarda o fusiona ofertas (JSON) en el histórico
  listar      Lista ofertas por estado (--json compacto; --json --completo con todas las columnas)
  oferta      Detalle completo de una oferta (o --campos concretos)
  estado      Cambia el estado de una oferta
  cv          Genera el CV adaptado de una oferta y lo verifica
  preparar    Deja el CV de una oferta listo para subir y muestra los datos del formulario (--sin-perfil)
  perfil-formulario  Candidato y respuestas fijas para formularios (una vez por sesión)
  enviada     Marca una oferta como enviada (y la registra en candidaturas-sync)
  excel       Importa cambios manuales del Excel semanal y lo regenera
  resumen     Resumen de la ejecución (consola y logs/)
  espontaneas-consulta  Solo lectura: CSV de espontáneas y coincidencias de una empresa en candidaturas.xlsx (JSON)
  perfiles    Perfiles de candidatura (perfiles_cv): cuándo aplica cada uno, asunto y CV fijo (JSON)
  espontaneas-informe  Solo lectura: envíos de espontáneas cruzados con respuestas del Excel, por categoría, destinatario, sector, tecnología y semana
  pendientes  Ofertas nuevas, CVs por enviar, envíos de hoy y cupos restantes (JSON)
  modo        Modos de envío efectivos (JOB_AGENTS_PRUEBA=1 fuerza revision/borrador) y rutas activas
  huella      Huella de solo lectura del histórico para comprobar que no se pierde ni cambia nada
  depurar     Filtro de calidad sobre la cola: Senior, eliminatorios o encaje bajo pasan a descartada
  resultados  Sincroniza respuestas/rechazos desde candidaturas.xlsx, marca silencios y muestra el embudo
  contactos   Enviadas que necesitan contacto en LinkedIn o mensaje de seguimiento (JSON); --hoy: textos de hoy
  contacto    Guarda persona, nota de conexión o seguimiento de una oferta (nunca envía nada)

Variables de entorno: JOB_AGENTS_DB (usar otra base, p. ej. una copia) y JOB_AGENTS_PRUEBA=1 (ensayo:
no envía, exige JOB_AGENTS_DB y escribe Excel, CVs, logs y CSV en data/tmp/prueba/).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from . import db, espont

RAIZ = db.RAIZ


def perfil() -> dict:
    # JOB_AGENTS_PERFIL: otro perfil (los tests usan uno fijo, nunca el real)
    ruta = Path(os.environ["JOB_AGENTS_PERFIL"]) if os.environ.get("JOB_AGENTS_PERFIL") else RAIZ / "config" / "profile.yaml"
    if not ruta.exists():
        raise SystemExit("Falta config/profile.yaml. Copia config/profile.example.yaml y rellénalo.")
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def modos(p: dict | None = None) -> dict:
    """Modos de envío efectivos. En modo prueba nunca se envía: revision y borrador, digan lo que digan el perfil."""
    envio = (p or perfil()).get("envio") or {}
    if db.PRUEBA:
        return {"portales": "revision", "espontaneas": "borrador", "prueba": True}
    # Nunca se supone un modo: si falta o no es válido, error (y la fase se detiene)
    m = {"portales": envio.get("modo"), "espontaneas": envio.get("espontaneas_modo")}
    validos = {"portales": ("revision", "auto"), "espontaneas": ("borrador", "auto")}
    if any(m[k] not in validos[k] for k in m):
        raise SystemExit(f"Modo de envío no válido en config/profile.yaml: envio.modo={m['portales']!r}, "
                         f"envio.espontaneas_modo={m['espontaneas']!r}")
    return {**m, "prueba": False}


def leer_json(ruta: str):
    texto = sys.stdin.read() if ruta == "-" else Path(ruta).read_text(encoding="utf-8")
    datos = json.loads(texto)
    return datos if isinstance(datos, list) else [datos]


def carpeta_sync() -> Path | None:
    """Carpeta de candidaturas-sync del perfil. Debe estar dentro del proyecto: de ella se importa y ejecuta código."""
    carpeta = perfil().get("candidaturas_sync")
    if not carpeta:
        return None
    raiz = (RAIZ / carpeta).resolve()
    if not raiz.is_relative_to(RAIZ.resolve()):
        raise SystemExit(f"candidaturas_sync debe estar dentro del proyecto, no en {raiz}")
    return raiz


def ruta_candidaturas() -> Path | None:
    """Ruta del Excel de candidaturas-sync (según su config.toml), o None si candidaturas_sync no está configurado."""
    raiz = carpeta_sync()
    if raiz is None:
        return None
    excel = raiz / "candidaturas.xlsx"
    cfg = raiz / "config.toml"
    if cfg.exists():
        import tomllib
        ruta = Path(tomllib.loads(cfg.read_text(encoding="utf-8")).get("excel", "candidaturas.xlsx")).expanduser()
        excel = ruta if ruta.is_absolute() else raiz / ruta
    return excel


def ya_postuladas() -> tuple[set[str], set[str]]:
    """Claves empresa|puesto e ids de LinkedIn del Excel de candidaturas-sync.

    Sin candidaturas_sync configurado no hay nada que comprobar (vacío). Configurado pero ausente, corrupto o
    ilegible: error, nunca cero candidaturas (se volvería a postular a lo ya enviado)."""
    excel = ruta_candidaturas()
    if excel is None:
        return set(), set()
    if not excel.exists():
        raise SystemExit(f"No existe {excel}: no se puede comprobar qué ofertas ya se postularon. Nada filtrado.")
    from openpyxl import load_workbook
    try:
        wb = load_workbook(excel, read_only=True, data_only=True)
        try:
            filas = wb["Candidaturas"].iter_rows(values_only=True)
            cab = list(next(filas))
            i_emp, i_pue, i_ref = cab.index("Empresa"), cab.index("Puesto"), cab.index("Ref")
            claves, ids = set(), set()
            for f in filas:
                if f[i_emp]:
                    claves.add(db.clave(f[i_emp], f[i_pue]))
                if f[i_ref] and str(f[i_ref]).startswith("li:"):
                    ids.add(str(f[i_ref]))
        finally:
            wb.close()
    except Exception as e:   # noqa: BLE001 - corrupto, bloqueado, sin hoja o sin columnas: nunca se toma como vacío
        raise SystemExit(f"No se puede leer {excel} ({type(e).__name__}: {e}): no se puede comprobar qué ofertas "
                         "ya se postularon. Nada filtrado.")
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


def minimo_postular(p: dict | None = None) -> int:
    return ((p or perfil()).get("encaje") or {}).get("minimo_postular", 55)


def cmd_guardar(args):
    con = db.conectar()
    minimo = minimo_postular()
    res = {"nuevas": [], "fusionadas": []}
    for o in leer_json(args.archivo):
        if not o.get("empresa") or not o.get("titulo"):
            print(f"Ignorada (sin empresa o título): {o.get('urls')}", file=sys.stderr)
            continue
        # Filtro de calidad solo al insertar: una oferta ya guardada conserva su estado
        motivo = None if db.buscar(con, o) else db.motivo_filtro(
            {"titulo": o.get("titulo"), "eliminatorios": o.get("eliminatorios"), "encaje": o.get("encaje")}, minimo)
        if motivo and (o.get("estado") or "nueva") == "nueva":
            o = {**o, "estado": "descartada", "notas": "; ".join(x for x in [o.get("notas"), f"Filtro: {motivo}"] if x)}
        oid, nueva = db.guardar(con, o)
        res["nuevas" if nueva else "fusionadas"].append(f"{oid} {o['empresa']} | {o['titulo']} ({o.get('encaje')})")
    con.commit()
    print(json.dumps(res, ensure_ascii=False, indent=1))


CAMPOS_LISTA = ["id", "encaje", "estado", "empresa", "titulo", "portales", "tipo_candidatura", "fecha_pub"]


def cmd_oferta(args):
    con = db.conectar()
    o = con.execute("SELECT * FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not o:
        raise SystemExit(f"No existe la oferta {args.id}")
    o = dict(o)
    for k in ("portales", "urls", "ids_externos", "requisitos"):
        try:
            o[k] = json.loads(o[k]) if o[k] else o[k]
        except ValueError:
            pass   # requisitos puede ser texto plano en ofertas antiguas
    if args.campos:
        o = {k: o.get(k) for k in ["id", *args.campos.split(",")]}
    print(json.dumps(o, ensure_ascii=False, indent=1))


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
    if args.json and args.completo:
        print(json.dumps(filas, ensure_ascii=False, indent=1))
        return
    if args.json:
        # Compacto: lo justo para elegir y ordenar. El detalle de una oferta, con `oferta <id>`.
        print("[\n" + ",\n".join(json.dumps({k: json.loads(f[k]) if k == "portales" else f[k] for k in CAMPOS_LISTA},
                                            ensure_ascii=False) for f in filas) + "\n]")
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
        if db.PRUEBA:   # reescribiría los PDF reales de cv/
            raise SystemExit("cv base no se ejecuta en modo prueba (JOB_AGENTS_PRUEBA=1): escribe en cv/ real")
        # Modelos fijos que se adjuntan en las candidaturas espontáneas: uno por clave de `perfiles` de cv_base.yaml
        base = yaml.safe_load(cv.BASE.read_text(encoding="utf-8"))
        for carpeta, idioma in cv.cvs_fijos(base):
            inf = cv.generar({"idioma": idioma, **({} if carpeta == "base" else {"perfil": carpeta})}, RAIZ / "cv" / carpeta / idioma)
            print(f"cv/{carpeta}/{idioma}/{cv.nombre_pdf()}: {inf['paginas']} página(s)")
        return
    con = db.conectar()
    oferta = con.execute("SELECT semana, titulo FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not oferta:
        raise SystemExit(f"No existe la oferta {args.id}")
    adapt = json.loads(Path(args.adaptacion).read_text(encoding="utf-8"))
    # El titular del CV debe llevar el título exacto del puesto (sin etiquetas tipo "(m/f/d)" o "(remoto)")
    if db.norm(oferta["titulo"]) not in db.norm(adapt.get("titular", "")):
        raise SystemExit(f"CV NO válido: el titular debe incluir el título del puesto '{oferta['titulo']}'")
    carpeta = db.OUTPUT / oferta["semana"] / args.id
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
    print(f"{args.id} -> cv_adaptado ({db.corta(carpeta)})")


def cmd_preparar(args):
    """Deja el CV en output/SUBIR/<id>/ (carpeta fácil de elegir en el diálogo de Windows) y devuelve lo necesario para postular."""
    import shutil
    from . import cv as cv_mod
    con = db.conectar()
    o = con.execute("SELECT * FROM ofertas WHERE id = ?", (args.id,)).fetchone()
    if not o:
        raise SystemExit(f"No existe la oferta {args.id}")
    origen = db.OUTPUT / o["semana"] / args.id
    cv_pdf = origen / cv_mod.nombre_pdf()
    if not cv_pdf.exists():
        raise SystemExit(f"{args.id} no tiene CV adaptado; ejecuta /adaptar primero")
    subir = db.OUTPUT / "SUBIR" / args.id
    subir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cv_pdf, subir / cv_pdf.name)
    carta = origen / "carta.txt"
    p = perfil()
    datos = {
        "id": o["id"], "empresa": o["empresa"], "titulo": o["titulo"], "portales": json.loads(o["portales"]),
        "urls": json.loads(o["urls"]), "tipo_candidatura": o["tipo_candidatura"],
        "cv": str(subir / cv_pdf.name), "carta": carta.read_text(encoding="utf-8") if carta.exists() else None,
        "modo": modos(p)["portales"],
    }
    if not args.sin_perfil:   # con --sin-perfil, candidato y respuestas se piden una vez con `perfil-formulario`
        datos.update(candidato=p["candidato"], respuestas=p.get("respuestas", {}))
    print(json.dumps(datos, ensure_ascii=False, indent=1))


def cmd_perfil_formulario(args):
    p = perfil()
    # salario_minimo: el postulador no puede leer el perfil (D3) y lo necesita para descartar ofertas por sueldo
    print(json.dumps({"candidato": p["candidato"], "respuestas": p.get("respuestas", {}), "modo": modos(p)["portales"],
                      "salario_minimo": (p.get("encaje") or {}).get("salario_minimo")}, ensure_ascii=False, indent=1))


def registrar_en_seguimiento(o, origen: str) -> str:
    """Añade la candidatura a candidaturas.xlsx (candidaturas-sync) cuando el portal no manda correo de confirmación."""
    import subprocess
    raiz = carpeta_sync()
    if raiz is None:
        return "sin candidaturas_sync configurado"
    url = (json.loads(o["urls"]) or [None])[0]
    cmd = [sys.executable, "-m", "candidaturas", "nueva", f"--empresa={o['empresa']}", f"--puesto={o['titulo']}",
           f"--origen={origen}", f"--nota=Enviada por job-agents ({o['id']})"] + ([f"--enlace={url}"] if url else [])
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
    if args.origen.lower() != "linkedin":   # en prueba cambiar_estado ya abortó: aquí nunca se llega
        print("Seguimiento:", registrar_en_seguimiento(o, args.origen))
    import shutil
    shutil.rmtree(db.OUTPUT / "SUBIR" / args.id, ignore_errors=True)


def cmd_excel(args):
    from . import excel
    con = db.conectar()
    destino, cambios = excel.exportar(con, args.semana)
    for c in cambios:
        print(c)
    print(f"Excel actualizado: {db.corta(destino)}")


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
        "- Embudo total: " + ", ".join(f"{k} {v}" for k, v in embudo_total(con).items()),
    ]
    if args.errores:
        lineas.append(f"- Errores: {args.errores}")
    texto = "\n".join(lineas)
    print(texto)
    logs = db.LOGS
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / f"{hoy}.md", "a", encoding="utf-8") as f:
        f.write(texto + "\n\n")


def espontaneas_hoy(hoy: str) -> list[str]:
    """Empresas del CSV de espontáneas con borrador o envío hoy (misma regla que espontaneas.md)."""
    import csv
    if not db.EMPRESAS.exists():
        return []
    with open(db.EMPRESAS, encoding="utf-8", newline="") as f:
        return [r.get("empresa") or "" for r in csv.DictReader(f)
                if (r.get("fecha") or "").startswith(hoy) and r.get("estado") in ("enviada", "borrador")]


def pendientes(con=None, p: dict | None = None) -> dict:
    """Qué trabajo queda hoy, para que el orquestador no lance fases vacías. Solo lectura."""
    con = con or db.conectar()
    envio = (p or perfil()).get("envio", {})
    hoy = date.today().isoformat()
    ids = lambda estado: [r[0] for r in con.execute(
        "SELECT id FROM ofertas WHERE estado = ? ORDER BY encaje DESC", (estado,))]
    enviadas = [f"{e} | {t}" for e, t in con.execute("SELECT empresa, titulo FROM ofertas WHERE enviada = ?", (hoy,))]
    esp = espontaneas_hoy(hoy)
    total = envio.get("max_diario_total", 30)
    queda_total = total - len(enviadas) - len(esp)
    return {
        "nuevas": ids("nueva"),
        "cv_adaptado": ids("cv_adaptado"),
        "enviadas_hoy": enviadas,
        "espontaneas_hoy": esp,
        "cupo_portales": max(0, min(envio.get("max_diario_portales", 15) - len(enviadas), queda_total)),
        "cupo_espontaneas": max(0, min(envio.get("espontaneas_objetivo_diario", 12), envio.get("espontaneas_max_diario", 15),
                                       total - len(enviadas)) - len(esp)),
        "candidaturas_sync": (p or perfil()).get("candidaturas_sync"),
        "contactos": {k: [o["id"] for o in v] for k, v in contactos_pendientes(con, cfg_contactos(p)).items()},
        "prueba": db.PRUEBA,
    }


def cmd_pendientes(args):
    print(json.dumps(pendientes(), ensure_ascii=False, indent=1))


def _fallo(mensaje: str):
    """Error explícito: nunca se devuelve como cero resultados."""
    print(json.dumps({"ok": False, "error": mensaje}, ensure_ascii=False, sort_keys=True))
    raise SystemExit(2)


def cmd_espontaneas_consulta(args):
    """Solo lectura. CSV de espontáneas: filas, por estado y envíos de hoy. Con --empresa/--dominio, además, sus
    coincidencias en la hoja Candidaturas de candidaturas.xlsx. Cualquier archivo ausente o ilegible es un error."""
    import csv
    from collections import Counter
    hoy = date.today().isoformat()
    ruta_csv = Path(args.csv) if args.csv else db.EMPRESAS
    if not ruta_csv.is_file():
        _fallo(f"no existe el CSV de empresas: {ruta_csv}")
    try:
        with open(ruta_csv, encoding="utf-8", newline="") as f:
            lector = csv.DictReader(f)
            faltan = {"empresa", "estado", "fecha"} - set(lector.fieldnames or [])
            filas = list(lector)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        _fallo(f"no se puede leer {ruta_csv}: {e}")
    if faltan:
        _fallo(f"al CSV {ruta_csv} le faltan columnas: {sorted(faltan)}")
    de_hoy = Counter(r["estado"] for r in filas if (r.get("fecha") or "").startswith(hoy) and r.get("estado") in ("enviada", "borrador"))
    p = perfil()
    envio = p.get("envio") or {}
    avisos = [f"{r.get('empresa')}: {e}" for r in filas for e in espont.validar_fila(r)]
    salida = {"ok": True, "csv": {
        "ruta": str(ruta_csv), "filas": len(filas),
        "por_estado": dict(sorted(Counter((r.get("estado") or "") for r in filas).items())),
        "hoy": {"enviada": de_hoy["enviada"], "borrador": de_hoy["borrador"], "total": sum(de_hoy.values())},
    }, "clasificacion": {   # aparte de "csv": su contenido es un contrato que otras pruebas comparan exacto
        "por_categoria": dict(sorted(Counter((r.get("categoria") or "sin_clasificar") for r in filas).items())),
        "retenidas_sin_evaluar": sum(1 for r in filas if r.get("estado") == "retenida" and not r.get("categoria")),
        "cola": [r["empresa"] for r in espont.cola(filas, envio.get("espontaneas_anillos") or [],
                                                     envio.get("espontaneas_anillo_actual", 0), db.norm)][:40],
        "avisos": avisos[:20],
    }}
    if args.empresa or args.dominio:
        salida["candidaturas"] = _candidaturas_de(args)
    print(json.dumps(salida, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def cmd_perfiles(args):
    """Solo lectura. Perfiles de candidatura (config/profile.yaml: perfiles_cv) y si su CV fijo existe en cada idioma."""
    from . import cv
    base = yaml.safe_load(cv.BASE.read_text(encoding="utf-8"))
    perfiles, avisos = cv.perfiles_cv(perfil(), base)
    for p in perfiles:
        p["pdf"] = {i: len(list((RAIZ / p["carpeta"] / i).glob("*.pdf"))) == 1 for i in cv._idiomas(base)}
        avisos += [f"{p['id']}: falta el PDF único en {p['carpeta']}/{i}/ (python -m src.cli cv base)"
                   for i, ok in p["pdf"].items() if not ok]
    print(json.dumps({"ok": True, "perfiles": perfiles, "avisos": avisos}, ensure_ascii=False, sort_keys=True))


def cmd_espontaneas_informe(args):
    """Solo lectura. Envíos de espontáneas (CSV) cruzados con el resultado del Excel (la única fuente de respuestas)."""
    import csv
    ruta_csv = Path(args.csv) if args.csv else db.EMPRESAS
    if not ruta_csv.is_file():
        _fallo(f"no existe el CSV de empresas: {ruta_csv}")
    with open(ruta_csv, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    resultados = None
    ruta = Path(args.excel) if args.excel else ruta_candidaturas()
    if ruta and ruta.is_file():
        from openpyxl import load_workbook
        wb = load_workbook(ruta, read_only=True, data_only=True)
        try:
            it = wb["Candidaturas"].iter_rows(values_only=True)
            cab = [str(c or "") for c in next(it)]
            xl = [dict(zip(cab, r)) for r in it]
        finally:
            wb.close()
        orden = {"entrevista": 3, "respuesta": 2, "rechazo": 1, None: 0}
        por_clave = {}
        for r in xl:
            if "espont" in str(r.get("Puesto") or "").lower():
                k = db.clave(str(r.get("Empresa") or ""), "").split("|")[0]
                res = resultado_de(r.get("Fase"), r.get("Notas"))
                if orden[res] >= orden[por_clave.get(k)]:
                    por_clave[k] = res
        resultados = {}
        for f in filas:
            k = db.clave(f.get("empresa") or "", "").split("|")[0]
            for otra, res in por_clave.items():
                if k and k == otra:   # exacta: por subcadena, 'acme' y 'acmesoft' se confundían
                    if orden[res] >= orden[resultados.get(f["empresa"])]:
                        resultados[f["empresa"]] = res
    inf = espont.informe(filas, resultados)
    print(json.dumps(inf, ensure_ascii=False, sort_keys=True) if args.json else espont.texto(inf))


def _candidaturas_de(args) -> dict:
    ruta = Path(args.excel) if args.excel else ruta_candidaturas()
    if ruta is None:
        return {"configurado": False}
    if not ruta.is_file():
        _fallo(f"no existe el Excel de candidaturas: {ruta}")
    from openpyxl import load_workbook
    try:
        wb = load_workbook(ruta, read_only=True, data_only=True)   # read_only: nunca se guarda
    except Exception as e:   # noqa: BLE001 - archivo corrupto, bloqueado, no es xlsx...
        _fallo(f"no se puede leer {ruta}: {type(e).__name__}: {e}")
    try:
        if "Candidaturas" not in wb.sheetnames:
            _fallo(f"{ruta} no tiene la hoja Candidaturas")
        filas = wb["Candidaturas"].iter_rows(values_only=True)
        cab = [str(c or "") for c in next(filas, [])]
        if "Empresa" not in cab:
            _fallo(f"la hoja Candidaturas de {ruta} no tiene la columna Empresa")
        col = {c: cab.index(c) for c in ("Fecha", "Empresa", "Puesto", "Enlace", "Fase", "Origen", "Notas") if c in cab}
        emp = db.clave(args.empresa, "").split("|")[0] if args.empresa else ""
        dom = (args.dominio or "").lower().removeprefix("www.").strip()
        coincidencias, n = [], 0
        for n, f in enumerate(filas, start=2):
            celda = lambda c: f[col[c]] if c in col and col[c] < len(f) else None
            otra = db.clave(str(celda("Empresa") or ""), "").split("|")[0]
            # Nombre normalizado igual, o uno contenido en el otro si es suficientemente largo; dominio en cualquier celda
            por_empresa = bool(emp and otra and (emp == otra or (min(len(emp), len(otra)) >= 4 and (emp in otra or otra in emp))))
            por_dominio = bool(dom and any(dom in str(v).lower() for v in f if v))
            if por_empresa or por_dominio:
                coincidencias.append({"fila": n, "motivo": "empresa" if por_empresa else "dominio",
                                      **{c.lower(): celda(c) for c in ("Fecha", "Empresa", "Puesto", "Fase", "Origen")}})
    finally:
        wb.close()
    return {"configurado": True, "ruta": str(ruta), "filas": max(n - 1, 0), "contactada": bool(coincidencias),
            "coincidencias": coincidencias}


def cmd_depurar(args):
    """Aplica el filtro de calidad a las ofertas nuevas: lo que no pasa queda descartada con el motivo.
    Las ya adaptadas (CV hecho, quizá en postulación) solo con --incluir-adaptadas."""
    con = db.conectar()
    minimo = minimo_postular()
    estados = ("nueva", "cv_adaptado") if args.incluir_adaptadas else ("nueva",)
    fuera = [(o["id"], m, o["empresa"], o["titulo"]) for o in con.execute(
        f"SELECT * FROM ofertas WHERE estado IN ({','.join('?' * len(estados))})", estados) if (m := db.motivo_filtro(o, minimo))]
    for oid, m, *_ in fuera if not args.simular else []:
        db.cambiar_estado(con, oid, "descartada", f"Filtro: {m}")
    con.commit()
    for f in fuera:
        print(" | ".join(f))
    print(f"{len(fuera)} ofertas {'se descartarían' if args.simular else 'descartadas'} (mínimo {minimo})")


# Notas de candidaturas.xlsx que indican entrevista o respuesta de la empresa
_ENTREVISTA = re.compile(r"entrevista|interview|videollamada|llamada|prueba t[eé]cnica|technical test", re.I)
_RESPUESTA = re.compile(r"ha respondido|respond", re.I)
# "no ha respondido", "sin respuesta", "sin entrevista"...: la negación anula lo que sigue
_NEGADO = re.compile(r"\b(?:no|sin|nunca|ni)\s+(?:ha\s+|han\s+|hay\s+|hubo\s+|tengo\s+)?\w*\s?(?:respond|respuesta|entrevista|llamad|interview|videollamada)\w*", re.I)


def resultado_de(fase: str | None, notas: str | None) -> str | None:
    if fase == "Rechazado":
        return "rechazo"
    notas = _NEGADO.sub(" ", notas or "")
    if _ENTREVISTA.search(notas):
        return "entrevista"
    if fase == "Completado" or _RESPUESTA.search(notas):
        return "respuesta"
    return None


def sincronizar(con, filas_xlsx, hoy: date, dias_silencio: int = 14) -> list[str]:
    """Pasa al histórico lo que candidaturas-sync sabe de cada candidatura enviada y marca los silencios.
    Solo avanza (db.RESULTADO): nunca devuelve una oferta a un estado anterior."""
    if filas_xlsx is None:   # sin Excel no se sabe si respondieron: no se inventan silencios
        return []
    por_clave, por_ref = {}, {}
    for f in filas_xlsx:
        if r := resultado_de(f.get("Fase"), f.get("Notas")):
            por_clave[db.clave(f.get("Empresa"), f.get("Puesto"))] = r
            if str(f.get("Ref") or "").startswith("li:"):
                por_ref[str(f["Ref"])] = r
    cambios = []
    for o in con.execute("SELECT id, clave, ids_externos, estado, enviada, empresa FROM ofertas WHERE enviada IS NOT NULL").fetchall():
        if o["estado"] not in db.RESULTADO:
            continue
        nuevo = por_clave.get(o["clave"]) or next((por_ref[i] for i in json.loads(o["ids_externos"] or "[]") if i in por_ref), None)
        if not nuevo and (hoy - date.fromisoformat(o["enviada"])).days >= dias_silencio:
            nuevo = "silencio_14d"
        if nuevo and db.RESULTADO[nuevo] > db.RESULTADO[o["estado"]]:
            db.cambiar_estado(con, o["id"], nuevo, None if nuevo == "silencio_14d" else f"candidaturas-sync: {nuevo}")
            cambios.append(f"{o['id']} {o['empresa']}: {o['estado']} -> {nuevo}")
    return cambios


def _filas_candidaturas() -> list[dict] | None:
    """Filas de candidaturas.xlsx, o None si no está configurado o no existe (distinto de un Excel vacío)."""
    ruta = ruta_candidaturas()
    if ruta is None or not ruta.is_file():
        return None
    from openpyxl import load_workbook
    wb = load_workbook(ruta, read_only=True, data_only=True)
    try:
        filas = wb["Candidaturas"].iter_rows(values_only=True)
        cab = [str(c or "") for c in next(filas)]
        return [dict(zip(cab, f)) for f in filas]
    finally:
        wb.close()


def embudo_total(con) -> dict:
    """Solo los totales (un COUNT): embudo() lee del disco el adaptacion.json de cada enviada."""
    total = {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0, "silencio_14d": 0}
    for estado, n in con.execute("SELECT estado, COUNT(*) FROM ofertas WHERE enviada IS NOT NULL GROUP BY estado"):
        total["enviadas"] += n
        if estado in total:
            total[estado] += n
    return total


def embudo(con) -> dict:
    """Enviadas y resultados por portal, tipo de candidatura, categoría, CV (perfil) y si hubo contacto."""
    from collections import defaultdict
    grupos = defaultdict(lambda: defaultdict(lambda: {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0}))
    total = {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0, "silencio_14d": 0}
    for o in con.execute("SELECT * FROM ofertas WHERE enviada IS NOT NULL"):
        adapt = db.OUTPUT / o["semana"] / o["id"] / "adaptacion.json"
        try:
            cv_perfil = json.loads(adapt.read_text(encoding="utf-8")).get("perfil") or "base"
        except (OSError, ValueError):
            cv_perfil = "sin_cv"
        claves = {"portal": (json.loads(o["portales"] or "[]") or ["?"])[0], "tipo": o["tipo_candidatura"] or "?",
                  "categoria": o["categoria"] or "?", "cv": cv_perfil,
                  "contacto": "sí" if o["contacto"] and o["contacto"] != "no encontrado" else "no"}
        total["enviadas"] += 1
        if o["estado"] in total:
            total[o["estado"]] += 1
        for dim, val in claves.items():
            g = grupos[dim][val]
            g["enviadas"] += 1
            if o["estado"] in g:
                g[o["estado"]] += 1
    return {"total": total, **{d: dict(v) for d, v in grupos.items()}}


def embudo_espontaneas(filas_xlsx) -> dict:
    """Respuestas a las candidaturas espontáneas (filas de candidaturas.xlsx con 'espont' en el puesto)."""
    t = {"enviadas": 0, "respuesta": 0, "entrevista": 0, "rechazo": 0}
    for f in filas_xlsx:
        if "espont" in str(f.get("Puesto") or "").lower():
            t["enviadas"] += 1
            if r := resultado_de(f.get("Fase"), f.get("Notas")):
                t[r] += 1
    return t


def cmd_resultados(args):
    con = db.conectar()
    filas = _filas_candidaturas()
    esp = embudo_espontaneas(filas or [])
    cambios = sincronizar(con, filas, date.today())
    if args.simular:
        con.rollback()
    else:
        con.commit()
    for c in cambios:
        print(c)
    e = {**embudo(con), "espontaneas": esp}
    print(json.dumps(e if args.json else e["total"], ensure_ascii=False))
    pos = esp["respuesta"] + esp["entrevista"]
    print(f"espontáneas: {esp['enviadas']} enviadas, {pos} respuestas/entrevistas ({100 * pos // max(esp['enviadas'], 1)}%), "
          f"{esp['rechazo']} rechazos")
    if not args.json:
        for dim in ("portal", "tipo", "categoria", "cv", "contacto"):
            for val, g in sorted(e.get(dim, {}).items(), key=lambda x: -x[1]["enviadas"]):
                pos = g["respuesta"] + g["entrevista"]
                print(f"{dim:9} {val:22} {g['enviadas']:4} enviadas  {pos:3} respuestas/entrevistas "
                      f"({100 * pos // max(g['enviadas'], 1)}%)  {g['rechazo']:3} rechazos")


def cfg_contactos(p: dict | None = None) -> dict:
    return {"encaje_minimo": 60, "seguimiento_dias": 12, "max_diario": 10, **((p or perfil()).get("contactos") or {})}


def contactos_pendientes(con, cfg: dict, hoy: date | None = None) -> dict:
    """A quién buscar contacto (enviadas con encaje alto sin contacto) y a quién escribir el seguimiento
    (sin respuesta a los seguimiento_dias, con contacto encontrado y sin seguimiento escrito)."""
    hoy = hoy or date.today()
    limite = date.fromordinal(hoy.toordinal() - cfg["seguimiento_dias"]).isoformat()
    campos = "id, semana, empresa, titulo, urls, portales, encaje, enviada, contacto, nota_contacto"
    contactar = con.execute(f"SELECT {campos} FROM ofertas WHERE estado IN ('enviada', 'silencio_14d') AND encaje >= ? AND contacto IS NULL "
                            "ORDER BY enviada DESC, encaje DESC LIMIT ?", (cfg["encaje_minimo"], cfg["max_diario"])).fetchall()
    seguir = con.execute(f"SELECT {campos} FROM ofertas WHERE estado IN ('enviada', 'silencio_14d') AND encaje >= ? "
                         "AND contacto IS NOT NULL AND contacto != 'no encontrado' AND seguimiento IS NULL AND enviada <= ? "
                         "AND contacto_fecha < ? ORDER BY enviada", (cfg["encaje_minimo"], limite, hoy.isoformat())).fetchall()
    fmt = lambda o: {**{k: o[k] for k in ("id", "empresa", "titulo", "encaje", "enviada", "contacto", "nota_contacto")},
                     "urls": json.loads(o["urls"] or "[]"), "portales": json.loads(o["portales"] or "[]"),
                     "adaptacion": str(db.OUTPUT / o["semana"] / o["id"] / "adaptacion.json")}
    return {"contactar": [fmt(o) for o in contactar], "seguir": [fmt(o) for o in seguir]}


def cmd_contactos(args):
    con = db.conectar()
    if args.hoy:   # textos generados hoy, para el email de resumen (los envía el candidato a mano)
        filas = con.execute("SELECT id, empresa, titulo, contacto, nota_contacto, seguimiento FROM ofertas "
                            "WHERE contacto_fecha = ? AND contacto != 'no encontrado'", (date.today().isoformat(),))
        print(json.dumps([dict(f) for f in filas], ensure_ascii=False, indent=1))
        return
    print(json.dumps(contactos_pendientes(con, cfg_contactos()), ensure_ascii=False, indent=1))


MAX_NOTA = 300   # límite de la nota de invitación de LinkedIn


def cmd_contacto(args):
    """Guarda la persona y la nota de conexión (o el mensaje de seguimiento) de una oferta. Nunca envía nada."""
    con = db.conectar()
    if not con.execute("SELECT 1 FROM ofertas WHERE id = ?", (args.id,)).fetchone():
        raise SystemExit(f"No existe la oferta {args.id}")
    for nombre, texto in (("nota", args.nota), ("seguimiento", args.seguimiento)):
        if texto and len(texto) > MAX_NOTA:
            raise SystemExit(f"{nombre} de {len(texto)} caracteres: máximo {MAX_NOTA}. Recórtala.")
        if texto and re.search("[—–]", texto):
            raise SystemExit(f"{nombre} con guiones largos o medios: quítalos.")
    cambios = {"contacto": args.persona, "nota_contacto": args.nota, "seguimiento": args.seguimiento}
    cambios = {k: v for k, v in cambios.items() if v}
    if not cambios:
        raise SystemExit("Nada que guardar: usa --persona, --nota o --seguimiento")
    cambios["contacto_fecha"] = date.today().isoformat()
    con.execute(f"UPDATE ofertas SET {', '.join(f'{k} = ?' for k in cambios)} WHERE id = ?", [*cambios.values(), args.id])
    con.commit()
    print(f"{args.id}: {', '.join(cambios)} guardado")


def cmd_modo(args):
    m = modos()
    print(json.dumps({**m, "db": str(db.RUTA), "empresas_csv": str(db.EMPRESAS), "output": str(db.OUTPUT)}, ensure_ascii=False))


def cmd_huella(args):
    print(json.dumps(db.huella(Path(args.ruta) if args.ruta else None), ensure_ascii=False))


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
    s.add_argument("--json", action="store_true", help="JSON compacto (id, encaje, empresa, título, portales...)")
    s.add_argument("--completo", action="store_true", help="Con --json, todas las columnas (texto incluido)")
    s.set_defaults(fn=cmd_listar)

    s = sub.add_parser("oferta", help="Detalle completo de una oferta")
    s.add_argument("id")
    s.add_argument("--campos", help="Solo estos campos, separados por comas (p. ej. titulo,texto,requisitos)")
    s.set_defaults(fn=cmd_oferta)

    s = sub.add_parser("estado")
    s.add_argument("id"); s.add_argument("estado", choices=db.ESTADOS); s.add_argument("--nota")
    s.set_defaults(fn=cmd_estado)

    s = sub.add_parser("cv", help="Genera el CV del candidato para una oferta (o 'base')")
    s.add_argument("id", help="ID de oferta o 'base'")
    s.add_argument("adaptacion", nargs="?", help="JSON de adaptación (obligatorio salvo con 'base')")
    s.set_defaults(fn=cmd_cv)

    s = sub.add_parser("preparar", help="Copia el CV a output/SUBIR/<id>/ y muestra datos para postular")
    s.add_argument("id")
    s.add_argument("--sin-perfil", action="store_true", help="Sin candidato/respuestas (pídelos una vez con perfil-formulario)")
    s.set_defaults(fn=cmd_preparar)

    s = sub.add_parser("perfil-formulario", help="Datos del candidato y respuestas fijas para formularios (una vez por sesión)")
    s.set_defaults(fn=cmd_perfil_formulario)

    s = sub.add_parser("enviada", help="Marca enviada y la registra en candidaturas-sync si hace falta")
    s.add_argument("id")
    s.add_argument("--origen", required=True, help="LinkedIn, InfoJobs, Tecnoempleo, Web empresa...")
    s.set_defaults(fn=cmd_enviada)

    s = sub.add_parser("excel", help="Importa cambios manuales y regenera el Excel semanal")
    s.add_argument("--semana", help="AAAA-Www (por defecto la actual)")
    s.set_defaults(fn=cmd_excel)

    s = sub.add_parser("resumen"); s.add_argument("--errores"); s.set_defaults(fn=cmd_resumen)

    s = sub.add_parser("pendientes", help="Trabajo pendiente hoy y cupos (lo usa src.diario para saltar fases vacías)")
    s.set_defaults(fn=cmd_pendientes)
    s = sub.add_parser("espontaneas-consulta", help="Solo lectura: CSV de espontáneas (filas, envíos de hoy) y, con "
                       "--empresa/--dominio, coincidencias en candidaturas.xlsx. Error explícito si falta o no se lee un archivo")
    s.add_argument("--empresa"); s.add_argument("--dominio")
    s.add_argument("--csv", help="Otro CSV (por defecto el de espontáneas activo)")
    s.add_argument("--excel", help="Otro candidaturas.xlsx (por defecto el de candidaturas_sync)")
    s.set_defaults(fn=cmd_espontaneas_consulta)
    s = sub.add_parser("perfiles", help="Solo lectura: perfiles de candidatura (cuándo aplica cada uno, asunto y CV fijo)")
    s.set_defaults(fn=cmd_perfiles)
    s = sub.add_parser("espontaneas-informe", help="Solo lectura: resultados de las espontáneas por categoría, destinatario, "
                       "sector, tecnología y semana (el Excel es la fuente de respuestas)")
    s.add_argument("--csv"); s.add_argument("--excel"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_espontaneas_informe)
    s = sub.add_parser("depurar", help="Descarta de las ofertas nuevas lo que no pasa el filtro de calidad")
    s.add_argument("--simular", action="store_true")
    s.add_argument("--incluir-adaptadas", action="store_true", help="también las que ya tienen CV adaptado")
    s.set_defaults(fn=cmd_depurar)
    s = sub.add_parser("resultados", help="Respuestas/rechazos desde candidaturas.xlsx, silencios y embudo")
    s.add_argument("--simular", action="store_true", help="Muestra los cambios sin guardarlos")
    s.add_argument("--json", action="store_true", help="Embudo completo en JSON"); s.set_defaults(fn=cmd_resultados)
    s = sub.add_parser("contactos", help="Pendientes de contacto y de seguimiento (JSON)")
    s.add_argument("--hoy", action="store_true", help="Textos generados hoy (para el email)"); s.set_defaults(fn=cmd_contactos)
    s = sub.add_parser("contacto", help="Guarda persona, nota de conexión o seguimiento (máx. 300 caracteres)")
    s.add_argument("id"); s.add_argument("--persona", help="'Nombre | cargo | url' o 'no encontrado'")
    s.add_argument("--nota"); s.add_argument("--seguimiento"); s.set_defaults(fn=cmd_contacto)
    s = sub.add_parser("modo", help="Modos de envío efectivos y rutas (en JOB_AGENTS_PRUEBA=1: revision/borrador)")
    s.set_defaults(fn=cmd_modo)
    s = sub.add_parser("huella", help="Huella de solo lectura del histórico (integridad, conteos, hash)")
    s.add_argument("--ruta", help="Otra base SQLite (por defecto la activa)")
    s.set_defaults(fn=cmd_huella)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
