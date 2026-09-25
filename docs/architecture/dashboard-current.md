# Dashboard actual — contrato funcional y visual

**Estado:** referencia de trabajo; separa comportamiento presente de objetivos pendientes.
**Última revisión:** 2026-08-27.
**Fuente de implementación:** `templates/index.html`, `templates/partials/period_summary_panel.html`, `static/js/chart-interaction.js`, `static/js/level-cascade.js`, `src/charts.py`, `src/summary_service.py` y `app.py`.

La cola activa vive en las specs abiertas (`specs/NNN/` con veredicto pendiente); los planes viejos murieron en la spec 014 (git guarda la historia).

Este documento describe el comportamiento que debe considerarse vigente. Los planes viejos murieron en la spec 014 (git guarda la historia). Si un doc histórico contradice este documento, prevalece este documento.

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

## 4. Tabla histórica única y selección local (UX-3 revisada 2026-08-29)

**Decisión de producto (corregida 2026-08-29):** la gráfica respeta la ventana seleccionada 1..8; la tabla histórica del panel muestra **todos los periodos disponibles del ciclo** (`aggregate_sets(...,None,None)`). `No modificar las 9 posiciones de customdata`; el periodo
normalizado para vínculo gráfica→tabla se obtiene de `pt.x` (no de `customdata[0]`).

La tabla única es `#period-summary-wrap #ps-content .ps-table` (sin `#ps-comparison`, sin pestaña `Resumen`).
Jerarquía: sin selección → `[Global]`; músculo(s) → una pestaña por músculo; ejercicio(s) → una pestaña por ejercicio; cada pestaña muestra el histórico por periodo;
Ejercicio(s) → una pestaña por ejercicio → histórico por periodo. Solo `exercise+Día` tiene acordeón desplegable con series.

Formatos (sin `Semana 17`/`Base`/`Comparado`/`2026-08-27` visible; ISO solo `data-*`/aria):
- Día: `S<n> · DD-MM-YY` ej `S17 · 27-08-26` (`week_start_date` reutilizado, no ISO week), aria `Semana 17 · 27 de agosto de 2026`.
- Semana: `S<n> · DD-MM-YY` (lunes de `week_start_date(n,ciclo_start)`).
- Mes: `MM-YY` ej `08-26`, aria `agosto de 2026`.
`·` no genera overflow; `fecha_iso` nunca texto visible; `DD-MM-YY` siempre 2 dígitos.

Selección local sin fetch, solo tab `exercise` Día:
- Clic reemplaza highlight, `Shift+clic` añade (solo dentro del tab activo, sin cambiar tab/selección).
- `Escape` conserva prioridad existente (diálogo/drawer > highlight+acordeón); sin diálogo/drawer limpia highlight sutil (no solo color, `data-selected`+clase) y cierra acordeones.
- ID canónico `gran|periodo_norm|entity_norm` con `periodo_norm` = `YYYY-MM-DD`/`str(semana)`/`YYYY-MM`, entidad `strip().casefold()`, idéntico Python/JS, en `data-period-id`. No usar etiqueta visible. Si no encuentra fila, no error.

Detalle Día+ejercicio: una query batch `LOWER(ejercicio) IN (...)` sin filtro de fechas (todo el ciclo) y sin `kg/reps IS NOT NULL` (mostrar `—` si falta; excluir solo sin fecha/ejercicio),
SSR de `SetDetail` dentro de histórico completo, cerrado por defecto
(`aria-expanded=false`, `hidden`, sin scroll propio — solo `.ps-panels` desplaza).

Al cambiar selección/granularidad/ventana (ventana solo afecta gráfica) o nueva figura OOB, se limpia highlight y se cierran
acordeones; no se conserva detalle obsoleto. Antigua tabla comparativa eliminada.

## 5. Resumen periódico

`#period-summary-wrap` se renderiza server-side inicialmente y vuelve como OOB desde `/grafica`.
Estados válidos:

- `ready`;
- `empty`;
- `error`.

El panel mantiene una sola zona de scroll interna (`.ps-panels`). La comparación usa la misma
superficie y no crea scroll anidado por fila.

La ventana técnica es fija (8) y no se expone como selector visible: el endpoint
acepta `ventana=1..8` por API, pero la UI siempre pide `ventana=8` y el histórico
muestra todo el ciclo. Cambiar de pestaña es local y no genera fetch.

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
