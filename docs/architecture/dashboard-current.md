# Dashboard actual — contrato funcional y visual

**Estado:** referencia de trabajo; separa comportamiento presente de objetivos pendientes.
**Última revisión:** 2026-08-27.
**Fuente de implementación:** `templates/index.html`, `templates/partials/period_summary_panel.html`, `static/js/chart-interaction.js`, `static/js/level-cascade.js`, `src/charts.py`, `src/summary_service.py` y `app.py`.

La prioridad de ejecución y el estado de los planes están en [`docs/plans/MASTER-PLAN.md`](../plans/MASTER-PLAN.md).

Este documento describe el comportamiento que debe considerarse vigente. Los planes de
`docs/plans/archive/` son históricos: explican decisiones anteriores y no son instrucciones
de ejecución. Si este documento contradice un plan archivado, prevalece este documento.

## 1. Estructura de la pantalla

En escritorio (a partir de 1024 px) el dashboard tiene exactamente tres pistas:

```text
[ catálogo izquierdo / rail ][ gráfica ][ resumen derecho permanente ]
```

- `#dashboard-catalog` ocupa la primera pista.
- `.dashboard-analytics-col` ocupa la segunda.
- `#period-summary-wrap` ocupa la tercera.
- Las tres columnas empiezan alineadas verticalmente.
- El resumen derecho no se pliega, no se convierte en rail y no desaparece.
- Solo el catálogo izquierdo usa `is-catalog-collapsed`.
- Al plegar el catálogo, la primera pista conserva `--catalog-collapsed-w` y la gráfica se expande.
- El rail izquierdo es una barra vertical completa, no una tarjeta flotante.

En móvil el orden es gráfica → resumen → catálogo como drawer superpuesto. El rail de escritorio
no se muestra. El resumen continúa siendo visible debajo de la gráfica.

## 2. Catálogo izquierdo

Controles y estado:

- `#catalog-toggle`: control dentro de `.catalog-panel`.
- `#catalog-rail-toggle`: control dentro de `.catalog-rail`.
- `#catalog-toggle-mobile`: apertura del drawer móvil.
- `#catalog-overlay`: cierre del drawer móvil.
- `is-catalog-collapsed`: único estado de plegado permitido.

El plegado no hace fetch, no cambia URL ni history y conserva músculos, ejercicios, grupos abiertos
y foco. Escape cierra el drawer móvil antes de realizar cualquier otra acción.

## 3. Gráfica

La gráfica vive en un shell persistente `#unified-chart` con estos nodos:

- `#unified-chart-header`;
- `#unified-chart-data` (JSON inerte generado por el servidor);
- `#unified-chart-plot` (nodo Plotly persistente);
- `#unified-chart-empty`.

La respuesta de `/grafica` actualiza gráfica, resumen y catálogo mediante targets OOB allow-listed.
El cliente usa `Plotly.react`; no debe reemplazar el shell completo ni crear un segundo nodo Plotly.

Granularidades vigentes:

- `day`: fechas reales con datos válidos;
- `week`: semanas del ciclo;
- `month`: meses `YYYY-MM`.

El modo Día aplica padding visual al rango X, sin inventar puntos ni modificar los datos de la traza.
El rango Y se calcula con datos reales. La altura del shell usa el contrato CSS existente y el
`ResizeObserver` mantiene ancho y alto de Plotly sincronizados.

## 4. Selección de puntos y comparación

La selección de puntos es local y no genera peticiones HTTP.

- Clic simple: reemplaza la comparación por un punto.
- `Shift` + clic: añade un punto.
- `Shift` + clic sobre un punto seleccionado: lo elimina.
- Se admiten hasta 8 puntos.
- El orden es el orden de selección.
- `Escape`: limpia la comparación y restaura el resumen normal.
- Doble clic conserva la acción previa si existía; no se inventa una acción nueva.

La identidad de un punto es:

```text
granularidad + periodo + nombre de traza
```

La comparación se muestra dentro de `#period-summary-wrap`, sin ocultar ni reemplazar su raíz.
La tabla de comparación contiene:

```text
Periodo | VAR | Series | Reps | Peso | RIR | RM aj.
```

La primera fila es `Base`; las siguientes son `Comparado 2`, `Comparado 3`, etc. Las etiquetas
son compactas:

- día: `18 jul` o `18 jul 26` si hay más de un año;
- semana: `S1`, `S14`;
- mes: `ene 26`.

Al cambiar selección, granularidad, periodo o recibir una nueva figura OOB, se limpia la comparación
porque los puntos anteriores ya no pertenecen necesariamente a la figura actual.

La implementación presente muestra etiquetas `Base`/`Comparado N`; su eliminación y el orden
descendente por periodo son objetivos pendientes de UX-3 en
[`dashboard-ux-refinement.md`](../plans/dashboard-ux-refinement.md). El detalle diario contextual
y la semántica exacta de `actual` frente a `inicio` también quedan pendientes de implementación y
validación funcional/visual.

## 5. Resumen periódico

`#period-summary-wrap` se renderiza server-side inicialmente y vuelve como OOB desde `/grafica`.
Estados válidos:

- `ready`;
- `empty`;
- `error`.

El panel mantiene una sola zona de scroll interna (`.ps-panels`). La comparación usa la misma
superficie y no crea scroll anidado por fila.

El periodo del resumen admite valores enteros del 1 al 8. El valor inicial es 8. El cambio de
periodo actualiza gráfica y resumen en una única petición `/grafica?ventana=N`. Cambiar de pestaña
es local y no genera fetch.

## 6. Contrato de `/grafica`

Parámetros:

- `musculos[]` y `ejercicios[]`: selección actual;
- `gran=day|week|month`: granularidad, por defecto `day`;
- `ventana=1..8`: periodo del resumen, por defecto `8`.

La respuesta puede incluir targets OOB para:

- `#unified-chart-header`;
- `#unified-chart-data`;
- `#unified-chart-empty`;
- `#period-summary-wrap`;
- `#dashboard-catalog-list`.

Todos los targets deben pasar por la allow-list de `src/response_fragments.py`.

## 7. Orden del catálogo y resumen

Los ejercicios se ordenan server-side por número de series válidas dentro de la ventana actual:

```text
kg IS NOT NULL AND reps IS NOT NULL
```

Más datos primero, menos datos después y cero datos al final. Los empates usan el orden estable
del catálogo. El mismo helper debe producir el orden del catálogo izquierdo y de las filas/tabs
del resumen. Un OOB del catálogo debe preservar selección, grupos abiertos y foco.

## 8. Deuda pendiente

La siguiente deuda funcional está fuera de la Fase 2 y requiere una tarea independiente:

- retirar `#history-section` y su contenido deprecated;
- retirar `GET /nivel?tipo=ejercicio` cuando no queden consumidores;
- retirar `trackXhr('/nivel')` cuando la transición de la cascada esté cerrada.

No se deben eliminar rutas o contratos solo porque una acción visible haya desaparecido. Cada
retirada necesita auditoría de consumidores, test 404/ausencia y actualización de este documento.

## 9. Verificación mínima

Antes de declarar una modificación completa:

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e -q
uv run pytest tests/e2e -q --no-cov
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
./scripts/build_css.sh
git diff --check
```

Los cambios de layout o interacción también requieren verificación Playwright a 1280×800 y
390×800, con mediciones de posiciones, visibilidad, overflow, foco y número de peticiones.
