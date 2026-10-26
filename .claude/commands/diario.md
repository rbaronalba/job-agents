---
description: Ejecución diaria completa (buscar, adaptar, postular y espontáneas). Pensado para claude -p --chrome desde el Programador de tareas.
---

Ejecuta en orden, sin pedirme confirmación (envio.modo y espontaneas_modo están en auto, autorizado por mí). Si un paso falla, anótalo y sigue con el siguiente.

1. Lanza el subagente `buscador` (búsqueda completa según config/profile.yaml).
2. Lanza el subagente `adaptador` para todas las ofertas en estado `nueva`.
3. Si Claude in Chrome responde (`tabs_context_mcp`), sigue el procedimiento de `.claude/agents/postulador.md` para todas las ofertas en `cv_adaptado`. Si Chrome no está disponible, sáltalo y anótalo.
4. Si Chrome está disponible, sigue `.claude/agents/espontaneas.md` hasta llegar a `envio.espontaneas_objetivo_diario` envíos de hoy.
5. `python -m src.cli excel` y `python -m src.cli resumen --errores "<errores o ninguno>"`.

Termina con un resumen de 10 líneas máximo: ofertas nuevas, CVs generados, candidaturas enviadas (empresa y puesto), espontáneas enviadas (empresa), pendientes de revisión con su motivo y errores. $ARGUMENTS
