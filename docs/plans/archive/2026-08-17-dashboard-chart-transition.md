# Plan 6: Dashboard — Transición de gráfica sin parpadeo

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 1-2, "Corregir el parpadeo básico causado por swaps HTMX")
**Depende de:** baseline A.2/A.3 y `2026-08-17-dashboard-selection-state.md` (una representación única de selección).
**Conclusión verificada:** `purge+newPlot`, fade y respuestas duplicadas contribuyen al parpadeo. `Plotly.react` solo preserva el canvas si HTMX no reemplaza `#unified-chart-plot`.

## 1. Objetivo

Eliminar el parpadeo de la gráfica `#unified-chart` al cambiar selección (músculo/ejercicio/global). Esto se logra con dos cambios de raíz:
1. Mantener un nodo `#unified-chart-plot` persistente y actualizar sus datos con **`Plotly.react`**.
2. Separar responsabilidades: catálogo, gráfica y resumen no pueden reemplazarse mutuamente ni emitir el mismo OOB.

## 2. Alcance

- `static/js/chart-interaction.js`: cambiar el render a `Plotly.react`.
- `static/js/level-cascade.js` y/o `app.py`: eliminar el doble disparo de gráfica en clic de músculo (y en `ⓘ` si aplica).
- `static/css/cascade.css`: gatear `chartFadeIn` con `prefers-reduced-motion`.
- Cerrar el hueco de cobertura "parpadeo" del baseline §9 (contar newPlot vs react).

## 3. Fuera de alcance

- Cambiar reglas de trazas/semántica (plan 7).
- Cambiar layout (plans 3/4).
- Cambiar dimensiones 450px ni el shell JSON inerte.

## 4. Estado actual (referencias verificadas)

- `static/js/chart-interaction.js`:
  - `loadPlotly()` (20-37): carga lazy vía CDN (plotly.js-basic-dist 2.32.0, SRI).
  - `renderUnifiedChart()` (57-93): `if (!plotData(fig)) return;` (línea 68) — **no purga en estado vacío** (caso límite F5 del baseline); luego `Plotly.purge(plotEl); return Plotly.newPlot(...)` (71-77); registra `plotEl.on('plotly_click', ...)` (82-88).
  - `initChartInteractions()` (119-127): escucha `htmx:load` y si el target es `#unified-chart-plot` → `renderUnifiedChart()`.
- `static/js/level-cascade.js`:
  - `clickMuscle` simple (121-132): `refreshExerciseRow()` (→ `/nivel?tipo=musculo&foco=`) **+** `refreshChart()` (→ `/grafica`). Dos pedidos de gráfica.
  - `app.py nivel_view` (1322-1326): `tipo=musculo&foco` también emite `chart_oob_wrapper(...)` (gráfica) — **ese OOB duplica la que ya manda `/grafica`**.
- `static/css/cascade.css` (14-21): `chartFadeIn 0.3s ease-out` en `.plotly-graph-div, .js-plotly-plot` — se dispara en cada aparición.
- Baseline A.2: clic músculo simple = **2 requests** (`/nivel` + `/grafica`), **2 purge, 2 newPlot**, 0 react. Shift+click = 1 request, 1 purge, 1 newPlot. `.ini`/detalle = 3 requests (aún con doble OOB de gráfica antes de detalle).
- Baseline A.3: tiempos de `newPlot` 6-27ms — el parpadeo es **blanqueo del DOM** (purge → vacío → pinta) + fade, no rendimiento de Plotly.

## 5. Cambios propuestos (paso a paso)

### 5.1 Shell persistente + `Plotly.react`

1. Cambiar el contrato HTML: `#unified-chart` conserva de forma permanente el header, `#unified-chart-data` y `#unified-chart-plot`. Las respuestas de `/grafica` actualizan solo el dato inerte y, si cambia, el título; **no** reemplazan `#unified-chart-plot` ni el shell completo.
2. Tras el swap del dato, el render recibe el mismo nodo del plot y reemplaza:
   ```js
   Plotly.purge(plotEl);
   return Plotly.newPlot(plotEl, fig.data, fig.layout || {}, { displayModeBar: false });
   ```
   por:
   ```js
   return Plotly.react(plotEl, fig.data, fig.layout || {}, { displayModeBar: false });
   ```
3. **Estado vacío:** el shell persistente debe mostrar el estado vacío y purgar el nodo existente de forma explícita, sin cargar Plotly si nunca se necesitó.
   ```js
   if (!plotData(fig)) {
     if (typeof Plotly !== 'undefined') Plotly.purge(plotEl);
     return; // o limpiar a chart-empty según diseño
   }
   ```
   - Nota: la carga de Plotly es lazy; en el vacío quizá no esté cargado. Implementar con guarda.
4. Registrar `plotly_click` una sola vez por nodo persistente, eliminando listeners previos antes de reconectar.

### 5.2 Eliminar el doble OOB

1. `/nivel` actualiza solo catálogo/detalle; no emite OOB de gráfica.
   - Consecuencia: actualizar los tests unitarios que esperaban OOB de gráfica en `/nivel?tipo=musculo&foco` (`test_nivel_cascada_grupo_musculo_ejercicio` ~1565, `test_grafica_multi_traza_oob` ~1591 — revisar qué ramas).
   - Ventaja adicional: `nivel_view` queda más liviano y la separación de responsabilidades (nivel → filas, grafica → gráfica) es más clara.
2. `/grafica` actualiza solo los datos/título de la gráfica (y posteriormente el resumen del plan 9); no emite `#ejercicios-row`.
3. Cada clic de músculo puede hacer una solicitud de catálogo y una de gráfica, pero nunca dos respuestas que reemplacen la misma región. Las respuestas deben incluir un id de selección/revisión para ignorar resultados obsoletos.

### 5.3 Fade y motion

1. `cascade.css:14-21`: envolver `animation: chartFadeIn 0.3s ease-out;` en:
   ```css
   @media (prefers-reduced-motion: no-preference) {
       .plotly-graph-div, .js-plotly-plot { animation: chartFadeIn 0.3s ease-out; }
   }
   ```
2. Mantener `chartFadeIn` definido (la keyframe), solo desactivarlo para motion-reduce.

### 5.4 Test de parpadeo (cierra hueco baseline §9)

1. Nuevo e2e (o extensión de `test_lazy_plotly_single_request_and_shell_stable`) que:
   - Intercepte `Plotly.newPlot` y `Plotly.react` (vía `page.evaluate` reemplazando los métodos, como se hizo en el plan 1 §12.8).
   - Cuente: en clic de músculo simple → **1** request a `/grafica`, **0 o 1** `newPlot` (solo primer render), **≥1** `react`.
   - Verifique estabilidad de altura (≤1px) y que no hay blanqueo (pixel check de `#unified-chart-plot` entre swap y afterSettle).
2. Ajustar tests que usaban el comportamiento del doble OOB.

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
```

## 7. Riesgos

- **R1**: `Plotly.react` no disponible en `basic-dist` (o comportamiento distinto) → verificar en el CDN fijado (2.32.0); si falla, mantener purge en caso de `fig.layout` cambiante (el `react` soporta cambio de data y layout).
- **R2**: `plotly_click` re-registrado con react → doble handler; evitar con `plotEl.removeAllListeners('plotly_click')` o registrando una sola vez.
- **R3**: quitar OOB de `/nivel?tipo=musculo&foco` rompe algún flujo que dependiera de esa ruta como única fuente de gráfica → revisar `test_nivel_and_grafica_still_live`, `test_nivel_cascada_grupo_musculo_ejercicio`.
- **R4**: el fade aún provoca percepción de parpadeo aunque haya react → decision de si se elimina por completo en motion-reduce o se mantiene.

## 8. Criterios de aceptación

- Clic músculo simple → una solicitud de gráfica y ninguna respuesta adicional que reemplace la gráfica.
- Después del primer render, las interacciones usan **`Plotly.react`** sobre el mismo nodo, no `newPlot`.
- Altura `#unified-chart-container` estable ≤1px en transiciones.
- `prefers-reduced-motion: reduce` → sin animación `chartFadeIn`.
- Estado vacío no deja trazas obsoletas (F5 resuelto).
- Gates verdes.

## 9. Próximo plan

`2026-08-17-dashboard-chart-series-semantics.md` (contrato de líneas); después `2026-08-17-dashboard-time-granularity.md` (eje temporal).
