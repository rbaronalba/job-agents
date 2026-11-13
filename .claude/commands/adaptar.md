---
description: Genera el CV adaptado (y carta si la piden) para todas las ofertas nuevas
---

Lanza el subagente `adaptador` para todas las ofertas en estado `nueva` (si los argumentos traen ids de oferta, solo para esos: pásaselos). $ARGUMENTS

Cuando termine, muéstrame su tabla final y las tecnologías añadidas que debería repasar. Termina con una última línea `ESTADO_FASE: ok`, `ESTADO_FASE: vacio` si no había ofertas nuevas, o `ESTADO_FASE: error` si el subagente falló.
