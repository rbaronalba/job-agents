---
description: Busca ofertas nuevas, las puntúa contra el CV y las guarda en el histórico
---

Lanza el subagente `buscador` para que haga una búsqueda completa según `config/profile.yaml`. $ARGUMENTS

Cuando termine, muéstrame su resumen tal cual (ofertas nuevas, las 5 mejores, coste y errores). Termina con una última línea `ESTADO_FASE: ok` (o `ESTADO_FASE: error` si no se pudo buscar en ninguna fuente).
