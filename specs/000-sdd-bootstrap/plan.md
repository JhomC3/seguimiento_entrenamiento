# Plan técnico — Spec 000 (línea base, sin código)

Sin cambios de conducta. Todo lo descrito ya existe; el plan solo mapea cada
RF a su implementación y test actuales.

## Estructura de módulos (existente)

- `app.py` → handlers delgados (RF-1, RF-2, RF-3, RF-4, RF-5, RF-7)
- `src/training_service.py` + `src/template_service.py` + `src/exercise_service.py` → dominio de entreno (RF-2, RF-4)
- `src/nutrition_service.py` → dominio de alimentación, recálculo contra catálogo (RF-3)
- `src/health_sync_service.py` + `src/cardio_service.py` → ingesta y anotaciones (RF-5)
- `src/database.py` (único SQL) + `src/db_connection.py` + `src/migrations/runner.py` → persistencia y migraciones (RF-6)
- `src/network_access.py` + `src/security.py` → gate LAN y CSRF/CSP (RF-7)
- `src/mutation_service.py` + `src/backup_utils.py` → backup pre-mutación + undo máx. 10 (RF-2, RF-3, RF-4)
- `src/metrics_engine.py` + `src/charts.py` → RM ajustado, PFR, gráficas Plotly (RF-1)
- `src/response_fragments.py` + `templates/` + `static/js/` → fragmentos OOB y contrato v3 (RF-1)

## Modelo de datos (existente, no se toca)

Tablas `ejercicios`, `training_sets`, `plantillas`, `plantilla_sets`,
`alimentos`, `diario_alimentacion`, `parametros_diarios`, `health_records`,
`cardio_annotations`, `training_splits`, `training_split_items`,
`undo_entries`, `schema_migrations`. Ver `AGENTS.md` §4. Cambios solo vía
migración versionada (RF-6).

## Contrato (existente, no se toca)

- UI/htmx: `docs/architecture/current-ui-contract.md` (RF-1, RF-2, RF-3, RF-4).
- Sync JSON: `docs/architecture/health-sync-contract.md` (RF-5).
- Diario móvil: `docs/architecture/training-api-contract.md` (RF-4, RF-5).
- Seguridad: `docs/architecture/security-model.md` (RF-7).

## Decisiones técnicas (ratificadas, alternativa descartada)

- Monolito modular sin ORM/colas/DI: la alternativa distribuida se descarta por tamaño (backend-standards §1).
- Handlers `def` síncronos en threadpool: se descarta async innecesario (backend-standards §2).
- Nutrientes y RM recalculados en servidor: se descarta confiar en el cliente (backend-standards §5).
- Undo en SQLite (`undo_entries`, máx. 10, solo `before`): se descarta pila solo-memoria como fuente de verdad.

## Estrategia de tests (existente)

- Unitarios de servicios/dominio con DB temporal (RF-2, RF-3, RF-4, RF-5).
- Integración de rutas y contratos OOB/JSON (RF-1, RF-5, RF-7).
- e2e Playwright con servidor aislado para cambios de contrato (RF-1).
- Gates: `uv run pytest --ignore=tests/e2e` (cobertura ≥ 90 %), `ruff format --check`, `ruff check`, `mypy app.py src tests` (RF-8).
