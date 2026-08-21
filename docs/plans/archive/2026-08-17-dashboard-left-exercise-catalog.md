# Plan 4: Dashboard — Catálogo izquierdo fijo (layout tipo splits)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 2)
**Depende de:** `2026-08-17-dashboard-stable-layout.md` (plan 3, zonas estables + CLS 0) y baseline Anexo A
**Decisiones confirmadas por el usuario:** al seleccionar un ejercicio debe mostrarse automáticamente su información/resumen; el botón `ⓘ` se retira.

## 1. Objetivo

Transformar el dashboard en un layout de ancho completo, de 2 columnas, siguiendo el patrón visual de `/splits`: **catálogo de músculos→ejercicios a la izquierda (sticky)** y **columna analítica a la derecha** (gráfica + resumen + detalle). Resolver "layout ineficiente" y "no se aprovecha el ancho" del master §2.

## 2. Alcance

- Crear layout de 2 columnas en `templates/index.html` (o en la vista principal).
- Trasladar la cascada actual (`#cascade-row` + `#ejercicios-row`) al panel izquierdo como lista agrupada tipo `details.split-catalog-group` (patrón `/splits`).
- Columna derecha: `#unified-chart-container`, `#history-section` (detalle `?tipo=ejercicio`) y, más adelante, el resumen del plan 9.
- Aplicar panel sticky izquierdo + scroll interno (patrón `.splits-catalog-col`).
- Mantener la estructura del catálogo reservada aunque no haya músculo seleccionado (plan 3).
- Verificar responsive y teclado.

## 3. Fuera de alcance

- Cambiar la semántica de trazas ni la lógica `chart_selection` (plan 7).
- Cambiar el estado de selección global/músculo/ejercicio ni cardio (plan 5).
- Introducir granularidad temporal (plan 8) ni resúmenes (plan 9) — solo dejar el hueco estructural.

## 4. Estado actual (referencias verificadas)

- `templates/index.html` (67 líneas): contenedor `max-w-7xl mx-auto px-4 py-8 flex flex-col gap-8` (NO full-width). Header con botones. Bloques verticales: `#cascade-row`, `#ejercicios-row`, `#unified-chart-container` (`panel panel-spacious`), `#history-section`, `#editor-popup` dialog.
- Patrón `/splits` a replicar:
  - `templates/splits.html`: `.splits-page` (ancho completo, `max-width: none`) con `.splits-page-header` y `.splits-layout` de 2 columnas (`.splits-catalog-col` sticky + `.splits-editor-col`).
  - Catálogo izquierdo: `<aside class="splits-catalog-col"><section class="panel panel-default"><input id="split-catalog-search" class="field-input">… <div id="splits-catalog">` con grupos `details.split-catalog-group` y chips `split-item-card split-catalog-chip` (`data-action="split-add-item"`); grupo `HIIT` al final.
  - CSS respectivo en `static/css/components.css` y `static/css/splits.css` (o el que aplique).
- `static/css/cascade.css`: `#unified-chart-plot`/`.chart-empty` 450px; `#ejercicios-row` reservado (plan 3).
- JS: `static/js/level-cascade.js` (selección actual por Sets + slices a `/nivel` y `/grafica`).

## 5. Cambios propuestos (paso a paso)

### 5.1 Nuevo HTML layout

1. En `templates/index.html` (o plantilla nueva `dashboard.html` extendida de `base.html`):
   - Cambiar el contenedor raíz a ancho completo (clase tipo `.dashboard-page` con `max-width: none`), replicando `.splits-page`.
   - Estructura de 2 columnas:
     ```html
     <div class="dashboard-layout">
       <aside class="dashboard-catalog-col">   <!-- sticky -->
         <section class="panel panel-default">
           <div id="cascade-row">…músculos…</div>
           <div id="ejercicios-row">…ejercicios…</div>
         </section>
       </aside>
       <main class="dashboard-analytics-col">
         <div id="unified-chart-container" class="panel panel-spacious">…#unified-chart…</div>
         <section id="history-section" class="flex flex-col gap-4">…detalle…</section>
       </main>
     </div>
     ```
2. Mantener los ids críticos para el JS/h tmм/htmx: `#cascade-row`, `#ejercicios-row`, `#unified-chart`, `#unified-chart-container`, `#history-section`. **No cambiar la semántica de las rutas `/nivel` y `/grafica`** en este plan (solo el estilo del contenedor).

### 5.2 Catálogo izquierdo agrupado

1. Reutilizar el patrón de grupos desplegables de `/splits` (`details.split-catalog-group` con `summary`) para músculos y ejercicios. Construir el árbol completo desde una única lectura server-side reutilizable; no crear un endpoint adicional solo para compensar un fragmento de UI.
   - El handler de índice puede recibir el catálogo ya agrupado; los fragmentos de selección conservan ids y acciones estables. Si una carga diferida resulta necesaria, justificar el nuevo contrato y cubrirlo con test.
2. Aplicar sticky: `.dashboard-catalog-col { position: sticky; top: Npx; max-height: calc(100vh - …); overflow-y: auto; }` — copiar de `.splits-catalog-col`.
3. La búsqueda no está en la solicitud original y queda fuera de alcance.

### 5.3 Columna derecha

1. El clic normal de ejercicio actualiza en una misma interacción la selección de la gráfica y el detalle/resumen en `#history-section`; no se introduce una segunda acción ni un nuevo botón de información.
2. Reservar el hueco del resumen (plan 9) como zona comentada/placeholder para no girar el layout más tarde.

### 5.4 CSS nuevo

1. Añadir clases canónicas en `static/css/components.css` (no utilidades inline repetidas): `.dashboard-page`, `.dashboard-layout`, `.dashboard-catalog-col`, `.dashboard-analytics-col`, `.dashboard-catalog-group`.
2. Usar **solo tokens** de `static/design-tokens.json` (gate `audit_consistency.py`). No hex literales.
3. Responsive: en móvil (≤ ancho X) apilar columnas (catálogo arriba, análisis abajo) o convertir catálogo en desplegable; replicar breakpoints de `/splits`.
4. Recompilar Tailwind: `./scripts/build_css.sh`.

### 5.5 JS

1. `static/js/level-cascade.js`: adaptar targets si el catálogo cambia la jerarquía del DOM (los listeners delegados sobre `document` con `data-action` siguen funcionando).
2. Si se añade endpoint de catálogo completo, `initLevelCascade`/`loadMuscles` deberá consumirlo y expandir/colapsar grupos (patrón splits).
3. `static/js/chart-interaction.js`: sin cambios (render de `#unified-chart`).

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_splits_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
```

Nuevos tests e2e:
- `_no_overflow` en desktop y móvil (patrón `test_pagina_estructura_sin_overflow` y `test_layout_movil_sin_overflow` de splits).
- Sticky del catálogo izquierdo (comprobar `scrollY` y que la columna permanece visible).
- Clic en ejercicio → abre detalle en `#history-section` (derecha) y refresca gráfica.
- Si se agregó endpoint de catálogo: test unit del endpoint (devuelve músculos→ejercicios agrupados).

## 7. Riesgos

- **R1**: cambiar el árbol del DOM rompe selector de e2e existentes (`#cascade-row .level-chip`, `#ejercicios-row .exercise-chip`). Mitigar: conservar esos ids/clases como alias hasta que los tests se migren.
- **R2**: el endpoint de catálogo completo duplica el contrato de `/nivel` → mantener `/nivel` intacto en este plan y evaluar si luego unifica.
- **R3**: sticky + scroll interno puede producir salto de scroll en móvil → gate `_no_overflow` y revisión de teclado.
- **R4**: la gráfica (450px) + catálogo (sticky) puede saturar altura en pantallas bajas → revisar `max-height` y scroll.

## 8. Criterios de aceptación

- Layout de 2 columnas a ancho completo en desktop; catálogo sticky con scroll interno.
- Móvil: usable (sin overflow horizontal de página; catálogo arriba o desplegable).
- Selección de músculo/ejercicio sigue funcionando (gráfica y marcas) tras el cambio de DOM.
- Detalle `?tipo=ejercicio` accesible desde el catálogo (clic en ejercicio) dentro del panel derecho.
- CLS = 0 heredado del plan 3 (las zonas estables no cambian de altura).
- Gates: todos verdes; axe sin violaciones en los estados nuevos.

## 9. Próximo plan

`2026-08-17-dashboard-selection-state.md` (estado global/músculo/ejercicio y URL única), seguido de `2026-08-17-dashboard-chart-transition.md` (nodo Plotly persistente y responsabilidades OOB separadas).
