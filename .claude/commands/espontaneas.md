---
description: Candidaturas espontáneas por Gmail (borradores con CV adaptado, o envío si el modo es auto)
---

Lee `.claude/agents/espontaneas.md` y sigue su procedimiento tú mismo en esta conversación (necesita Claude in Chrome para adjuntar el CV). Número de empresas: el primer número de los argumentos (si no lo indico, 5). Argumentos: $ARGUMENTS

- Las herramientas de Chrome son diferidas: antes de usarlas cárgalas todas en una sola llamada `ToolSearch` con `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__find,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__get_page_text`. `file_upload` existe: si no aparece, repite el `ToolSearch` antes de dar el paso por bloqueado.
- Si Claude in Chrome no responde (`tabs_context_mcp`), dímelo, para y termina con la línea `ESTADO_FASE: sin_chrome`.
- Termina siempre con una última línea `ESTADO_FASE: ok` (o `ESTADO_FASE: error` si un fallo te impidió trabajar).
