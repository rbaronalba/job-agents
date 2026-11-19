# Modelo de amenazas

job-agents es un sistema de agentes de Claude Code que lee contenido de terceros (ofertas, webs de empresas, correos)
y actúa con las cuentas del candidato (Gmail, LinkedIn, portales de empleo). Ese contenido es **no confiable**: lo
puede escribir cualquiera, y un agente que lo lee puede recibir instrucciones ocultas (inyección de prompts).

## Activos

| Activo | Dónde está | Por qué importa |
|---|---|---|
| CV y datos personales | `cv/`, `config/profile.yaml`, `output/` | Contacto, salario, historial laboral |
| Cuentas | Sesiones de Gmail, LinkedIn y portales en el navegador | Enviar correos o candidaturas en nombre del candidato |
| Histórico | `data/historico.sqlite`, `candidaturas.xlsx` | Qué se ha enviado y a quién |
| Secretos | `.env`, `secretos/` | Credenciales OAuth |

## Actores y entradas no confiables

- **Autor de una oferta o de una web de empresa**: texto que el agente lee y puede intentar manipular.
- **Remitente de un correo** que llega a la bandeja que lee el agente.
- **Servidor de un ATS o redirección maliciosa**: respuestas HTTP/XML/JSON manipuladas.
- **Un colaborador o un commit descuidado**: datos personales o secretos que acaban en un repositorio público.

Fuera de alcance: un atacante con acceso al equipo o a las cuentas del usuario, y los fallos de Claude Code, Claude
in Chrome, Composio o Gmail en sí.

## Amenazas y controles

| # | Amenaza | Control | Dónde | Prueba |
|---|---|---|---|---|
| 1 | Una oferta ordena enviar el CV o un correo a un tercero | Gmail: escritura denegada salvo lo que la fase necesita; `send_message` solo al destinatario validado | `diario.permisos()`, `guardia.motivo()` | `test_permisos`, `test_guardia` |
| 2 | Lo mismo por Composio (que también envía correo) | Composio solo en la fase `buscar`, solo herramientas `JOB_SEARCH_*` y bash sin red | `guardia._composio()` | `test_guardia` |
| 3 | Una web da un correo falso para una candidatura espontánea | El destinatario debe constar en `empresas.csv` con el dominio de la web de su empresa; un solo `to`, sin cc ni bcc | `guardia.correo_valido()` | `test_guardia` |
| 4 | El navegador visita o exfiltra a un dominio arbitrario | Lista de dominios en `.claude/settings.json`; por lote, solo los de las ofertas; el hook bloquea `navigate` a otros y JS con `fetch`/XHR/WebSocket | `guardia.motivo()`, `diario.postular()` | `test_guardia` |
| 5 | SSRF o respuestas gigantes desde un ATS | Solo https, IPs públicas (también en redirecciones), tope de 5 MB, slugs validados | `ats._leer()` | `test_guardia` |
| 6 | XML malicioso (billion laughs, XXE) | Se rechaza cualquier XML con DTD o entidades | `ats._get()` | `test_guardia` |
| 7 | Inyección SQL | Valores siempre parametrizados; solo nombres de columna internos en f-strings | `db.py`, `cli.py` | revisión + CodeQL |
| 8 | Argumentos manipulados hacia un subproceso | Lista de argumentos (sin shell), valores con `--opcion=valor` | `cli.registrar_en_seguimiento()` | `test_fase2` |
| 9 | Datos personales o secretos en el repo público | `.gitignore` de lista blanca, hook `pre-commit`, gitleaks en CI | `.gitignore`, `githooks/`, CI | CI |
| 10 | Una sesión de prueba modifica datos reales | Modo prueba: copia de la BD, `Edit`/`Write` denegados sobre archivos reales, sin escritura en Gmail | `diario.permisos()` | `test_seguridad` (sesiones reales) |
| 11 | Duplicar candidaturas o inventar silencios por un Excel ausente | Excel ausente = error o `None`, nunca "cero candidaturas" | `cli.ya_postuladas()`, `cli.sincronizar()` | `test_fase2` |
| 12 | Dependencias vulnerables | `requirements.lock`, `pip-audit`, Dependabot, CodeQL | CI | CI |

## Límites conocidos

Los controles reducen el riesgo; no lo eliminan.

- **Inyección de prompts**: ningún filtro la impide del todo. El diseño asume que ocurrirá y limita lo que un
  agente comprometido podría hacer (mínimo privilegio por fase, destinatarios validados, modo `borrador` por defecto).
- **DNS rebinding**: el filtro de IPs públicas resuelve el nombre antes de conectar y no fija la IP resuelta.
- **WebFetch a hosts públicos**: solo se bloquean hosts internos; datos en la URL hacia un host público no se detectan.
  Por eso `WebFetch` solo se permite en la fase de espontáneas.
- **Clics en Chrome**: el hook inspecciona `navigate` y `tabs_create`; un clic en un enlace lo cubre el permiso por
  dominio de `ClaudeInChromeDomain`, no el hook.
- **Correos con dominio distinto al de la web**: en modo `auto` se bloquean (el borrador sigue funcionando).
- **`--no-verify`** salta el hook `pre-commit`; por eso gitleaks se repite en CI.

## Buenas prácticas para quien use el proyecto

1. Deja `envio.modo` y `envio.espontaneas_modo` en `revision` y `borrador` hasta que confíes en el flujo; pasa a
   `auto` solo si has revisado los resultados de varias ejecuciones.
2. Usa un perfil de Chrome dedicado, no el que tiene tu banca o tu correo personal abiertos.
3. Revisa `git status` antes de cada commit y no uses `--no-verify`.
4. Ejecuta `python -m src.diario --prueba --max-ofertas 1` tras cambiar permisos o la guardia.
