# Plan técnico — Spec 014 (borrado + 2 reparos)

## Borrado (RF-1)

`git rm -r docs/plans/` (todo: raíz + `archive/`).

## Reparos (RF-2, RF-3)

- `dashboard-current.md:7`: "La prioridad de ejecución y el estado de los planes están en MASTER-PLAN" → "La cola activa vive en las specs abiertas (`specs/NNN/` con veredicto pendiente)".
- `backend-standards.md:214`: "`docs/plans/*` (planes con justificación y archivo)" → "`specs/NNN/*` (spec, plan y tareas con veredicto)".

## Resto (RF-4)

Borrar `docs/sdd/templates/AGENTS.md` en el checkout principal (0 bytes;
no viaja a worktrees por ser untracked; excepción mínima documentada).

## Decisiones

- Borrado total (no CONGELADO): orden explícita del dueño 2026-09-25 + git como archivo.
- Specs cerradas intactas (historia).
