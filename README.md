# job-agents

Sistema de agentes de [Claude Code](https://claude.com/claude-code) que automatiza la búsqueda de empleo: busca ofertas, adapta tu CV a cada una, postula con Claude in Chrome y envía candidaturas espontáneas por Gmail.

No es una app que se ejecute sola: es un proyecto de Claude Code. Todo se dispara desde una conversación de Claude Code (terminal, VS Code o la app) con comandos (`/buscar`, `/adaptar`...).

## 0. Requisitos

- [Claude Code](https://claude.com/claude-code) instalado.
- Python 3.11+.
- Una cuenta con el conector de Gmail activado (para InfoJobs y candidaturas espontáneas) y, si vas a postular o enviar espontáneas, [Claude in Chrome](https://chromewebstore.google.com) conectado.
- Opcional: una cuenta Composio para el agente `buscador` (búsqueda en LinkedIn/Google Jobs).

## 1. Clona y abre el proyecto con Claude Code

```
git clone <url-del-repo>
cd job-agents
claude
```

## 2. Ejecuta `/configurar`

Es el único paso que de verdad necesitas. Desde la conversación de Claude Code:

```
/configurar
```

Te va a pedir que le pegues tu CV (texto o tu "Acerca de"/"Experiencia" de LinkedIn) y los datos que falten (contacto, puestos que buscas, ciudad, salario mínimo, nivel de inglés...). Con eso:

- Prepara el entorno: activa el hook de seguridad anti-datos-personales (`git config core.hooksPath githooks`), instala las dependencias de Python y el navegador de Playwright.
- Genera `config/profile.yaml` (tus criterios de búsqueda y candidatura) y `cv/cv_base.yaml` (tu CV maestro, hechos reales, nunca inventados).
- Genera y verifica los PDF de tu CV (`python -m src.cli cv base`).

Estos dos archivos nunca se suben a git (están en `.gitignore`): puedes escribir en ellos tus datos reales sin riesgo.

**Revisa a mano `cv/cv_base.yaml` antes de usarlo en candidaturas reales.** Lo redacta Claude a partir de lo que le pegaste, no es un documento verificado.

## 3. Úsalo

Comando a comando:

| Comando | Qué hace |
|---|---|
| `/buscar` | Busca ofertas nuevas en LinkedIn, Google Jobs y alertas de InfoJobs, las puntúa contra tu CV y las guarda. |
| `/adaptar` | Adapta tu CV (y carta si la piden) a cada oferta nueva. |
| `/postular` | Postula con Claude in Chrome a las ofertas con CV ya adaptado. Necesita Claude in Chrome conectado. |
| `/espontaneas` | Busca empresas y envía candidaturas espontáneas por Gmail con tu CV fijo adjunto. |
| `/diario` | Encadena los cuatro anteriores, pensado para ejecución desatendida. |

Todo el seguimiento queda en `data/historico.sqlite` y se exporta a un Excel semanal en `data/ofertas/` que puedes editar a mano (cambios de `Estado`/`Notas` se vuelven a importar).

`envio.modo` y `envio.espontaneas_modo` en `config/profile.yaml` controlan si Claude para antes de enviar (`revision`, el valor por defecto) o envía solo (`auto`). Empieza en `revision` hasta que confíes en el resultado.

## 4. Automatízalo (opcional)

En Windows, `instalar_tarea.ps1` programa `/diario` todos los días a las 9:30 con el Programador de tareas (necesita el PC encendido y tu sesión de Chrome abierta):

```
powershell -ExecutionPolicy Bypass -File .\instalar_tarea.ps1
```

**Modo por fases (menos tokens).** `python -m src.diario` hace lo mismo que `/diario`, pero con una sesión de Claude por fase (y por lote de 5 ofertas al postular), de modo que el contexto de una fase no se arrastra a la siguiente, y sin arrancar las fases que no tienen trabajo. `diario.bat` lo usa solo si existe la variable de entorno `JOB_AGENTS_DIARIO=nuevo`.

- Ensayo sin riesgo: `python -m src.diario --prueba --max-ofertas 1` trabaja sobre una copia del histórico en `data/tmp/prueba/`, rellena sin enviar, deja las espontáneas en borrador y no manda el email de resumen. `--simular` solo muestra qué fases y lotes se lanzarían.
- Consumo real de tokens: `python -m src.consumo cargar` y `python -m src.consumo informe` (lee los transcripts de Claude Code).
- Pruebas: `python -m src.test_optim`.

## Seguridad y datos personales

Este repo está pensado para publicarse: todo lo personal (`config/profile.yaml`, `cv/`, `data/`, `output/`, `logs/`, `.env`) está en una lista blanca de `.gitignore` y además bloqueado por el hook `githooks/pre-commit` si intentas commitearlo por error. Nunca edites el `.gitignore` para añadir esos archivos ni fuerces un commit con `--no-verify`.
