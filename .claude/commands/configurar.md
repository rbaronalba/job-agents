---
description: Onboarding guiado -- genera config/profile.yaml y cv/cv_base.yaml a partir del CV que pegues en el chat
---

Sigue tú mismo este procedimiento en esta conversación (no lances un subagente: necesitas preguntarme cosas y leer lo que te pego). Responde en español salvo que yo escriba en otro idioma.

## Reglas
- **Nunca inventes datos.** Todo lo que escribas en `config/profile.yaml` o `cv/cv_base.yaml` tiene que venir de lo que yo te pego o te contesto. Si algo no está claro o falta, pregúntamelo antes de darlo por bueno; no rellenes huecos a tu criterio.
- Los dos archivos están en `.gitignore` (nunca se suben), así que puedes escribir datos reales sin problema.

## Procedimiento
0. **Prepara el entorno** (idempotente, puedes ejecutarlo aunque ya esté hecho): `git config core.hooksPath githooks` (activa el hook anti-secretos de `githooks/pre-commit`; sin esto, commitear accidentalmente un dato personal no se bloquea), `pip install -r requirements.txt` y `playwright install chromium` (lo usa `src/cv.py` para generar los PDF). Dime si algo falla antes de seguir.
1. **Comprueba si ya existen** `config/profile.yaml` o `cv/cv_base.yaml`. Si alguno ya existe, dime qué contiene en una línea y pregúntame si quiero sobrescribirlo, actualizarlo con lo nuevo que te pase, o cancelar. No sigas sin mi confirmación.
2. **Pide el CV**: pídeme que te pegue mi CV (texto, o el "Acerca de"/"Experiencia" de mi LinkedIn) en el chat, en el idioma que sea. Si quiero el CV en los dos idiomas (`es` y `en`) de `cv/cv_base.yaml`, pregúntame si lo pego en los dos o si traduces tú el que falte (avísame de que la traducción hay que revisarla).
3. **Pide los datos de contacto y búsqueda** que no vengan en el CV y hacen falta para `config/profile.yaml`: lee `config/profile.example.yaml` entero para ver qué campos pide (contacto, puestos, ubicaciones aceptadas, modalidad, salario mínimo aceptable, expectativa salarial, nivel de inglés, catalán u otros idiomas si aplica, disponibilidad). Pregúntamelos de golpe, agrupados, no uno a uno.
4. **Redacta `cv/cv_base.yaml`** a partir de `cv/cv_base.example.yaml` (mismo esquema) y de lo que te haya pasado:
   - `contacto`: datos reales que te di.
   - `experiencia`: un bloque por puesto, con un id corto y claro (minúsculas, sin espacios) por puesto; viñetas en formato XYZ (logré X, medido por Y, haciendo Z) **solo si el CV que pegué ya trae esa cifra o ese resultado**. Si un logro no tiene métrica, dímelo y pregúntame si tienes el dato real o si lo dejas sin cifra (no inventes el número).
   - `proyectos`: igual, un id corto por proyecto, con enlaces (GitHub/demo) solo si te los doy.
   - `titular` y `resumen`: redáctalos tú a partir de los hechos que te di (esto sí es redacción, no invención de hechos), siguiendo el estilo del ejemplo (3 frases máximo en el resumen).
   - `formacion` e `idiomas`: tal cual me lo dieras.
   - `skills`: agrupa las tecnologías/competencias que mencioné; no añadas ninguna que no haya dicho.
   - `perfiles`: pregúntame primero si quiero un segundo perfil de CV muy distinto al principal (p. ej. mi puesto es frontend pero también quiero postular a datos). Si digo que no, **borra la clave `perfiles` entera** (en los dos idiomas) de lo que escribas. Si digo que sí, pide los hechos de ese perfil igual que el principal.
5. **Redacta `config/profile.yaml`** a partir de `config/profile.example.yaml` con los datos del paso 3. Dejas intactos los comentarios explicativos del ejemplo; solo cambias los valores.
6. **Avisa de los pasos manuales que quedan fuera de este comando**: editar `.claude/agents/adaptador.md` (las reglas de "Tipo de oferta" y "Proyectos" usan los ids del candidato original, hay que cambiarlos por los míos) y, si quiero usar `/espontaneas`, revisar `data/empresas.csv` y `.claude/agents/espontaneas.md` (anillos geográficos: hay que sustituirlos por los de mi propia ciudad).
7. **Verifica**: ejecuta `python -m src.cv` (autochequeo del CV base) y `python -m src.cli cv base`; enséñame el resultado (páginas, coincidencia) y dime claramente que **revise a mano** `cv/cv_base.yaml` antes de usarlo en candidaturas reales, porque lo he escrito yo a partir de lo que le di a Claude, no es un documento legal verificado.
8. **Resume los siguientes pasos**: `/buscar` (busca ofertas), `/adaptar` (adapta el CV a las nuevas), `/postular` (postula con Claude in Chrome), `/espontaneas` (candidaturas espontáneas por Gmail), o `/diario` para encadenar los cuatro. Si quiero automatizarlo a diario sin tocar nada, `instalar_tarea.ps1` (Windows) lo programa.
