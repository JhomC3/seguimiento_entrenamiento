---
description: Revisa el diff actual sin modificar archivos
agent: reviewer
subtask: true
---

Revisa los cambios actuales del repositorio:

!`git status --short`
!`git diff --stat`
!`git diff --cached --stat`

No edites archivos. Inspecciona tanto `git diff` como `git diff --cached`, sin
limitarte a rutas predefinidas. Si `git status` muestra archivos no rastreados,
léelos antes de concluir la revisión. Busca bugs, regresiones, problemas de
seguridad, contratos rotos, tests faltantes y cambios no relacionados. Devuelve
primero los hallazgos ordenados por severidad, con archivo/línea e impacto; si no
hay hallazgos, indícalo.
