# Plan 9: Dashboard — Resumen de periodo (sincronizado con la gráfica)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de definición de métricas e implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 3)
**Depende de:** `2026-08-17-dashboard-time-granularity.md` (plan 8, granularidad día/semana/mes)
**Decisiones confirmadas por el usuario:** el análisis debe incluir un resumen coherente con día/semana/mes y una tabla por periodo. Las métricas exactas se confirman antes de implementar.

## 1. Objetivo

Añadir un resumen y una **tabla de periodos** que muestren las métricas de la selección, sincronizados con día/semana/mes y con la gráfica. Todo valor se calcula **en el servidor**.

## 2. Alcance

- Nuevo componente de resumen y tabla HTML server-driven.
- Propuesta de métricas: series, reps, peso medio/tonelaje, RM, rendimiento y delta RM; validar definiciones antes de codificar.
- Sincronización con granularidad y selección; refresco por OOB junto a la gráfica.
- Colocación en el panel derecho del layout (plan 4, `#history-section` o una zona nueva).
- Tests unit + e2e.

## 3. Fuera de alcance

- Cambiar la gráfica o su semántica (plans 6/7/8).
- Cambiar layout general (plan 4).

## 4. Estado actual (no existe resumen)

- No hay panel de resumen en el dashboard; solo `#history-section` (detalle tabular de ejercicio) y la gráfica.
- Datos ya disponibles server-side:
  - `get_exercise_session_summary(db_path, ejercicio)` (`charts.py:336-379`): `total_sets`, `total_tonelaje`, `avg_kg`, `avg_reps`, `avg_rm_ajustado` por sesión.
  - `get_exercise_raw_data` (`charts.py:25-69`): serie a serie con `rm`, `rm_ajustado`.
  - `calculate_pfr_timeline` (`metrics_engine.py:70-174`): `rendimiento` por día (+ `sets_totales`, `sets_fallo`, `avg_rir`).
  - `analysis_data.py`: series diarias (`daily_volume`, `daily_weight`, `daily_kcal`, ...).
  - Baseline por ejercicio (`get_exercises_baselines`): `rm_ajustado` promedio de la primera semana.

## 5. Definición candidata de métricas (requiere aprobación)

Para la selección + periodo (granularity + ámbito), el servidor calcula:

| Métrica | Definición | Origen de datos |
|---|---|---|
| **series** | Total de series con carga en el periodo | `training_sets` agregado por periodo (como `weekly["series"]`, pero por granularidad) |
| **reps** | Total de repeticiones (suma de `reps` ∈ series válidas) | `training_sets.reps.sum()` |
| **peso** | Peso medio de las series (promedio de `kg`) o tonelaje total — **decision**: mostrar peso medio + tonelaje como valor secundario | `training_sets.kg.avg()` |
| **RM** | RM ajustado medio del periodo (`avg(rm_ajustado)`) | series válidas del periodo |
| **rendimiento** | Rendimiento relativo medio del periodo (`pfr_timeline.rendimiento.mean()`), base 100 | `calculate_pfr_timeline` |
| **delta RM vs último rendimiento** | `RM_actual − RM_previo`, donde previo = último periodo con datos distinto del actual; mostrar como `+X kg` / `-X kg` / `—` si no hay previo | serie `rm_ajustado` por periodo, comparando último disponible vs el anterior |

## 6. Cambios propuestos (paso a paso)

### 6.1 Datos (análisis)

1. Crear `src/summary_service.py` como servicio tipado, sin SQL fuera de `src/database.py`. Las lecturas/agrupaciones SQL se añaden a `src/database.py`; el servicio combina las métricas y aplica reglas de presentación.
   - `period_summary(db_path, filter_type, filter_value, granularity) -> dict` con las métricas del §5.
   - Reutilizar la agregación por granularidad del plan 8 (o extraer un helper común `_buckets(df, granularity)`).
2. Para **delta RM**: tomar la serie `rm_ajustado` por periodo de la selección (jm. gestión: último periodo con datos vs anterior). Si selección global: usar todas las series; músculo: filtro group; ejercicio: filtro exercise.

### 6.2 Vista / fragmento

1. Nueva plantilla `templates/period_summary.html` (fragmento OOB `#period-summary`):
   - Resumen compacto del periodo activo y una tabla ordenada de los buckets visibles con las métricas aprobadas.
   - La fila/periodo seleccionado debe corresponder inequívocamente al punto o rango de la gráfica.
   - Estado vacío: "Sin datos en este periodo".
   - Todo texto numérico formateado en servidor (o con `|format` en Jinja), server-owned.
2. Añadir `period-summary` a `OOB_FRAGMENT_TARGETS` en `src/response_fragments.py` (allow-list) y crear `summary_oob`/reusar `fragment_oob`.
3. En `app.py`: `grafica_view`, `nivel_view`, `read_index` emiten también el resumen OOB junto a la gráfica (misma selección+granularity). Mantener las rutas actuales; añadir el fragmento.

### 6.3 Sincronización y layout

1. En el layout del plan 4, colocar `#period-summary` debajo de la gráfica (o en `#history-section` si es solo detalle; recomendado: zona propia antes de `#history-section`).
2. Refrescar vía `hx-swap-oob` del mismo response que refresca `#unified-chart` (así resumen y gráfica van siempre juntos y sincronizados).
3. El estado de selección + granularidad determina filtro y ejes; cuando cambie selección (plan 5) o gran (plan 8), se re-sirve.

### 6.4 Tests

- Unit: `period_summary` para global/músculo/ejercicio y day/week/month; delta RM con periodos adyacentes y sin previo → `None`/`—`.
- Unit: el fragmento OOB `#period-summary` aparece en `/grafica` y `/nivel?tipo=musculo` con selección.
- E2E: al cambiar granularidad cambia el resumen (valores coherentes); al cambiar selección cambia; delta RM correcto en datos sembrados (inyectar en DB como en `test_cardio_annotation_saves_from_popup`).

## 7. Riesgos

- **R1**: el delta RM es ambiguo si el periodo no tiene RM anterior (vuelta a definir "último rendimiento" — usar el **último periodo con datos**); documentar claramente.
- **R2**: resumen global pesado de calcular si la DB crece — índices ya existen en `training_sets(fecha, set_orden)` (v014); verificar planes de query.
- **R3**: para varios músculos el resumen debe reflejar la combinación seleccionada, no el global total; documentar este ámbito y no inferirlo de la línea de referencia.
- **R4**: cambiar el contrato de `/grafica` (añadir OOB `#period-summary`) requiere actualizar tests que asertan contenido exacto.

## 8. Criterios de aceptación

- El panel muestra las **6 métricas** del §5 para la selección+granularidad actuales.
- Resumen y gráfica se actualizan juntos (mismo OOB) y son coherentes.
- Delta RM: valor respecto al último periodo con datos; `—` si no hay historial previo.
- Server-first (todo cálculo en Python; el cliente solo renderiza el HTML/JSON).
- Sin datos → estado vacío claro.
- Gates verdes; axe sin violaciones.

## 9. Próximo plan

`2026-08-17-daily-record-page.md` (Fase 4, página `/registro`), que se apoya en el resumen para el encabezado del día si aplica.
