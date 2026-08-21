# Plan 8: Dashboard — Granularidad temporal (días / semanas / meses)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de decisión e implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 3, "Grupos temporales y resúmenes")
**Depende de:** `2026-08-17-dashboard-chart-series-semantics.md` (plan 7, semántica de trazas fija) y baseline (la semana está hardcodeada)
**Decisiones confirmadas:** vista diaria como **predeterminada**; semana y mes disponibles; selector integrado.

## 1. Objetivo

Parametrizar la agregación temporal de la gráfica: **día / semana / mes**, con la vista **diaria como valor por defecto**, y selector en el UI sincronizado con el eje X y el hover. Hoy la semana está hardcodeada en el motor (`_weekly_pfr_df` usa `groupby("semana")` en `charts.py`).

## 2. Alcance

- Refactorizar `_weekly_pfr_df` → `_pfr_df(..., granularity)` soportando `day|week|month`.
- Propagar `granularity` por `chart_selection`, `chart_pfr_timeline`, `dashboard_service.chart_html`, `app._chart_selection_html`, `app.grafica_view`, `app.nivel_view` y `/`.
- Selector UI (días/semanas/meses) persistente en URL (`?gran=...`).
- Mantener la semántica de líneas del plan 7 intacta (solo cambia el eje).
- Hover/resumen adaptados a la granularidad (este plan solo el eje/hover; el resumen detallado en plan 9).

## 3. Fuera de alcance

- El panel de resumen con métricas (plan 9).
- Cambiar colores/trazas (plan 7) ni layout (plans 3/4).
- Cambiar el motor de métricas (RM/PFR) — solo su agrupación temporal.

## 4. Estado actual (hechos verificados)

- `src/charts.py`:
  - `_week_series(db_path, daily_fn)` (12-22): agrega series diarias por **semana de ciclo** (`calculate_cycle_week` + `parse_cycle_start()`).
  - `_weekly_pfr_df(db_path, filter_type, filter_value)` (72-105): llama a `calculate_pfr_timeline` (serie **diaria**) y hace `df.groupby("semana").agg(rendimiento=mean, series=sum, fallos=sum)` (83-93); `crecimiento = rendimiento - 100` (95); `customdata` semanal (96-104) con `_week_series` (volumen/peso/sueño).
  - `chart_selection` (164-260) y `chart_pfr_timeline` (263-333) construyen el eje X "Semana" (tickvals de semanas).
- `src/analysis_data.py`: funciones diarias (`daily_sleep_hours`, `daily_volume`, `daily_weight`, etc.) — no aceptan granularidad.
- `src/metrics_engine.py` `calculate_pfr_timeline` (70-174): timeline **diario** con `groupby("fecha_dt")` (130-143), ffilled por días de descanso; `perf_rel = rm_ajustado/baseline*100` (106-113). Baseline es la primera semana (en `get_exercises_baselines`).
- Config: `CICLO_START = "04/05/2026"`, `CICLO_NUMERO = 1`; `calculate_cycle_week(fecha, cycle_start)` en `training_service.py:28-35` (semanas lun-dom; trunca pre-ciclo a 1).
- No existe parámetro de granularidad en ninguna firma.

## 5. Cambios propuestos (paso a paso)

### 5.1 Motor de agregación

1. En `src/charts.py`, refactorizar `_weekly_pfr_df` → `_pfr_df(db_path, filter_type, filter_value, granularity: str = "day")`:
   - `granularity="week"`: **comportamiento actual** (`groupby("semana")` + `_week_series`), para no romper la semántica del baseline.
   - `granularity="day"`: decidir antes de codificar si se muestran solo días con entrenamiento o días calendario imputados. Propuesta: mostrar solo días con entrenamiento y usar la imputación solo para cálculos internos, para no presentar descansos como sesiones.
   - `granularity="month"`: `groupby` por `año-mes` (p. ej. `fecha_dt.dt.to_period('M')`), etiquetar como "Mmm AAAA"; agregar igual que semana (mean/sum) y `customdata` mensual (reusar `_week_series` re-agrupando o nueva `_period_series`).
2. Adaptar `_pfr_trace` para que el eje X sea el periodo (label) con ticks según granularidad.
3. Mantener `customdata` (series/fallos/volumen/peso/sueño) con los índices que espera `HOVER_TEMPLATE`.

### 5.2 Firma nueva de granularidad

1. Añadir un tipo validado `Literal["day", "week", "month"]` (o enum equivalente) en la capa de servicio; no propagar strings sin validar por `app.py`, charts y análisis.
2. En `dashboard_service.chart_html(db_path, filter_type, filter_value, title="", granularity="day")`.
3. En `app._chart_selection_html(musculos, ejercicios, granularity)` (1269-1289) y en `grafica_view`/`nivel_view`/`read_index` (para `/`).
4. `Query(granularidad="day")` en las rutas; validar en `{"day","week","month"}` (default day).

### 5.3 UI selector

1. En el header de la gráfica (o en el header del shell `_chart_header_html`), añadir un selector de granularidad (seg, tipo `buttons` de Plotly o un `<select>` htmx). Recomendado: **select server-side** que hace `hx-get` a `/grafica?gran=...&musculos=...&ejercicios=...` con `hx-swap-oob` de `#unified-chart`, conservando selección.
2. Persistir `?gran=` en la URL (pushState) junto a la selección; `restoreFromURL` lo lee.
3. Accesibilidad: `<label>` + `<select>` (o aria) y navegación por teclado.
4. Recompilar CSS si se añaden clases nuevas (preferir clases canónicas de `components.css`).

### 5.4 Ajustes de eje y layout

1. El eje X cambia de "Semana" → "Día"/"Semana"/"Mes" según granularidad; `tickvals`/`ticktext` adaptados.
2. Hover: mantener `hovermode="x unified"`; el `customdata` sigue igual (series, fallos, volumen, peso, sueño). El índice de semana en `firstTrainingOfWeek`/clic en punto: con granularidad día, el clic abre el popup del propio día (o el primer entreno del periodo — decidir: con day, popup del día; con week/month, primer entreno del periodo).
3. Sustituir el contrato específico `GET /semana/primer-entreno` por un resolver de fecha de periodo que reciba `granularity` y una clave canónica de bucket. Día abre ese día; semana/mes abren el primer entrenamiento del bucket. Mantener compatibilidad temporal de la ruta semanal hasta migrar sus consumidores.

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest tests/test_charts.py -q
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
```

Nuevos tests:
- Unit: `_pfr_df` con `day`/`week`/`month` produce ejes y valores correctos (month: agrupación por año-mes); `chart_selection` y `chart_pfr_timeline` aceptan granularity; `granularity` inválido → 400 o fallback a day.
- App: `/grafica?gran=week` devuelve gráfica con ticks semanales; `/grafica?gran=month` mensuales; `?gran=day` predeterminado.
- E2E: selector cambia eje y el resumen (plan 9) si está; restore con `?gran=`; clic en punto con `gran=day` abre popup del día.

## 7. Riesgos

- **R1**: el PFR diario es ruidoso y la imputación de descansos puede engañar; la definición de puntos diarios debe quedar aprobada y probada antes del código.
- **R2**: cambiar `_weekly_pfr_df` interno puede romper `HOVER_TEMPLATE` (índice de customdata) → verificar índices invariantes.
- **R3**: el clic-en-punto con gran=day debe abrir el popup del día correcto; ajustar `firstTrainingOfWeek`/`semana_primer_entreno`.
- **R4**: `granularity="week"` debe ser idéntico al comportamiento actual (regresión evitada por los tests de charts existentes).

## 8. Criterios de aceptación

- `day|week|month` producen ejes/ticks/hover correctos y coherentes.
- La vista predeterminada es **day**.
- El selector UI cambia la gráfica conservando selección (músculos/ejercicios) y persiste `?gran=` en URL (restore incluido).
- Clic en punto abre el popup del periodo correcto según granularidad.
- La semántica de líneas del plan 7 no cambia.
- Gates verdes; axe sin violaciones nuevas.

## 9. Próximo plan

`2026-08-17-dashboard-period-summary.md` (panel de resumen con métricas sincronizadas con la granularidad).
