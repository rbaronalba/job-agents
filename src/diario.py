"""Ejecución diaria con una sesión de Claude por fase (el contexto de una fase no se arrastra a la siguiente).

  python -m src.diario [--fases buscar,adaptar,...] [--lote 5] [--max-ofertas N] [--prueba] [--simular]

Fases, en orden: buscar, adaptar, postular (lotes de --lote ofertas, una sesión por lote), espontaneas,
seguimiento (candidaturas-sync), resumen (Excel, resumen y email). Antes de cada fase se consulta
`src.cli pendientes`: si no hay trabajo, la fase no arranca. Si una fase choca con el límite de uso,
no se lanzan las siguientes. Cada resultado (JSON de `claude -p`) queda en logs/diario/<fecha>/.

--prueba    JOB_AGENTS_PRUEBA=1 sobre una copia del histórico en data/tmp/prueba/: nada se envía
            (portales en revision, espontáneas en borrador), no se ejecuta el seguimiento ni se envía el email.
--simular   No lanza Claude ni escribe resultados: muestra qué fases y lotes se ejecutarían (con --prueba,
            sobre la copia).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from . import db

FASES = ["buscar", "adaptar", "postular", "espontaneas", "seguimiento", "resumen"]
# Las mismas herramientas que permitía diario.bat para la sesión única
HERRAMIENTAS = ("Read,Write,Edit,Glob,Grep,ToolSearch,Agent,Task,WebSearch,WebFetch,mcp__claude-in-chrome,"
                "mcp__claude_ai_Gmail,mcp__claude_ai_Composio,Bash(python -m src.cli:*),Bash(python -m candidaturas:*),"
                "Bash(cd:*),Bash(mkdir:*)")
DESATENDIDA = ("Ejecucion desatendida: nadie puede responder, no hagas preguntas; si falta algo, anotalo y sigue. "
               "Termina con una linea ESTADO_FASE: ok, vacio, sin_chrome o error.")
PRUEBA = " MODO PRUEBA: no envies candidaturas, formularios ni correos."
# El postulador no necesita el perfil (sus datos llegan por src.cli perfil-formulario): sin acceso, no puede
# "recuperar" el modo de él ni editarlo si un comando falla
SIN_PERFIL = "Read(config/profile.yaml),Edit(config/profile.yaml),Write(config/profile.yaml)"
LIMITE = re.compile(r"hit your limit|usage limit|limite de uso", re.I)


_ESTADO = re.compile(r"ESTADO_FASE\W*(ok|vacio|vacia|sin_chrome|error)\b", re.I)


def estado_de(texto: str) -> str | None:
    """Último ESTADO_FASE válido del texto, tolerando Markdown (**error**, `ok`); un valor desconocido no cuenta."""
    marcas = _ESTADO.findall(texto or "")
    return marcas[-1].lower() if marcas else None


def _seguro(texto: str) -> str:
    # claude es un .CMD en Windows: los argumentos pasan por cmd.exe
    if re.search(r'[\r\n"%&|<>^]', texto):
        raise ValueError(f"Argumento no seguro para cmd.exe: {texto!r}")
    return texto


class Diario:
    def __init__(self, a):
        self.a = a
        self.fases: list[dict] = []
        self.parar = False
        self.chrome = True
        base = db.RAIZ / "data" / "tmp" / "prueba" if a.prueba else db.RAIZ
        self.dir_logs = base / "logs" / "diario" / f"{datetime.now():%Y-%m-%d_%H%M%S}"
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if a.prueba:
            # Copia nueva en cada ensayo: el histórico y el CSV reales nunca se abren en escritura
            copia = db.RAIZ / "data" / "tmp" / "prueba" / "historico.sqlite"
            copia.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a.origen_db, copia)
            csv_real = db.RAIZ / "data" / "empresas.csv"
            if csv_real.exists():
                shutil.copy2(csv_real, copia.parent / "empresas.csv")
            self.env.update(JOB_AGENTS_PRUEBA="1", JOB_AGENTS_DB=str(copia))

    # --- utilidades -------------------------------------------------------------------------------------------------
    def cli(self, *args) -> str:
        r = subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=db.RAIZ, env=self.env,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            raise RuntimeError(f"src.cli {' '.join(args)}: {(r.stderr or r.stdout).strip()[-300:]}")
        return r.stdout

    def pendientes(self) -> dict:
        return json.loads(self.cli("pendientes"))

    def registrar(self, fase: str, estado: str, detalle: str = "", **extra):
        self.fases.append({"fase": fase, "estado": estado, "detalle": detalle[:300], **extra})
        print(f"[{datetime.now():%H:%M:%S}] {fase:12} {estado:10} {detalle[:150]}", flush=True)

    def claude(self, fase: str, prompt: str, chrome=False, cwd: Path | None = None, prohibidas: str = "") -> dict:
        prompt = _seguro(f"{prompt} {DESATENDIDA}{PRUEBA if self.a.prueba else ''}")
        cmd = [shutil.which("claude") or "claude", "-p", prompt, "--output-format", "json",
               "--allowedTools", HERRAMIENTAS] + (["--chrome"] if chrome else []) \
            + (["--disallowedTools", prohibidas] if prohibidas else [])
        if self.a.simular:
            self.registrar(fase, "simulado", prompt.split(" Ejecucion")[0])
            return {"estado": "ok"}
        inicio = time.time()
        try:
            # stdin cerrado: sin él, claude -p espera 3 s a datos por stdin en cada sesión
            r = subprocess.run(cmd, cwd=cwd or db.RAIZ, env=self.env, stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, encoding="utf-8", timeout=self.a.timeout)
            salida = r.stdout
        except subprocess.TimeoutExpired:
            self.registrar(fase, "timeout", f"más de {self.a.timeout}s")
            return {"estado": "timeout"}
        try:
            res = json.loads(salida)
        except ValueError:   # salida no JSON: se guarda tal cual para no perder el error
            res = {"result": None, "is_error": True, "subtype": "salida_no_json", "salida": salida[-2000:]}
        texto = str(res.get("result") or "")
        errores = [str(e) for e in res.get("errors") or []]
        diagnostico = {"codigo_salida": r.returncode, "is_error": res.get("is_error"), "subtype": res.get("subtype"),
                       "errors": errores, "stderr": (r.stderr or "")[-1000:] or None}
        res["_diagnostico"] = diagnostico
        estado = estado_de(texto) or ("error" if res.get("is_error") or r.returncode else "ok")
        if any(LIMITE.search(t) for t in (texto, r.stderr or "", *errores)):
            estado, self.parar = "limite", True
        if estado == "sin_chrome":
            self.chrome = False
        self.dir_logs.mkdir(parents=True, exist_ok=True)
        n = sum(1 for f in self.fases if f["fase"] == fase) + 1
        (self.dir_logs / f"{len(self.fases) + 1:02d}-{fase}-{n}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        # Sin resultado útil, el detalle es el error: errors del CLI, si no stderr, si no la salida en bruto
        util = texto or "; ".join(errores) or diagnostico["stderr"] or res.get("salida") or f"código de salida {r.returncode}"
        resumen = re.sub(r"\s+", " ", util.replace("ESTADO_FASE:", ""))[-300:]
        self.registrar(fase, estado, resumen, session_id=res.get("session_id"), turnos=res.get("num_turns"),
                       segundos=round(time.time() - inicio), coste_usd=res.get("total_cost_usd"), texto=util[-1500:],
                       **diagnostico)
        return {"estado": estado}

    def activa(self, fase: str) -> bool:
        if fase not in self.a.fases:
            return False
        if self.parar:
            self.registrar(fase, "omitida", "límite de uso alcanzado en una fase anterior")
            return False
        return True

    # --- fases ------------------------------------------------------------------------------------------------------
    def buscar(self):
        if self.activa("buscar"):
            self.claude("buscar", "/buscar")

    def adaptar(self):
        if not self.activa("adaptar"):
            return
        nuevas = self.pendientes()["nuevas"]
        if not nuevas:
            return self.registrar("adaptar", "vacia", "no hay ofertas nuevas")
        self.claude("adaptar", "/adaptar")

    def modo_valido(self, fase: str) -> bool:
        """Antes de una fase que puede enviar: si no se puede obtener el modo efectivo, la fase no arranca."""
        try:
            m = json.loads(self.cli("modo"))
            assert m["portales"] in ("revision", "auto") and m["espontaneas"] in ("borrador", "auto"), m
            if self.a.prueba:
                assert m["prueba"] and m["portales"] == "revision" and m["espontaneas"] == "borrador", m
            return True
        except Exception as e:   # noqa: BLE001 - cualquier fallo de modo detiene la fase
            self.registrar(fase, "error", f"src.cli modo falló, la fase no se ejecuta: {e}")
            return False

    def postular(self):
        if not self.activa("postular") or not self.modo_valido("postular"):
            return
        intentadas: list[str] = []
        while not self.parar and self.chrome:
            p = self.pendientes()
            cupo = p["cupo_portales"]
            if self.a.max_ofertas is not None:
                cupo = max(0, min(cupo, self.a.max_ofertas - len(intentadas)))
            # Las que siguen en cv_adaptado tras su lote (falló algo) no se reintentan hoy
            lote = [i for i in p["cv_adaptado"] if i not in intentadas][:min(self.a.lote, cupo)]
            if not lote:
                if not intentadas:
                    motivo = "sin cupo hoy" if p["cv_adaptado"] else "no hay CVs adaptados"
                    self.registrar("postular", "vacia", f"{motivo} ({len(p['cv_adaptado'])} en cola, cupo {p['cupo_portales']})")
                return
            intentadas += lote
            if self.claude("postular", "/postular " + " ".join(lote), chrome=True,
                           prohibidas=SIN_PERFIL)["estado"] in ("error", "timeout"):
                return   # una tanda fallida (p. ej. modo o preparar fallaron) detiene la fase: no se lanzan más lotes

    def espontaneas(self):
        if not self.activa("espontaneas") or not self.modo_valido("espontaneas"):
            return
        if not self.chrome:
            return self.registrar("espontaneas", "omitida", "Chrome no disponible en postular")
        cupo = self.pendientes()["cupo_espontaneas"]
        if self.a.max_ofertas is not None:
            cupo = min(cupo, self.a.max_ofertas)
        if not cupo:
            return self.registrar("espontaneas", "vacia", "objetivo diario cubierto")
        self.claude("espontaneas", f"/espontaneas {cupo}", chrome=True)

    def seguimiento(self):
        if not self.activa("seguimiento"):
            return
        carpeta = self.pendientes()["candidaturas_sync"]
        if not carpeta:
            return self.registrar("seguimiento", "vacia", "candidaturas_sync no configurado")
        if self.a.prueba:
            return self.registrar("seguimiento", "omitida", "modo prueba: no se toca candidaturas.xlsx")
        # Desde la raíz del proyecto (no desde la carpeta de candidaturas-sync): solo aquí existe el subagente correo,
        # único con Gmail en claude -p
        c = Path(carpeta).as_posix()
        self.claude("seguimiento", f"Sigue el procedimiento de {c}/.claude/commands/revisar.md en modo sin Google Cloud "
                    f"(lee antes {c}/CLAUDE.md). Ejecuta sus comandos python -m candidaturas desde esa carpeta "
                    f"(cd {c} y despues el comando). Toda operacion de Gmail (buscar o leer hilos) pidesela al subagente "
                    "correo con la consulta exacta y los campos que necesites: tu no tienes Gmail.")

    def resumen(self):
        if "resumen" not in self.a.fases:
            return
        errores = "; ".join(f"{f['fase']}: {f['estado']} {f['detalle'][:120]}" for f in self.fases
                            if f["estado"] not in ("ok", "vacia", "vacio", "simulado")) or "ninguno"
        if self.a.simular:
            return self.registrar("resumen", "simulado", f"excel + resumen --errores ({errores[:100]}) + email")
        try:
            self.cli("excel")
        except RuntimeError as e:   # p. ej. Excel abierto: se anota y sigue
            errores += f"; excel: {e}"
        texto = self.cli("resumen", "--errores", errores)
        if self.a.prueba:
            return self.registrar("resumen", "ok", "modo prueba: email de resumen no enviado")
        if self.parar:
            return self.registrar("resumen", "omitida", "email no enviado: límite de uso")
        p = self.pendientes()
        # El contenido va en un archivo: por línea de comandos solo pasa una instrucción corta y segura
        self.dir_logs.mkdir(parents=True, exist_ok=True)
        datos = self.dir_logs / "email_resumen.md"
        datos.write_text("\n".join([
            f"Asunto: job-agents | resumen {date.today().isoformat()}",
            "Destinatario: el candidato. Lo fija el subagente correo (candidato.email): no lo busques tú.",
            "Cuerpo en texto plano, 15 líneas como máximo: ofertas nuevas, candidaturas enviadas (empresa y puesto), "
            "espontáneas enviadas (empresa), respuestas recibidas de empresas, pendientes que necesitan al candidato "
            "(pregunta o motivo) y errores.", "", "## Resumen", texto,
            "## Enviadas hoy por portales", *p["enviadas_hoy"], "## Espontáneas de hoy", *p["espontaneas_hoy"],
            "## Resultado de cada fase", *(f"- {f['fase']} ({f['estado']}): {f.get('texto', f['detalle'])[-800:]}" for f in self.fases),
        ]), encoding="utf-8")
        ruta = _seguro(datos.relative_to(db.RAIZ).as_posix())
        self.claude("email", f"Lee {ruta}, redacta el correo tal y como indica y pide al subagente correo que lo envie "
                    "(operacion enviar, resumen diario): tu no tienes Gmail.")

    def ejecutar(self) -> int:
        for fase in (self.buscar, self.adaptar, self.postular, self.espontaneas, self.seguimiento, self.resumen):
            try:
                fase()
            except Exception as e:   # una fase rota no tumba las demás (como en /diario)
                self.registrar(fase.__name__, "error", str(e))
        if not self.a.simular:
            self.dir_logs.mkdir(parents=True, exist_ok=True)
            (self.dir_logs / "diario.json").write_text(json.dumps(self.fases, ensure_ascii=False, indent=1), encoding="utf-8")
        malas = [f for f in self.fases if f["estado"] in ("error", "timeout", "limite")]
        print(f"Fases: {len(self.fases)}, con problemas: {len(malas)}")
        return 1 if malas else 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m src.diario", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fases", default=",".join(FASES), help="Subconjunto separado por comas")
    p.add_argument("--lote", type=int, default=5, help="Ofertas por sesión de postular")
    p.add_argument("--max-ofertas", type=int, help="Tope de ofertas a postular y de espontáneas (para ensayos)")
    p.add_argument("--timeout", type=int, default=3600, help="Segundos máximos por sesión de Claude")
    p.add_argument("--prueba", action="store_true")
    p.add_argument("--simular", action="store_true")
    p.add_argument("--origen-db", type=Path, default=db.RUTA, help="Histórico que se copia en --prueba")
    a = p.parse_args(argv)
    a.fases = [f.strip() for f in a.fases.split(",")]
    if desconocidas := set(a.fases) - set(FASES):
        p.error(f"Fases desconocidas: {desconocidas}")
    if db.PRUEBA and not a.prueba:
        p.error("JOB_AGENTS_PRUEBA=1 en el entorno: usa --prueba")
    sys.exit(Diario(a).ejecutar())


if __name__ == "__main__":
    main()
