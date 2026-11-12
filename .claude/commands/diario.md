---
description: Ejecución diaria completa (buscar, adaptar, postular y espontáneas). Pensado para claude -p --chrome desde el Programador de tareas.
---

(Para la ejecución desatendida existe también `python -m src.diario`, que hace lo mismo con una sesión de Claude por fase y salta las fases sin trabajo; este comando sigue siendo la versión en una sola sesión.)

Ejecuta en orden, sin pedirme confirmación (envio.modo y espontaneas_modo están en auto, autorizado por mí). Si un paso falla, anótalo y sigue con el siguiente.

1. Lanza el subagente `buscador` (búsqueda completa según config/profile.yaml).
2. Lanza el subagente `adaptador` para todas las ofertas en estado `nueva`.
3. Las herramientas de Chrome son diferidas: antes de usarlas cárgalas todas en una sola llamada `ToolSearch` con `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__form_input,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__browser_batch`. `file_upload` existe: si no aparece, repite el `ToolSearch` antes de dar el paso por bloqueado. Si Claude in Chrome responde (`tabs_context_mcp`), sigue el procedimiento de `.claude/agents/postulador.md` para todas las ofertas en `cv_adaptado`. Si Chrome no está disponible, sáltalo y anótalo.
4. Si Chrome está disponible, sigue `.claude/agents/espontaneas.md` hasta llegar a `envio.espontaneas_objetivo_diario` envíos de hoy.
5. **Seguimiento** (solo si `candidaturas_sync` está configurado en `config/profile.yaml`, es opcional): sigue `<candidaturas_sync>/.claude/commands/revisar.md` (modo sin Google Cloud, con el conector de Gmail) ejecutando sus comandos desde esa carpeta, para que `candidaturas.xlsx` quede al día con respuestas y rechazos. Si el Excel está abierto y no se puede guardar, anótalo y sigue. Si `candidaturas_sync` es `null`, salta este paso.
6. `python -m src.cli excel` y `python -m src.cli resumen --errores "<errores o ninguno>"`.
7. **Resumen por email**: envía con `send_message` a `candidato.email` de `config/profile.yaml` (solo a esa dirección) un correo con asunto "job-agents | resumen AAAA-MM-DD" y en el cuerpo, en texto plano y 15 líneas máximo: ofertas nuevas, candidaturas enviadas (empresa y puesto), espontáneas enviadas (empresa), respuestas recibidas de empresas, pendientes que necesitan al candidato (pregunta o motivo) y errores.

Termina con ese mismo resumen. $ARGUMENTS
