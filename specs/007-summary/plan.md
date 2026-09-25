# Plan técnico — Spec 007 (capas + entrada que re-exporta)

## Estrategia

A diferencia de 006 (fachada pura), `src/summary_service.py` conserva su
razón de ser: `build_period_summary` + `_collapse_entity_rows_global/multi`
son el punto de entrada que `app.py` invoca. Se queda con ellos y re-exporta
el resto. Cero cambios en `app.py`, `src/charts.py`, `tests/`.

## DAG (verificado por AST, sin ciclos)

periods (puro, solo calendario) ← models (dataclasses) ← aggregate (DB +
métricas) ← history (filas) ← entry (`summary_service.py`).

## Cortes

| Módulo | Líneas | Code est. |
|---|---|---|
| `src/summary_periods.py` | 1–64 parcial (doc+imports+constantes) + 65–298 | ~200 |
| `src/summary_models.py` | 307–444 + imports | ~120 |
| `src/summary_aggregate.py` | 447–725 + imports | ~270 |
| `src/summary_history.py` | 728–922 + imports | ~200 |
| `src/summary_service.py` | 925–1111 + re-exports | ~230 |

Imports: cada módulo parte del bloque original completo; `ruff --fix`
poda lo no usado (F401). Constantes de mes/ventana y `WindowWeeks` viajan
con periods (único usuario).

## Orden de tareas

T1 spec+plan+tasks y línea base (hecho). T2 caracterización. T3–T4 extraer
periods+models, aggregate+history. T5 entrada+re-exports, tamaños. T6 gates
+ allowlist + commit.
