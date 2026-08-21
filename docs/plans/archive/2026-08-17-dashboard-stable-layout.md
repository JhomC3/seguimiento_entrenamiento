# Plan 3: Dashboard — Layout estable (CLS = 0)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 1)
**Depende de:** `2026-08-17-dashboard-remove-secondary-actions.md` (plan 2, retirada de acciones secundarias) y `2026-08-17-dashboard-baseline-and-contract.md` Anexo A.1
**Decisiones confirmadas por el usuario:** ninguna nueva — este plan cubre "fijar alturas, espacios y zonas de scroll".

## 1. Objetivo

Eliminar el cambio de altura/layout que desplaza la gráfica al seleccionar músculos o ejercicios. El baseline midió (A.1) que una causa directa es una zona sin altura reservada:
- `#ejercicios-row`: **0px → 28px** al aparecer los chips del músculo (+28px).
- `#history-section`: **0px → 1602px** al cargar el detalle de ejercicio (+1602px); el detalle se trasladará al panel analítico estable del plan 4, no debe resolverse con un hueco vacío gigante en esta fase.
- La gráfica ya es estable: `#unified-chart-plot` y `.chart-empty` fijos a **450px** (CLS 0, verificado e2e).

## 2. Alcance

- Reservar altura estable para `#ejercicios-row` (fila de ejercicios) en estado vacío y cargado.
- Definir el contrato de reserva para el detalle y ejecutarlo junto al panel analítico del plan 4.
- Mantener la gráfica a 450px intacta.
- Añadir tests e2e que cierren los huecos de cobertura del baseline §9 (CLS de `#ejercicios-row` y `#history-section`).

## 3. Fuera de alcance

- Cambiar la lógica de selección, las rutas, los contratos htmx o la gráfica.
- Cambiar a layout de 2 columnas (eso es el plan 4 `left-exercise-catalog`).
- Eliminar/retirar más controles (plan 2).

## 4. Estado actual (referencias verificadas)

- `templates/index.html`:
  - `#cascade-row` (músculos) dentro de un bloque `flex flex-col gap-2 border-b border-neutral-800 pb-4` (líneas ~26-28).
  - `#ejercicios-row` (líneas ~30-33): `<div id="ejercicios-row">` con `<span class="htmx-indicator">Cargando ejercicios…</span>`. Sin `min-height`.
  - `#unified-chart-container` (líneas ~39-43): `<div class="panel panel-spacious"><div id="unified-chart">{{ systemic_chart_html | safe }}</div></div>`.
  - `#history-section` (líneas ~45-46): `<section id="history-section" class="flex flex-col gap-4"></section>` — sin altura.
- `static/css/cascade.css` (líneas 14-28): `chartFadeIn 0.3s` y `#unified-chart-plot, .chart-empty { height: 450px; }`.
- Medidas baseline (A.1 del plan baseline, 1440×900 / 1920×1080 / 390×844):
  - `#ejercicios-row` 0 → 28px (delta +28). Mobile 390×844: `#cascade-row` 136px (wrapping), mismo delta.
  - `#history-section` 0 → 1602px (detalle). La tabla de detalle ocupa un panel alto.
- Tests existentes: `test_lazy_plotly_single_request_and_shell_stable` (tests/e2e/test_dashboard_flow.py:745-771) valida que el contenedor de la gráfica respete ≤1px; no cubre las dos zonas problema.

## 5. Cambios propuestos (paso a paso)

### 5.1 Reservar `#ejercicios-row`

1. En `static/css/cascade.css` (o `components.css` si hay clase canónica): dar `min-height` a `#ejercicios-row`.
   - Valor sugerido: **28px** (altura medida del chip) + algo de respiro. Decision: `min-height: 28px;` para que el estado vacío ya reserve el espacio del chip único.
   - Evitar cambios de altura cuando hay 0, 1 ó 2+ músculos: la fila siempre ocupa lo mismo (contenido vacío colapsado a `min-height`).
2. Opcional: si el `htmx-indicator` se muestra/oculta, asegurar que no altere la altura (positionar el indicador absoluto o mantenerlo dentro del espacio reservado).

### 5.2 Detalle: contrato, no hueco prematuro

1. No reservar 480–560px vacíos bajo la gráfica en el layout vertical actual: resolvería un salto creando una zona visual sin propósito.
2. Documentar el requisito que plan 4 implementará: `#history-section` vive dentro de una superficie analítica estable, con altura limitada y scroll interno solo cuando haya detalle seleccionado.
3. Mantener aquí la prueba de que abrir el detalle no modifica la posición de la gráfica; la invariancia de altura del panel de detalle se prueba después del layout de dos columnas.

### 5.3 Mantener la gráfica intacta

- No tocar `#unified-chart-plot`/`.chart-empty` (450px). Solo asegurar que la reserva de `#ejercicios-row` y `#history-section` no cambie el layout de `#unified-chart-container` (el test `shell_stable` debe seguir pasando).

### 5.4 Tests e2e nuevos (cierran huecos del baseline §9)

1. Nuevo test en `tests/e2e/test_dashboard_flow.py` (o archivo dedicado `test_layout_stability.py`): medir `bounding_box()` (o `getBoundingClientRect`) de `#ejercicios-row`, `#history-section`, `#unified-chart-container` y `window.scrollY` en:
   - Estado base (sin selección).
   - Selección 1 músculo.
   - 2+ músculos.
   - Detalle de ejercicio (`?tipo=ejercicio`).
   - Con confirmación de que `abs(altura_cargado - altura_vacio) <= 1.0` (mismo patrón que `test_lazy_plotly_single_request_and_shell_stable`).
2. Verificar también sin CLS en 3 viewports (1440×900, 1920×1080, 390×844) o al menos en desktop + mobile.
3. Test de que `#unified-chart-container` NO se desplaza hacia abajo al aparecer la fila de ejercicios (offsetTop constante).

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh   # si se tocó CSS/plantillas
```

## 7. Riesgos

- **R1**: `max-height` con scroll en `#history-section` rompe algún test e2e que espera contenido completo visible (p. ej. `test_nivel_cascada_grupo_musculo_ejercicio` que lee las tablas). Ajustar el scroll o el selector del test.
- **R2**: reservar 28px fijos en `#ejercicios-row` aprieta el layout en móvil si la fila se hace más alta al envolver. Validar con el e2e de móvil.
- **R3**: `min-height` puede chocar con `getBoundingClientRect` en tests que miden `scrollHeight`. Verificar.
- **R4**: el `chartFadeIn` no afecta al CLS (es opacidad), no tocar aquí (plan 6 chart-transition).

## 8. Criterios de aceptación

- En estados base, 1 músculo y multi-músculo, `#ejercicios-row` y `#unified-chart-container` no varían en más de **1px** y la gráfica no cambia de `offsetTop`.
- Abrir el detalle no desplaza la gráfica; la altura estable del detalle queda como criterio del plan 4.
- `window.scrollY` no cambia al seleccionar (tras el swap, mantiene posición).
- `#unified-chart-container` no se desplaza verticalmente al aparecer la fila de ejercicios (offsetTop constante ±1px).
- Móvil: scroll interno en `#history-section` sin `_no_overflow` y sin scroll de página agregado.
- Tests previos (shell_stable ≤1px) siguen verdes.

## 9. Próximo plan

`2026-08-17-dashboard-left-exercise-catalog.md` (layout de 2 columnas tipo splits) reutilizará estas zonas estables y la gráfica reservada.
