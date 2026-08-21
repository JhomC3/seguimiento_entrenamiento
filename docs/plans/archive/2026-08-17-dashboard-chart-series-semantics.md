# Plan 7: Dashboard — Semántica de series de la gráfica (contrato de líneas)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de confirmación puntual e implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 2, "Semántica de selección y líneas")
**Depende de:** `2026-08-17-dashboard-selection-state.md` (plan 5, estado explícito) y baseline §8 (reglas de trazas)
**Contrato a implementar a partir de la solicitud:** global en la vista global; global + músculo en la vista muscular; músculo guía + ejercicios en la vista de ejercicio. La visibilidad de global en la vista de ejercicio requiere confirmación final antes de codificarla; la propuesta es ocultarlo para evitar ruido.

## 1. Objetivo

Implementar, documentar y probar las reglas exactas de qué líneas aparecen en cada estado de selección. El comportamiento actual es la línea base, no el contrato objetivo: hoy una selección de un músculo no muestra global y por ello no satisface la solicitud.

## 2. Alcance

- Reemplazar el contrato actual de `chart_selection` por el contrato objetivo.
- Cubrir con tests de tabla la matriz de decisión completa.
- Extraer la decisión de trazas a una función pura para facilitar el testeo por tabla.

## 3. Fuera de alcance

- Añadir cardio como serie de fuerza o como grupo analítico; requiere un plan posterior con métricas propias.
- Cambiar colores/tokens o estilos (depende de plan 8/9 si aplican).
- Rendering/parpadeo (plan 6).

## 4. Línea base y contrato objetivo

En `chart_selection(db_path, musculos, ejercicios)` (`src/charts.py:164-260`):

| Estado | Trazas | Detalle técnico |
|---|---|---|
| **Global** (0 músculos, `/` o `tipo=global`) | 1 traza sólida "Crecimiento" `primary` | `chart_pfr_timeline("systemic")`, `_pfr_trace(alpha=1, width=2.5, marker=8)`. No usa `chart_selection`. |
| **1 músculo** | **Compilado del músculo sólido `primary`** (width 2.5) + **ejercicios seleccionados tenues** (`alpha=0.4`, `width=3.5`, `marker=6`), solo los pertenecientes al músculo (ajenos descartados: `if ejercicio.lower() not in valid: continue`) | `chart_selection` rama 1 (`177-201`); `_weekly_pfr_df("muscle_group", musculo)` + `_weekly_pfr_df("exercise", ejercicio)`. |
| **2+ músculos** | **Global (cuerpo entero) sólido `primary`** + **músculos tenues** (cada uno `alpha=0.4`); **los ejercicios se ignoran** | `chart_selection` rama 2+ (`202-213`). |
| Sin datos | `go.Figure()` vacío → la capa `_chart_selection_html` devuelve `chart-empty` "Sin datos para esta selección" | `app.py:1269-1289`. |

Eje X = semana del ciclo; Y = "Crecimiento (%)" (rendimiento − 100; baseline semana 1 = 0); hover unificado (series, fallos, volumen, peso, sueño) — `HOVER_TEMPLATE` (charts.py:108-113). Altura 450px; bg transparente (tokens).

El contrato objetivo sustituye esas ramas:

| Estado | Series objetivo |
|---|---|
| Global | Global, como única línea guía. |
| Uno o varios músculos, sin ejercicios | Global como referencia + una línea por músculo seleccionado. |
| Ejercicios de un músculo | Músculo como línea guía + ejercicios seleccionados. Global queda oculto salvo confirmación contraria. |
| Ejercicios inválidos o de otro músculo | Se rechazan/sanean en el borde; no cambian las líneas. |

Tests existentes que ya cubren parte (`tests/test_charts.py`): `test_chart_pfr_timeline_crecimiento_base_0`, `test_chart_muscle_exercises_compilado_solo`, `test_chart_muscle_exercises_una_traza_por_ejercicio`, `test_chart_muscle_exercises_filtra_ejercicios_ajenos`, `test_chart_muscle_exercises_vacio_sin_datos`, `test_chart_muscle_exercises_ejercicios_mas_tenues`, `test_chart_selection_dos_musculos_global_mas_tenues`, `test_chart_selection_dos_musculos_ignora_ejercicios`.

## 5. Cambios propuestos (paso a paso)

### 5.1 Contrato documentado

1. En `docs/architecture/current-ui-contract.md`, añadir una sección "Semántica de series de la gráfica" con línea base, contrato objetivo y matriz de decisión.
2. Definir nombres, orden visual, alpha y grosor mediante tokens/configuración central, sin usar transparencia como único diferenciador visual.

### 5.2 Refactor de `chart_selection` a ramas puras (sin cambio de comportamiento)

1. Extraer la decisión de "cuáles y cómo" a una función pura `selection_plan(musculos, ejercicios, catalogo_musculo) -> list[TraceSpec]` (o similar) donde `TraceSpec` = (nombre, tipo_dato, filter, alpha, width).
2. `chart_selection` consume el plan y construye las figuras conforme al contrato objetivo.
3. Objetivo: poder escribir tests por tabla y aislar la futura granularidad temporal.

### 5.3 Tests de matriz de decisión

1. Parametrizar en `tests/test_charts.py` (o nuevo `test_chart_semantics.py`) los casos:
   - global → 1 traza "Crecimiento".
   - 1 músculo, 0 ejercicios → global + compilado muscular.
   - N músculos, 0 ejercicios → global + N compilados musculares.
   - 1 músculo, 1 ejercicio válido → compilado muscular + ejercicio.
   - 1 músculo, N ejercicios → músculo + N ejercicios; global solo si se aprueba conservarlo en este estado.
   - 1 músculo, ejercicio ajeno → ejercicio ignorado (1 traza).
   - 2+ músculos con ejercicios → los ejercicios se limpian antes de construir el plan.
2. Añadir el caso "sin datos → chart-empty" si no está (`test_chart_muscle_exercises_vacio_sin_datos` parece cubrirlo).
3. Mantener el subconjunto e2e: `test_cascade_musculo_persistente_y_multi_traza`, `test_multimusculo_con_shift_click_mantiene_global`, `test_multiejercicios_con_shift_click` deben seguir verdes (actúan como red de integración).

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest tests/test_charts.py -q
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
```

## 7. Riesgos

- **R1**: el refactor de `selection_plan` cambia sutilmente el orden o el naming de trazas (puede romper los tests que asertan por `name`). Usar los tests como red y verificar exactamente los nombres ("Compilado", "Global", nombre de ejercicio/músculo).
- **R2**: la frase del usuario sobre el global en la vista de ejercicio admite dos lecturas; bloquear el cambio de esa rama hasta confirmarla.

## 8. Criterios de aceptación

- La matriz de decisión (§4 + cardio) está 100% cubierta por tests parametrizados o de tabla.
- La línea base queda cubierta y los tests cambian deliberadamente para exigir el contrato objetivo.
- `docs/architecture/current-ui-contract.md` documenta la semántica y cita `chart_selection` y los tests.
- Gates verdes; axe sin regresiones.

## 9. Próximo plan

`2026-08-17-dashboard-time-granularity.md` (eje y resumen temporal), que consumirá esta semántica fija para agregar por día/semana/mes sin cambiar el qué se muestra.
