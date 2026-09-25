# Plan técnico — Spec 008 (familias + entrada que re-exporta)

## Estrategia

`src/charts.py` conserva `chart_selection` (el builder principal que `app.py`
y `dashboard_service` invocan) + `_pfr_trace` (solo él lo usa) y re-exporta
el resto con `__all__` desde el principio (lección 007).

## DAG (verificado por AST)

- format: formato/tooltip/hover/RIR/color (rompe ciclo: `chart_color`/`_hex_to_rgba` y `EXERCISE_PALETTE` viven aquí; `_hover_totals_for` se muda a data).
- data → format? NO tras el movimiento: `_pfr_df` solo usa summary_service. data usa summary + db.
- axis: puro (listas/fechas), sin dependencias internas.
- timeline → format + data + axis. metrics → format + data + axis.
- entry → format + data + axis (+ timeline/metrics solo para re-export).

## Cortes (1-indexed, verificados contra inventario)

| Módulo | Líneas | Code est. |
|---|---|---|
| `src/chart_format.py` | 32–266, 289–341, 562–579 + contrato customdata | ~200 |
| `src/chart_data.py` | 267–286, 344–560 | ~220 |
| `src/chart_axis.py` | 582–734 | ~130 |
| `src/chart_timeline.py` | 1039–1188 | ~130 |
| `src/chart_metrics.py` | 1191–1336 | ~140 |
| `src/charts.py` | 737–1036 + re-exports + `__all__` | ~230+cabecera |

Imports: bloque original completo por módulo; poda con `ruff --fix` SOLO
después de añadir `__all__` e imports internos (lección 007). Verificar
decoradores en fronteras.

## Orden de tareas

T1 spec+plan+tasks y línea base (hecho). T2 caracterización. T3 extraer
format+data+axis. T4 extraer timeline+metrics. T5 entrada+re-exports+
`__all__`, tamaños. T6 gates + allowlist + commit.
