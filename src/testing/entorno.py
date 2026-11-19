"""Apoyo de las pruebas: entorno aislado, constructores de datos, ejecutores y dobles. Sin asserts: los tests solo comprueban.

Nada de esto toca el histórico, el perfil ni los CV reales: todo va a carpetas temporales (JOB_AGENTS_DATOS, JOB_AGENTS_PERFIL).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml
from openpyxl import Workbook, load_workbook

from .. import db

FALSO = Path(__file__).with_name("falso.py")
CABECERA_CSV = "empresa,web,email,ciudad,sector,notas,estado,fecha\n"
CABECERA_CLASIFICADA = CABECERA_CSV.strip() + ",categoria,compatibilidad,senal,destinatario,tecnologias\n"
HOY_FIJO = date(2026, 11, 17)


# --- entorno -------------------------------------------------------------------------------------------------------
def entorno(**extra) -> dict:
    """Entorno heredado sin variables JOB_AGENTS_* ajenas, más las indicadas (las None se omiten)."""
    heredado = {k: v for k, v in os.environ.items() if not k.startswith("JOB_AGENTS_")}
    return {**heredado, "PYTHONIOENCODING": "utf-8", **{k: str(v) for k, v in extra.items() if v is not None}}


def perfil_fijo(destino: Path) -> Path:
    """Perfil de ejemplo con cupos conocidos (30 en total, 15 por portales, 12 espontáneas al día)."""
    p = yaml.safe_load((db.RAIZ / "config" / "profile.example.yaml").read_text(encoding="utf-8"))
    p.setdefault("encaje", {})["minimo_postular"] = 55
    p["envio"].update(max_diario_total=30, max_diario_portales=15, espontaneas_max_diario=15, espontaneas_objetivo_diario=12)
    destino.write_text(yaml.safe_dump(p, allow_unicode=True), encoding="utf-8")
    return destino


# --- datos ---------------------------------------------------------------------------------------------------------
OFERTAS_BASE = [("A", "Front Angular", 80, "nueva"), ("B", "React Dev", 60, "nueva"), ("C", "Full Stack", 70, "cv_adaptado"),
                ("D", "Angular", 90, "cv_adaptado"), ("E", "Vue", 50, "enviada")]


def crear_base(carpeta: Path) -> Path:
    """Histórico sintético de 5 ofertas (2 nuevas, 2 con CV adaptado, 1 enviada)."""
    ruta = carpeta / "h.sqlite"
    con = db.conectar(ruta)
    for i, (emp, tit, enc, est) in enumerate(OFERTAS_BASE):
        db.guardar(con, {"empresa": emp, "titulo": tit, "encaje": enc, "estado": est, "texto": "x" * 2000,
                         "requisitos": ["Angular"], "urls": [f"https://e/{i}"], "portales": ["linkedin"], "justificacion": "j",
                         "tipo_candidatura": "easy_apply", "fecha_pub": f"2026-11-0{i + 1}"})
    con.commit()
    con.close()
    return ruta


def ids_por_estado(base: Path, estado: str) -> list[str]:
    con = db.conectar(base)
    try:
        return [r[0] for r in con.execute("SELECT id FROM ofertas WHERE estado = ? ORDER BY encaje DESC", (estado,))]
    finally:
        con.close()


def oferta_con_cv(base: Path) -> tuple[str, str]:
    """(id, semana) de la oferta con CV adaptado de mayor encaje."""
    con = db.conectar(base)
    try:
        return tuple(con.execute("SELECT id, semana FROM ofertas WHERE estado = 'cv_adaptado' ORDER BY encaje DESC").fetchone())
    finally:
        con.close()


def marcar_enviada_hoy(base: Path, oid: str) -> None:
    con = db.conectar(base)
    db.cambiar_estado(con, oid, "enviada")
    con.commit()
    con.close()


def enviadas(con, empresas: list[str], dias: int = 30, encaje: int = 90) -> dict[str, str]:
    """Una candidatura enviada hace `dias` por cada empresa. Devuelve {empresa: id}."""
    hace = (HOY_FIJO - timedelta(days=dias)).isoformat()
    ids = {}
    for e in empresas:
        ids[e], _ = db.guardar(con, {"empresa": e, "titulo": "Dev", "ids_externos": [f"li:{e}"]})
        con.execute("UPDATE ofertas SET estado='enviada', enviada=?, encaje=? WHERE id=?", (hace, encaje, ids[e]))
    return ids


def escenario_contactos(con) -> dict[str, str]:
    """Seis candidaturas enviadas con distinto encaje y fecha: Rech, Entr, Calla, Nueva, Baja (encaje 40) y Seguir."""
    ids = {}
    for emp, enc, env in (("Rech", 80, "2026-11-10"), ("Entr", 80, "2026-11-10"), ("Calla", 80, "2026-11-01"),
                          ("Nueva", 70, "2026-11-15"), ("Baja", 40, "2026-11-15"), ("Seguir", 90, "2026-11-03")):
        ids[emp], _ = db.guardar(con, {"empresa": emp, "titulo": "Frontend", "encaje": enc, "ids_externos": [f"li:{emp}"]})
        con.execute("UPDATE ofertas SET estado = 'enviada', enviada = ? WHERE id = ?", (env, ids[emp]))
    return ids


def fila(**campos) -> dict:
    """Fila de empresas.csv de una empresa pendiente en el primer anillo (Alfa)."""
    return {"empresa": "X", "estado": "pendiente", "ciudad": "Alfa", **campos}


CLASIFICACION_VALIDA = dict(categoria="B", compatibilidad="media", senal="sin_vacante_publicada", destinatario="empleo")
ANILLOS = [["Alfa"], ["Beta", "Gamma"], ["Delta"]]


def filas_de_la_cola() -> list[dict]:
    """Diez filas con todos los casos que ordena o descarta la cola de espontáneas (con el anillo actual = 1)."""
    base = dict(compatibilidad="alta", senal="necesidad_potencial", destinatario="rrhh")
    return [fila(empresa="sinclas"), fila(empresa="C-cor", categoria="C", **base),
            fila(empresa="B-sev", categoria="B", ciudad="Beta", **base), fila(empresa="B-cor", categoria="B", **base),
            fila(empresa="A-sev", categoria="A", ciudad="Gamma", **{**base, "senal": "vacante_confirmada"}),
            fila(empresa="D", categoria="D", **base), fila(empresa="baja", categoria="B", **{**base, "compatibilidad": "baja"}),
            fila(empresa="lejos", categoria="A", ciudad="Delta", **base), fila(empresa="env", estado="enviada"),
            fila(empresa="ret", estado="retenida")]


def envios_para_el_informe() -> list[dict]:
    """Doce enviadas (E0..E11) más una pendiente."""
    envs = [fila(empresa=f"E{i}", estado="enviada", fecha="2026-11-02", categoria="B", destinatario="general",
                 tecnologias="TecX; TecY") for i in range(12)]
    return envs + [fila(empresa="pend")]


def resultados_del_informe() -> dict:
    """E0 entrevista, E1 rechazo, el resto sin respuesta; E11 sin fila en el Excel."""
    return {f"E{i}": r for i, r in enumerate(["entrevista", "rechazo", None] + [None] * 8)}


def cv_ejemplo(**es) -> dict:
    return {"es": {"titular": "Dev | X", **es}, "en": {"titular": "Dev EN | X"}}


def csv_antiguo(ruta: Path) -> Path:
    """empresas.csv de 8 columnas (sin clasificar)."""
    return csv_empresas(ruta, ["Acme,https://a.es,rrhh@a.es,Alfa,Software,,pendiente,", "Beta,https://b.es,info@b.es,Alfa,Software,,retenida,2026-01-01"])


def csv_clasificado(ruta: Path) -> Path:
    """El mismo CSV con las columnas de clasificación; Acme es categoría A sin vacante confirmada (incoherente)."""
    return csv_empresas(ruta, ["Acme,https://a.es,rrhh@a.es,Alfa,Software,,pendiente,,A,alta,sin_evidencia,rrhh,",
                               "Beta,https://b.es,info@b.es,Alfa,Software,,retenida,2026-01-01,,,,,"],
                        cabecera=CABECERA_CSV.strip() + ",categoria,compatibilidad,senal,destinatario,tecnologias\n")


def csv_de_envios(ruta: Path) -> Path:
    """CSV con tres espontáneas enviadas (Acme, AcmeSoft, Beta) y una pendiente."""
    return csv_empresas(ruta, ["Acme,https://a.es,rrhh@a.es,Alfa,Software,,enviada,2026-11-02,B,media,sin_vacante_publicada,general,Angular",
                               "AcmeSoft,https://s.es,rrhh@s.es,Alfa,Software,,enviada,2026-11-03,B,media,sin_vacante_publicada,general,Vue",
                               "Beta,https://b.es,rrhh@b.es,Alfa,Datos,,enviada,2026-11-04,C,alta,sin_vacante_publicada,rrhh,Python",
                               "Zeta,https://z.es,rrhh@z.es,Alfa,Datos,,pendiente,,,,,,"], cabecera=CABECERA_CLASIFICADA)


def excel_de_resultados(ruta: Path) -> Path:
    """candidaturas.xlsx: Acme rechazó (dos filas, una sin resultado), AcmeSoft dio entrevista y una fila no es espontánea."""
    esp = "Candidatura espontánea"
    return xlsx(ruta, "Candidaturas", [["Empresa", "Puesto", "Fase", "Notas"], ["Acme", esp, "Rechazado", None], ["Acme", esp, "Enviada", None],
                                       ["AcmeSoft", esp, "En curso", "entrevista el lunes"], ["Otra", "Frontend", "Rechazado", None]])


def csv_ilegible(ruta: Path) -> Path:
    """Un CSV que no es UTF-8 válido."""
    ruta.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x20, 0x80]))
    return ruta


def csv_empresas(ruta: Path, filas: list[str], cabecera: str = CABECERA_CSV) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(cabecera + "".join(f + "\n" for f in filas), encoding="utf-8")
    return ruta


def texto(ruta: Path, contenido: str) -> Path:
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def xlsx(ruta: Path, hoja: str, filas: list[list]) -> Path:
    wb = Workbook()
    wb.active.title = hoja
    for f in filas:
        wb.active.append(f)
    wb.save(ruta)
    return ruta


def editar_excel(ruta: Path, columna: str, fila: int, valor) -> None:
    """Cambia a mano una celda del Excel de ofertas (como haría el candidato)."""
    from .. import excel
    wb = load_workbook(ruta)
    wb[excel.HOJA].cell(row=fila, column=excel.CAB.index(columna) + 1).value = valor   # cell(value=None) no borra
    wb.save(ruta)


def celda_excel(ruta: Path, columna: str, fila: int):
    from .. import excel
    return load_workbook(ruta)[excel.HOJA].cell(row=fila, column=excel.CAB.index(columna) + 1).value


def sello(rutas: list[Path]) -> list:
    """(nombre, SHA-256, mtime) de archivos: para comprobar que algo no se tocó."""
    return [(p.name, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in rutas]


def sello_arbol(raiz: Path) -> list:
    return sorted((str(p), p.stat().st_mtime_ns) for p in raiz.rglob("*"))


def fases_lanzadas(llamadas: list[dict]) -> list[str]:
    """['/buscar', '/adaptar', ...]: primera palabra del prompt de cada sesión de Claude."""
    return [l["argv"][1].split()[0] for l in llamadas]


def lotes_lanzados(llamadas: list[dict]) -> list[list[str]]:
    """[['/postular', 'id1'], ...]: las dos primeras palabras del prompt de cada sesión."""
    return [l["argv"][1].split()[:2] for l in llamadas]


def con_chrome(llamadas: list[dict]) -> list[bool]:
    return ["--chrome" in l["argv"] for l in llamadas]


def prompts(llamadas: list[dict]) -> list[str]:
    return [l["argv"][1] for l in llamadas]


def argumento(llamada: dict, opcion: str) -> str:
    """Valor que sigue a una opción en la línea de comandos de una sesión (p. ej. --disallowedTools)."""
    a = llamada["argv"]
    return a[a.index(opcion) + 1]


def gmail_en(permiso: str) -> set[str]:
    """Operaciones de Gmail (sin prefijo) que aparecen en una lista de permisos separada por comas."""
    prefijo = "mcp__claude_ai_Gmail__"
    return {p[len(prefijo):] for p in permiso.split(",") if p.startswith(prefijo)}


def menciones(permiso: str, texto: str) -> list[str]:
    """Permisos de la lista que contienen `texto` (vacío = ninguno)."""
    return [p for p in permiso.split(",") if texto in p]


def herramientas_de_agente(md: Path) -> set[str]:
    """Herramientas declaradas en la cabecera `tools:` de un agente .claude/agents/*.md."""
    linea = next(l for l in md.read_text(encoding="utf-8").splitlines() if l.startswith("tools: "))
    return set(linea[len("tools: "):].split(", "))


def respuestas_resumen(email: str) -> dict[str, str]:
    """Lo que devolvería src.cli en la fase de resumen para un candidato con ese email."""
    return {"modo": '{"portales": "auto", "espontaneas": "auto", "prueba": false}',
            "perfil-formulario": json.dumps({"candidato": {"email": email}}), "excel": "", "resumen": "r", "contactos": "[]"}


def excel_malo(carpeta: Path, tipo: str) -> Path:
    """Un candidaturas.xlsx que ya_postuladas debe rechazar: ausente, corrupto, sin la hoja o sin columnas."""
    if tipo == "ausente":
        return carpeta / "no.xlsx"
    if tipo == "corrupto":
        ruta = carpeta / "roto.xlsx"
        ruta.write_text("no es un xlsx", encoding="utf-8")
        return ruta
    if tipo == "sin_hoja":
        return xlsx(carpeta / "h.xlsx", "Otra", [])
    return xlsx(carpeta / "col.xlsx", "Candidaturas", [["Empresa"]])


def archivos_consulta(carpeta: Path) -> SimpleNamespace:
    """Excel de candidaturas y CSV de empresas de ejemplo, más un CSV sin columnas y Excels rotos, para espontaneas-consulta."""
    hoy = date.today().isoformat()
    return SimpleNamespace(
        carpeta=carpeta,
        xlsx=xlsx(carpeta / "candidaturas.xlsx", "Candidaturas", [
            ["Fecha", "Empresa", "Puesto", "Enlace", "Fase", "Días", "Origen", "Notas", "Ref"],
            [date(2026, 10, 1), "Acme Software S.L.", "Frontend", "https://www.acme.es/empleo", "Enviada", 3, "Espontánea", None, None],
            [date(2026, 10, 2), "Otra", "Angular", None, "Rechazado", 9, "LinkedIn", "contacto en rrhh@beta.io", "li:1"],
            [None] * 9]),
        csv=csv_empresas(carpeta / "empresas.csv", [f"A,,,,,,enviada,{hoy}", f"B,,,,,,borrador,{hoy}", "C,,,,,,enviada,2020-01-01",
                                                     "D,,,,,,pendiente,", "E,,,,,,,"]),
        csv_malo=texto(carpeta / "malo.csv", "nombre,correo\nX,y\n"),
        roto=excel_malo(carpeta, "corrupto"), sin_hoja=excel_malo(carpeta, "sin_hoja"), ausente=carpeta / "no.xlsx", csv_ausente=carpeta / "no.csv")


def nombres_de_agentes(carpeta: Path) -> list[str]:
    return sorted(p.stem for p in carpeta.glob("*.md"))


def usa_gmail_directamente(md: Path) -> bool:
    """¿El agente nombra herramientas de Gmail? (solo `correo` y `buscador` pueden: un subagente no delega en otro)."""
    import re
    return bool(re.search(r"mcp__claude_ai_Gmail|search_threads|create_draft|send_message|list_drafts|label_message",
                          md.read_text(encoding="utf-8")))


def json_de_fase(carpeta: Path, fase: str) -> dict:
    return json.loads(next(carpeta.glob(f"*-{fase}-*.json")).read_text(encoding="utf-8"))


def base_vacia(carpeta: Path) -> Path:
    ruta = carpeta / "vacia.sqlite"
    db.conectar(ruta).close()
    return ruta


def prompts_sin(llamadas: list[dict], texto: str) -> list[str]:
    """Los prompts que NO contienen `texto` (lista vacía = todos lo llevan)."""
    return [l["argv"][1][:40] for l in llamadas if texto not in l["argv"][1]]


def estados(fases: list[dict]) -> dict[str, str]:
    return {f["fase"]: f["estado"] for f in fases}


# --- ejecutores ----------------------------------------------------------------------------------------------------
class Sandbox:
    """Carpetas y variables de una prueba: datos de prueba y perfil propios, base sintética y `claude` falso."""

    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.datos = raiz / "datos"
        self.logs = raiz / "logs"
        self.perfil = perfil_fijo(raiz / "profile.yaml")
        self.base = crear_base(raiz)
        self.falso = raiz / "falso"
        self.falso.mkdir()
        self.registro = self.falso / "llamadas.jsonl"
        (self.falso / "claude.cmd").write_text(f'@"{sys.executable}" "{FALSO}" %*\r\n', encoding="utf-8")

    def activar_sync(self) -> Path:
        """Configura candidaturas_sync en el perfil con una carpeta `sync` (dentro de la raíz temporal) y la crea."""
        p = yaml.safe_load(self.perfil.read_text(encoding="utf-8"))
        p["candidaturas_sync"] = "sync"
        self.perfil.write_text(yaml.safe_dump(p, allow_unicode=True), encoding="utf-8")
        (self.raiz / "sync").mkdir(exist_ok=True)
        return self.raiz / "sync"

    def env(self, *, prueba=False, base=True, **extra) -> dict:
        return entorno(JOB_AGENTS_DATOS=self.datos, JOB_AGENTS_LOGS=self.logs, JOB_AGENTS_PERFIL=self.perfil, FALSO_LLAMADAS=self.registro,
                       JOB_AGENTS_DB=self.base if base is True else base or None,
                       JOB_AGENTS_PRUEBA="1" if prueba else None,
                       PATH=f"{self.falso}{os.pathsep}{os.environ['PATH']}", **extra)

    def cli(self, *args, prueba=False, base=True, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=db.RAIZ, capture_output=True, text=True,
                              encoding="utf-8", env=self.env(prueba=prueba, base=base, **extra))

    def json(self, *args, **kw):
        return json.loads(self.cli(*args, **kw).stdout)

    def diario(self, *args, stdin_abierto=False, base=False, **extra) -> tuple[str, list[dict]]:
        self.registro.unlink(missing_ok=True)
        p = subprocess.Popen([sys.executable, "-m", "src.diario", *args], cwd=db.RAIZ, env=self.env(base=base, **extra),
                             stdin=subprocess.PIPE if stdin_abierto else subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        salida = p.stdout.read()
        p.wait()
        return salida, self.llamadas()

    def diario_prueba(self, *args, **extra) -> tuple[str, list[dict]]:
        """Orquestador en modo prueba con su histórico y su CSV de empresas (vacío): independiente de los datos reales."""
        empresas = csv_empresas(self.datos.parent / "origen_empresas.csv", [])
        return self.diario("--prueba", "--origen-db", str(self.base), "--origen-empresas", str(empresas), *args, **extra)

    def diario_bat(self, **extra) -> list[dict]:
        self.registro.unlink(missing_ok=True)
        subprocess.run(["cmd", "/c", str(db.RAIZ / "diario.bat"), "--prueba", "--simular", "--origen-db", str(self.base)],
                       cwd=db.RAIZ, env=self.env(base=False, **extra), capture_output=True)
        return self.llamadas()

    def llamadas(self) -> list[dict]:
        if not self.registro.exists():
            return []
        return [json.loads(l) for l in self.registro.read_text(encoding="utf-8").splitlines()]

    def diario_real(self, *args, **extra) -> tuple[str, list[dict]]:
        """Orquestador sin --prueba, sobre la base sintética (con `claude` falso)."""
        return self.diario(*args, base=True, **extra)

    def ultima_ejecucion(self, prueba=True) -> tuple[list[dict], Path]:
        """(fases de diario.json, carpeta de logs) de la ejecución más reciente del orquestador."""
        raiz = self.datos / "logs" if prueba else self.logs
        carpeta = max((raiz / "diario").iterdir(), key=lambda p: p.stat().st_mtime)
        return json.loads((carpeta / "diario.json").read_text(encoding="utf-8")), carpeta


def args_diario(base: Path, *, prueba=False, fases=(), simular=False, lote=1, max_ofertas=None):
    """Argumentos de un Diario creado en proceso (como los que construye argparse)."""
    from argparse import Namespace
    return Namespace(prueba=prueba, simular=simular, timeout=60, fases=list(fases), origen_db=base, origen_empresas=None,
                     lote=lote, max_ofertas=max_ofertas)


def preparar_cv(carpeta: Path) -> Path:
    """cv_base.yaml (el de ejemplo, con un perfil `ia`) y profile.yaml (candidata Ana María López) en `carpeta`."""
    base = yaml.safe_load((db.RAIZ / "cv" / "cv_base.example.yaml").read_text(encoding="utf-8"))
    base["es"]["perfiles"] = {"ia": {"titular": "IA es | Datos"}}
    base["en"]["perfiles"] = {"ia": {"titular": "IA en | Data"}}
    (carpeta / "cv_base.yaml").write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    (carpeta / "profile.yaml").write_text(yaml.safe_dump({"candidato": {"nombre": "Ana María López"}}, allow_unicode=True), encoding="utf-8")
    return carpeta


def cambiar_cv_base(carpeta: Path, idioma: str, campo: str, valor) -> None:
    """Cambia un campo del cv_base.yaml de `carpeta` (el de preparar_cv)."""
    ruta = carpeta / "cv_base.yaml"
    base = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    base[idioma][campo] = valor
    ruta.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")


def candidaturas_falso(carpeta: Path) -> Path:
    """Paquete `candidaturas` de mentira: `python -m candidaturas ...` guarda sus argumentos en args.json y responde 'nueva ok'."""
    paquete = carpeta / "candidaturas"
    paquete.mkdir(parents=True, exist_ok=True)
    (paquete / "__init__.py").write_text("", encoding="utf-8")
    guion = ["import json, sys", "open('args.json', 'w').write(json.dumps(sys.argv[1:]))", "print('nueva ok')", ""]
    (paquete / "__main__.py").write_text("\n".join(guion), encoding="utf-8")
    return carpeta / "args.json"


def anadir_oferta(base: Path, **campos) -> str:
    """Inserta una oferta directamente (sin el filtro de calidad de `cli guardar`). Devuelve su id."""
    con = db.conectar(base)
    oid, _ = db.guardar(con, {"empresa": "X", "titulo": "Dev", **campos})
    con.commit()
    con.close()
    return oid


class Resultado:
    """Lo que dejó una invocación del CLI en proceso."""

    def __init__(self, salida: str, error: str, codigo: int):
        self.salida, self.error, self.codigo = salida, error, codigo
        self.texto = salida + error

    def json(self):
        return json.loads(self.salida)


class CliEnProceso:
    """Ejecuta `src.cli.main(argv)` en el proceso de la prueba, con stdin y salidas capturados y sin que un SystemExit la corte."""

    def __init__(self, monkeypatch, sandbox: "Sandbox", *, prueba: bool = False):
        from .. import cli, excel
        self.cli = cli
        for modulo, nombre, valor in ((db, "RUTA", sandbox.base), (db, "PRUEBA", prueba), (db, "OUTPUT", sandbox.datos / "output"),
                                      (db, "LOGS", sandbox.logs), (db, "EMPRESAS", sandbox.datos / "empresas.csv"),
                                      (db, "EXCEL", sandbox.datos / "ofertas"), (excel, "CARPETA", sandbox.datos / "ofertas"),
                                      (cli, "RAIZ", sandbox.raiz)):
            monkeypatch.setattr(modulo, nombre, valor)
        monkeypatch.setenv("JOB_AGENTS_PERFIL", str(sandbox.perfil))
        self.monkeypatch = monkeypatch

    def __call__(self, *args, entrada: str | None = None) -> Resultado:
        import contextlib
        import io
        salida, error, codigo = io.StringIO(), io.StringIO(), 0
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(entrada or ""))
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
            try:
                self.cli.main([str(a) for a in args])
            except SystemExit as e:
                codigo = e.code if isinstance(e.code, int) else 1
                error.write("" if isinstance(e.code, int) or e.code is None else str(e.code))
        return Resultado(salida.getvalue(), error.getvalue(), codigo)


# --- dobles --------------------------------------------------------------------------------------------------------
class Red:
    """Falso `ats._leer`: responde por trozo de URL y apunta las pedidas. Lo no registrado falla como un 404."""

    def __init__(self, monkeypatch, respuestas: dict | None = None):
        from .. import ats
        self.respuestas, self.pedidas = respuestas or {}, []
        monkeypatch.setattr(ats, "_leer", self)
        monkeypatch.setattr(ats.time, "sleep", lambda s: None)

    def __call__(self, url, timeout=0, limite=0):
        self.pedidas.append(url)
        for trozo, cuerpo in self.respuestas.items():
            if trozo in url:
                return cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
        raise OSError(f"404 {url}")


class CliFalso:
    """Falso `Diario.cli`: responde por subcomando; los de `fallan` lanzan RuntimeError, como un src.cli roto."""

    def __init__(self, respuestas: dict | None = None, fallan: tuple = ()):
        self.respuestas, self.fallan = respuestas or {}, fallan

    def __call__(self, *args):
        if args[0] in self.fallan:
            raise RuntimeError("perfil roto")
        return self.respuestas.get(args[0], "r")
