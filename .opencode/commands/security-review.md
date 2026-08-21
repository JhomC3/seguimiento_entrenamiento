---
description: Audita la seguridad de una tarea o del diff actual sin editar archivos
agent: security
subtask: true
---

Audita la seguridad de este alcance:

$ARGUMENTS

Si no se indicó un alcance concreto, revisa los cambios actuales, incluidos los
staged y los archivos no rastreados. No edites archivos ni ejecutes pruebas
intrusivas. Prioriza amenazas relevantes para este proyecto: CSRF/Origin, token de
Health Connect, validación de entrada, límites de lote/cuerpo, SQL, secretos, CSP,
exposición de rutas y gate LAN. Distingue hallazgos confirmados de riesgos a vigilar.
