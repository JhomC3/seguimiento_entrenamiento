---
description: Implementa una tarea con verificación y alcance controlado
agent: build
subtask: false
---

Implementa esta tarea:

$ARGUMENTS

Primero inspecciona el repositorio y el estado de Git. Si existe un plan aprobado en
la conversación, síguelo; si no, formula brevemente el alcance antes de editar.
Si la solicitud sigue siendo ambigua, detente y recomienda `/refine` antes de cambiar
archivos.
Respeta `AGENTS.md`, cambia solo lo necesario, añade tests cuando corresponda y
verifica con los comandos aplicables. No hagas commit ni push. Al final resume el
diff, las pruebas ejecutadas y cualquier riesgo pendiente.
