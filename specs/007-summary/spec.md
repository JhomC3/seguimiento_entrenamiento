# Spec 007 — Partir `src/summary_service.py` sin cambio de conducta

Constitución: `docs/constitution.md` (principios 1, 2, 6).
Plan de etapa: `/Users/jhomc/.opencode/plan/refactors-006-009.md`.

## Contexto y objetivo

`src/summary_service.py` tiene 916 líneas de código (tope: 500 aviso / 800 bloqueo).
Partirlo por capas en módulos ≤500, manteniendo `src/summary_service.py` como
punto de entrada (conserva `build_period_summary` + colapsos) que re-exporta
todo lo público. Cero cambios de conducta.

Línea base remedida (2026-09-25): summary 916, charts 1115, app 2758.
DAG interno verificado (sin ciclos): periods ← models ← aggregate ← history ← entry.

## Usuarios

Cualquier agente que toque resúmenes; ningún cambio visible para el dueño.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO cualquier consumidor importe desde `src.summary_service`, EL SISTEMA seguirá resolviendo todos los nombres públicos actuales (`build_period_summary`, `db_window`, helpers puros, modelos y los privados usados por tests/charts como `_week_bounds`, `_PeriodTotals`).
- RF-2: EL SISTEMA ubicará cada pieza en su módulo de capa:
  - `src/summary_periods.py`: Window, RowMetrics, ventana/intersecciones/etiquetas/orden/formatos, constantes de mes (~190 líneas).
  - `src/summary_models.py`: SummaryFilter, PeriodAggregate, _PeriodTotals, SetDetail, HistoricalPeriodRow, SummaryTab, PeriodSummary (~100 líneas).
  - `src/summary_aggregate.py`: flatten, last_valid_training_date, db_window, aggregate_sets y colapsos (~250 líneas).
  - `src/summary_history.py`: filas históricas por ejercicio/global/músculo (~190 líneas).
  - `src/summary_service.py`: `build_period_summary` + colapsos global/multi + re-exports (~160 + fachada).
- RF-3: SI un módulo nuevo supera 500 líneas de código, ENTONCES el refactor se rechaza.
- RF-4: MIENTRAS se ejecuta el refactor, `tests/test_summary_service.py` permanece en verde; al cierre, gates §8 completos pasan.
- RF-5: Al cerrar, la allowlist pierde `src/summary_service.py` (si queda <800).

## Fuera de alcance

Ningún cambio de conducta, fórmulas (RM, redondeos) o contratos. 008–009.

## Criterios de finalización

- Caracterización verde antes y después + gates §8 + RF×test registrado.

## Dudas abiertas

- Ninguna.

## Veredicto (recorrido RF×test, 2026-09-25)

- RF-1: OK — 44/44 nombres (41 re-exportados + 3 definidos en la entrada); 0 cambios en `app.py`/`src/charts.py`/`tests/`.
- RF-2: OK — periods 207, models 112, aggregate 272, history 203, entrada 259.
- RF-3: OK — máx 272.
- RF-4: OK — caracterización 38/38 antes y después; unitaria 893 passed (90.96%); ruff/mypy/module-coverage/file-size verdes. e2e `test_dashboard_flow.py`: mismos 14 preexistentes que en `dev` limpio.
- RF-5: OK — `src/summary_service.py` fuera de la allowlist; gate `tamaño OK`.
