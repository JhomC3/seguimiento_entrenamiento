# Gym Tracker Dashboard

Dashboard personal de progresión de gimnasio y nutrición (FastAPI + SQLite + htmx).
Metodología de trabajo: SDD (`specs/`, ver `AGENTS.md` §9).

## Arranque (3 pasos)

```bash
uv sync --locked          # entorno (falla si uv.lock está obsoleto)
./scripts/start_server.sh # único arranque: genera secretos, sirve 0.0.0.0:8000
uv run pytest --ignore=tests/e2e  # suite (cobertura ramas ≥90 %)
```

Detalle: `docs/operations/local-development.md`. Reglas del agente: `AGENTS.md`.

## Mapa

| Área | Doc |
|---|---|
| Constitución y proceso | `docs/constitution.md`, `specs/` |
| Contratos UI / sync / API móvil / seguridad | `docs/architecture/` |
| Operación (release, migraciones, sync) | `docs/operations/` |
| Kit SDD portable | `../sdd-kit/` |

## Estado

- Cola activa: `specs/` con veredicto pendiente (`ls specs/`).
- Calidad: `pytest` + `ruff` + `mypy` en verde, cobertura ≥90 %.
- Última verificación de este README: 2026-09-25.
