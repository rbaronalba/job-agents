# Email modelo de candidatura espontánea

Formato corto (decidido por el candidato el 2026-11-16): el objetivo del correo es una respuesta, no contarlo todo. El CV va adjunto y no se repite en el cuerpo.

## 1. Perfil de la empresa: fija el asunto y el CV
Los perfiles son los de `perfiles_cv` de `config/profile.yaml` (`python -m src.cli perfiles`: id, `cuando`, asunto por idioma y carpeta del CV). Sin esa clave, hay uno por cada clave de `perfiles` de `cv/cv_base.yaml`, o uno solo con el CV base.

Decide el perfil con lo que hace la empresa (su web), no con lo que te gustaría: el que mejor case con su `cuando`. Si ninguno encaja, salta la empresa (`estado: pendiente`, motivo en `notas`).

- Asunto: `<asunto del perfil en el idioma> | <logro> | {nombre}`. CV: `<carpeta del perfil>/<es|en>/`.
- Preséntate solo con el puesto del perfil elegido (asunto y cuerpo); nunca con el de otro perfil.
- `<logro>`: una cifra real, en 4 a 8 palabras, del perfil elegido, sacada de `cv/cv_base.yaml` (`perfiles.<cv>` o un proyecto afín). Forma de los ejemplos válidos (la cifra y el tema salen siempre del CV): "<X>% menos tiempo de respuesta en <tecnología>", "<X>% de cobertura de tests", "<N> <resultado medible> con <método>". Si el perfil no tiene ninguna cifra, usa `<asunto> | <proyecto por su nombre> | {nombre}`. Nunca inventes una cifra.
- El asunto se escribe **al final**, con la línea más fuerte del cuerpo ya escrita.

## 2. Cuerpo (70 a 100 palabras, 4 frases y firma)
Sin "espero que estéis bien", sin "mi nombre es", sin guiones largos ni medios. Tuteo en plural.

```
Hola, equipo de [Empresa]:

[1. Una frase sobre algo concreto de SU trabajo, verificado en su web: un producto por su nombre, un cliente, un lanzamiento reciente, un artículo de su blog. Si no hay nada verificable, no inventes: salta la empresa.]
[2. Qué hago, en una frase, en el perfil elegido: puesto y empresa reciente o proyecto, con la tecnología que les importa.]
[3. Un logro con cifra real, relevante para ellos, ligado a lo que sabes de su necesidad (`senal` y `tecnologias` del CSV): "En mi última etapa en <empresa más reciente del CV>, hasta <mes y año de salida>, conseguí <logro con su cifra del CV> ..." (en inglés: "In my last role at <company>, until <month year>, I <achievement with its figure> ..."). Si el CV no tiene fecha de salida porque el puesto sigue vigente, usa "En <empresa>," sin fecha / el del asunto u otro del mismo perfil. Si la señal es solo una hipótesis, no la presentes como un hecho.]
[4. La petición: "¿Tendríais 15 minutos en las próximas dos semanas para hablar de cómo podría aportar en [su producto o área]?"]
[Solo si el correo no es de empleo: "Si este correo no es el adecuado, os agradecería que se lo hicierais llegar a quien lleve el equipo de [área]."]

Os adjunto mi CV.

Un saludo,
{nombre}
{telefono}
```

## 3. Antes de guardar el borrador
- El asunto lleva el perfil correcto y una cifra que existe en `cv/cv_base.yaml`.
- La primera frase habla de ellos, no de ti.
- Una sola petición y concreta (15 minutos), no "cualquier oportunidad".
- 100 palabras como máximo en el cuerpo.
- No hay seguimiento automático: si el candidato quiere insistir, lo hace él.
