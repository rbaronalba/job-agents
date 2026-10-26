---
description: Ejecución diaria completa (buscar, adaptar, postular y espontáneas). Pensado para claude -p --chrome desde el Programador de tareas.
---

Ejecuta en orden, sin pedirme confirmación (envio.modo y espontaneas_modo están en auto, autorizado por mí). Si un paso falla, anótalo y sigue con el siguiente.

1. Lanza el subagente `buscador` (búsqueda completa según config/profile.yaml).
2. Lanza el subagente `adaptador` para todas las ofertas en estado `nueva`.
3. Si Claude in Chrome responde (`tabs_context_mcp`), sigue el procedimiento de `.claude/agents/postulador.md` para todas las ofertas en `cv_adaptado`. Si Chrome no está disponible, sáltalo y anótalo.
4. Si Chrome está disponible, sigue `.claude/agents/espontaneas.md` hasta llegar a `envio.espontaneas_objetivo_diario` envíos de hoy.
5. **Seguimiento**: sigue `../candidaturas-sync/.claude/commands/revisar.md` (modo sin Google Cloud, con el conector de Gmail) ejecutando sus comandos desde la carpeta `../candidaturas-sync`, para que `candidaturas.xlsx` quede al día con respuestas y rechazos. Si el Excel está abierto y no se puede guardar, anótalo y sigue.
6. `python -m src.cli excel` y `python -m src.cli resumen --errores "<errores o ninguno>"`.
7. **Resumen por email**: envía con `send_message` a correo@ejemplo.com (solo a esa dirección) un correo con asunto "job-agents | resumen AAAA-MM-DD" y en el cuerpo, en texto plano y 15 líneas máximo: ofertas nuevas, candidaturas enviadas (empresa y puesto), espontáneas enviadas (empresa), respuestas recibidas de empresas, pendientes que necesitan a el candidato (pregunta o motivo) y errores.

Termina con ese mismo resumen. $ARGUMENTS
