# Tareas — Spec 000 (bootstrap SDD, sin código de negocio)

- [x] T1. Constitución: crear `docs/constitution.md` (6 principios, ≤ 15 líneas) destilando backend/web-standards.
      (RF: todos) Hecho cuando: el archivo existe y no contradice `AGENTS.md` §§5/5.5/7.5.
- [x] T2. Fusión AGENTS.md: añadir bloque SDD append-only (§9) sin reordenar ni borrar nada existente.
      (RF: todos) Hecho cuando: `git diff AGENTS.md` solo muestra la sección añadida.
- [x] T3. Retro-spec: crear `specs/000-sdd-bootstrap/spec.md` con RF-1..RF-8 en EARS referenciando contratos vigentes.
      (RF-1..RF-8) Hecho cuando: cada RF apunta a su contrato/módulo y declara fuera de alcance cualquier cambio de conducta.
- [x] T4. Plan: crear `specs/000-sdd-bootstrap/plan.md` mapeando cada RF a módulos, datos, contratos y tests existentes.
      (RF-1..RF-8) Hecho cuando: ningún apartado propone código nuevo.
- [x] T5. Tareas: crear este archivo con checkboxes y líneas "Hecho cuando:" verificables.
      (RF-8) Hecho cuando: existe y refleja el estado real al cerrar.
- [x] T6. Validación: ejecutar gates en el worktree y registrar el resultado.
      (RF-8) Hecho cuando: `pytest --ignore=tests/e2e` + `ruff format --check` + `ruff check` + `mypy` en verde.
