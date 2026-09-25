# Spec 008 — Partir `src/charts.py` sin cambio de conducta

Constitución: `docs/constitution.md` (principios 1, 2, 6).
Plan de etapa: `/Users/jhomc/.opencode/plan/refactors-006-009.md`.

## Contexto y objetivo

`src/charts.py` tiene 1115 líneas de código (tope: 500 aviso / 800 bloqueo).
Partirlo por familias en módulos ≤500, manteniendo `src/charts.py` como
entrada (`chart_selection` + `_pfr_trace`) que re-exporta todo. Cero cambios
de conducta. El contrato customdata (9 posiciones) no se toca.

Línea base remedida (2026-09-25): charts 1115, app 2758.

## Usuarios

Cualquier agente que toque gráficas; ningún cambio visible para el dueño.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO cualquier consumidor importe desde `src.charts`, EL SISTEMA seguirá resolviendo todos los nombres públicos actuales (builders, datos, formato, tooltip, `extract_point_values`, `point_comparison_id`).
- RF-2: EL SISTEMA ubicará cada pieza en su módulo:
  - `src/chart_format.py`: formato corto, tooltip/labels, hover, traza RIR, color y paleta (~200 líneas).
  - `src/chart_data.py`: raw/cohort/`_pfr_df`/`_hover_totals_for` (~220 líneas).
  - `src/chart_axis.py`: ticks, rangos, ventanas visibles (~130 líneas).
  - `src/chart_timeline.py`: `chart_pfr_timeline` (~130 líneas).
  - `src/chart_metrics.py`: índice de métricas + resumen de sesión (~140 líneas).
  - `src/charts.py`: `chart_selection` + `_pfr_trace` + re-exports con `__all__` (~230 + cabecera).
- RF-3: SI un módulo nuevo supera 500 líneas de código, ENTONCES el refactor se rechaza.
- RF-4: MIENTRAS se ejecuta el refactor, `tests/test_charts.py` permanece en verde; al cierre, gates §8 completos pasan.
- RF-5: Al cerrar, la allowlist pierde `src/charts.py` (si queda <800).

## Fuera de alcance

Ningún cambio visual, de datos o del contrato customdata. 009.

## Criterios de finalización

- Caracterización verde antes y después + gates §8 + RF×test registrado.

## Dudas abiertas

- Ninguna.

## Veredicto (recorrido RF×test, 2026-09-25)

- RF-1: OK — 36/36 nombres (33 defs + 3 consts públicas); 0 cambios en `app.py`/`src/*`/tests salvo allowlist.
- RF-2: OK — format 261, data 218, axis 130, timeline 146, metrics 142, entrada 340.
- RF-3: OK — máx 340.
- RF-4: OK — caracterización 86/86 antes y después; unitaria 893 passed (90.99%); ruff/mypy/module-coverage/file-size verdes. e2e `test_dashboard_flow.py`: mismos 14 preexistentes que en `dev` limpio.
- RF-5: OK — `src/charts.py` fuera de la allowlist; gate `tamaño OK`.
