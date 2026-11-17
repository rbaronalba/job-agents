# Política de seguridad

## Cómo informar de una vulnerabilidad

No abras un issue público. Usa el aviso privado de GitHub:
**Security → Report a vulnerability** (<https://github.com/rbaronalba/job-agents/security/advisories/new>).

Incluye qué ocurre, cómo reproducirlo y qué impacto tiene. Respondo en un plazo orientativo de 7 días y coordino la
publicación del arreglo contigo. Es un proyecto personal sin soporte comercial.

## Qué se considera una vulnerabilidad

- Una entrada ajena (oferta, web de empresa, correo) que consiga que un agente envíe datos o correos a un destino no
  validado, o actúe fuera de lo que permite su fase (ver [THREAT_MODEL.md](THREAT_MODEL.md)).
- Un bypass de la guardia (`src/guardia.py`), de los permisos por fase (`src/diario.py: permisos()`) o del modo prueba.
- Fugas de datos personales o secretos hacia git, logs o servicios externos.
- SSRF, XML o JSON malicioso, o escritura fuera de las carpetas previstas en el código de `src/`.

Fuera de alcance: fallos en Claude Code, Claude in Chrome, Composio o Gmail (informa a sus proveedores), y ataques
que exijan acceso previo al equipo o a la cuenta del usuario.

## Versiones con soporte

Solo la rama `main`.

## Medidas ya aplicadas

Resumen; el detalle y sus límites están en [THREAT_MODEL.md](THREAT_MODEL.md).

- Mínimo privilegio por fase y hook `PreToolUse` que valida los argumentos de Gmail, Composio, Chrome y WebFetch.
- Destinatarios de correo validados contra el dominio de la web de la empresa; el resumen solo va al propio candidato.
- Modo prueba: copia del histórico, sin escrituras en Gmail ni en archivos reales.
- `.gitignore` de lista blanca, hook `pre-commit` y gitleaks en CI para que no se suban datos personales ni secretos.
- Dependencias fijadas (`requirements.lock`), `pip-audit`, Dependabot, CodeQL y OpenSSF Scorecard en CI.
