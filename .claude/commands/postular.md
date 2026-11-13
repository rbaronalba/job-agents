---
description: Postula con Claude in Chrome a las ofertas con CV adaptado (envía o para antes de enviar según envio.modo)
---

Lee `.claude/agents/postulador.md` y sigue su procedimiento tú mismo en esta conversación (no lances un subagente: usa Chrome y, en modo revision, necesitas mis confirmaciones). $ARGUMENTS

- Si los argumentos traen ids de oferta (AAAA-Www-NNN), procesa solo esos, en ese orden; si no, todas las de `cv_adaptado`.
- Las herramientas de Chrome son diferidas: antes de usarlas cárgalas todas en una sola llamada `ToolSearch` con `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__find,mcp__claude-in-chrome__form_input,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__browser_batch`. `file_upload` existe: si no aparece, repite el `ToolSearch` antes de dar el paso por bloqueado.
- Necesitas Claude in Chrome conectado (`tabs_context_mcp`); si no lo está, dímelo, para y termina con la línea `ESTADO_FASE: sin_chrome`.
- Termina siempre con una última línea `ESTADO_FASE: ok` (o `ESTADO_FASE: error` si un fallo te impidió procesar las ofertas).
