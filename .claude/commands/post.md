---
description: Redacta un borrador de post de LinkedIn sobre lo que construye el candidato (nunca lo publica)
---

Redactas un borrador de post de LinkedIn para que los reclutadores encuentren al candidato por su combinación poco común: **frontend con Angular + datos + análisis de fútbol**. Tú no publicas: el candidato decide. Responde en español. $ARGUMENTS

1. `python -m src.cli modo`: la carpeta de salida es `<output>/posts/` (en modo prueba apunta a `data/tmp/prueba/`). Lee los borradores anteriores de esa carpeta (solo su primera línea `Tema:`) para no repetir tema.
2. Fuentes, solo hechos reales:
   - `cv/cv_base.yaml` (experiencia, proyectos, cifras) y `candidato.empleo_actual` y `candidato.proyectos` de `python -m src.cli perfil-formulario`.
3. Elige **un** tema, rotando entre: una decisión técnica de uno de los proyectos de `candidato.proyectos` (qué problema, qué alternativa descartaste y por qué); un análisis de partido o de jugadores con datos (método y conclusión, sin datos internos del club ni nombres de jugadores que no sean públicos); algo aprendido construyendo agentes de IA o automatizaciones; un detalle de frontend con Angular.
4. Escribe `<output>/posts/AAAA-MM-DD.md`:
   - Primera línea `Tema: <tema en 5 palabras>`, una línea en blanco y el post.
   - Post de 120 a 220 palabras: primera línea que enganche sin clickbait, una historia concreta con un dato o una decisión, qué aprendiste, y una pregunta final para generar comentarios. Párrafos de 1 o 2 frases. Como mucho 3 hashtags al final (#Angular, #DataAnalytics, #FootballAnalytics o similares). Sin guiones largos ni medios, sin "apasionado", "emocionado de anunciar" ni frases vacías, sin emojis en cada línea.
   - Al final, tras una línea `---`, una nota para el candidato: qué imagen o captura acompañaría bien el post.
5. Termina con la ruta del borrador y la línea `ESTADO_FASE: ok`.
