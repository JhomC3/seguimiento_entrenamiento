# Plan: Dashboard — Línea base y contrato funcional

**Fecha:** 2026-08-17
**Estado:** Completado (análisis + documento; sin cambios de código de aplicación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 0)
**Modo:** solo análisis, medición y documentación — **cero cambios de código, rutas, contratos o estilos** en esta fase.

## 1. Objetivo

Establecer una línea base técnica y funcional del dashboard actual (selección global/músculo/ejercicio, gráfica `#unified-chart`, cascada y popup de registro) ANTES del rediseño. Registrar hechos observados, separándolos de hipótesis y decisiones pendientes, como ancla de regresión para los planes atómicos siguientes (`stable-layout`, `left-exercise-catalog`, `selection-state`, `chart-transition`, ...).

## 2. Alcance

- Documentar rutas, fragmentos OOB, plantillas, módulos JS y servicios implicados en la cadena del dashboard.
- Documentar el flujo de interacción completo (global, músculo, ejercicio, popup).
- Diagnosticar con evidencia las causas del parpadeo y de los cambios de altura/scroll.
- Documentar las reglas actuales de trazas (global / músculo / ejercicio).
- Inventariar la cobertura de pruebas y sus huecos.
- Producir criterios de aceptación verificables para los próximos planes.

## 3. Fuera de alcance

- Cualquier cambio funcional o visual (retirar exportar CSV, botón ⓘ, layout izquierdo, semántica de líneas, granularidad temporal, página `/registro`).
- Cambiar rutas, contratos htmx, tokens, estilos o dependencias.
- Crear migraciones o tocar datos.
- Commits.

## 4. Inventario de archivos y rutas

### Rutas (app.py)

| Ruta | Función | Respuesta |
|---|---|---|
| `GET /` | `read_index` | `index.html` completo; sirve `cascade_row_html` (músculos), `systemic_chart_html`, navegador + editor + popup + `#app-config` |
| `GET /nivel?tipo=global\|musculo\|ejercicio[&foco=]` | `nivel_view` | Fragmento según tipo+foco; `tipo=musculo&foco` y `tipo=global` añaden **OOB `#unified-chart`** vía `chart_oob_wrapper` |
| `GET /grafica?musculo[]=&ejercicios[]=` | `grafica_view` | **OOB `#unified-chart`**; con 1 músculo además OOB `#ejercicios-row` |
| `GET /semana/primer-entreno?semana=` | — | JSON `{fecha}` para abrir el popup desde el clic en la gráfica |
| `GET /editor/popup?fecha=` | — | Cuerpo del popup (fetch en `editor-popup.js`) |

### Fragmentos y targets OOB (`src/response_fragments.py`)

- `OOB_FRAGMENT_TARGETS` incluye 15 targets: `session-editor-wrap`, `exercise-create`, `plantillas-section`, `unified-chart`, `date-navigator`, `session-history`, `nutrition-editor-wrap`, `alimento-create`, `nutrition-templates-section`, `popup-body`, `cardio-day`, `cascade-row`, `ejercicios-row`, `splits-section`, `split-board` (allow-list completa — `response_fragments.py:19-35`).
- `chart_oob_wrapper(chart_html)` → `<div id="unified-chart" hx-swap-oob="innerHTML">…</div>`.
- `fragment_oob(...)` para targets como `ejercicios-row` (usa `swap="outerHTML"`).

### Plantillas

- `index.html`: header (Exportar CSV, Splits, + Registrar), `#cascade-row` + `#ejercicios-row` (**sin alturas reservadas**), `#unified-chart-container` → `#unified-chart`, `#history-section` vacío, `<dialog id="editor-popup">`.
- `cascade_row.html`: chips `data-action="select-muscle"`.
- `ejercicios_row.html`: chips `toggle-exercise` + **botón `ⓘ` `exercise-detail`** (objetivo de retirada en Fase 1).
- `exercise_detail.html`: tablas "Resumen por Sesión" y "Datos Crudos" (sin gráfica propia).

### JS

- `static/js/level-cascade.js`: `selectedMuscles`/`selectedExercises` (Set), `refreshChart()` → `htmx.ajax('/grafica', swap:none)` (produce **OOB**), `refreshExerciseRow()`, `deselectAll()`, historial `pushState`/`popstate`, cancelación de requests en vuelo (`pendingXhrs`), Escape.
- `static/js/chart-interaction.js`: lazy-load de Plotly (basic-dist, SRI), `renderUnifiedChart()` con **`Plotly.purge` + `newPlot`**, `plotly_click` → `firstTrainingOfWeek` → `openEditorPopup(fecha)`; se dispara vía `htmx:load` en `#unified-chart-plot`.
- `static/js/editor-popup.js`: `openEditorPopup`, `showModal`, `?registro=` en historial, navegador de fechas, `POST /cardio/annotation`.

### Servicios

- `src/charts.py`: `chart_pfr_timeline`, `chart_selection`, `_weekly_pfr_df`, `_pfr_trace`, `HOVER_TEMPLATE` (series, fallos, volumen, peso, sueño).
- `src/dashboard_service.py`: `chart_html` (shell JSON + plot), `_chart_header_html`, `_json_for_inline`.
- `src/analysis_data.py`: métricas semanales (PFR) de la gráfica.

## 5. Flujo actual de selección

1. **Carga inicial**: el server renderiza la fila de músculos + la gráfica sistémica (`chart_html("systemic")`). Si la URL trae `?musculos=&ejercicios=`, `level-cascade` restaura la selección y relanza `refreshExerciseRow` + `refreshChart`.
2. **Clic músculo (simple)**: `clickMuscle` → `selectedMuscles={m}`, limpia ejercicios, `refreshExerciseRow()` (GET `/nivel?tipo=musculo&foco=m` → OOB `#unified-chart` + re-render `#ejercicios-row`) y `refreshChart()` (GET `/grafica?musculo=m` → OOB `#unified-chart`). → **Dos respuestas OOB de gráfica muy próximas.**
3. **Shift+click músculo**: añade/quita de la selección múltiple; con 0 → `deselectAll` (gráfica sistémica). Con 2+, `refreshExerciseRow` deja `#ejercicios-row` vacío y `refreshChart` pide la gráfica multi (global sólida + músculos tenues).
4. **Clic ejercicio**: `clickExercise` → solo `refreshChart()` (con los ejercicios del músculo). Shift+click acumula (multi-ejercicio, solo dentro de 1 músculo).
5. **Clic `ⓘ`**: `refresh('#history-section', '/nivel?tipo=ejercicio&foco=...')` → tablas en `#history-section` (`exercise_detail.html`); no toca la gráfica.
6. **Escape** (sin popup abierto): `deselectAll()`.
7. **Historial**: cada interacción hace `pushState(currentUrl())`; `popstate` cancela requests en vuelo, `loadMuscles` y `restoreFromURL`.
8. **Clic en un punto de la gráfica**: `plotly_click` → `fetch('/semana/primer-entreno?semana=')` → `openEditorPopup(fecha)` → GET `/editor/popup?fecha=` dentro de `#popup-body`.

### Qué se reemplaza en cada interacción

| Interacción | Elemento reemplazado | Swap |
|---|---|---|
| Clic músculo simple | `#ejercicios-row` (innerHTML) + `#unified-chart` (OOB) | nivel + grafica |
| Shift+click músculo | `#cascade-row` (marcas client-side) + `#unified-chart` | grafica |
| Clic ejercicio | `#unified-chart` | grafica |
| `ⓘ` | `#history-section` | innerHTML |
| Escape / global | `#cascade-row` (innerHTML) + `#unified-chart` | nivel?tipo=global |

### Qué provoca cambios de altura o scroll (hechos)

- `#ejercicios-row` (en `index.html`) **sin `min-height`**: al aparecer los chips, la fila crece y **desplaza hacia abajo `#unified-chart-container`** (la cascada está arriba de la gráfica).
- `#history-section` **sin altura reservada**: el detalle (`exercise_detail.html`) añade tablas grandes; si el usuario está scrolleando a la altura de la gráfica, **la posición visual salta**.
- La gráfica **NO** cambia altura: `cascade.css` fija `#unified-chart-plot` y `.chart-empty` a **450px** (CLS 0; e2e `test_lazy_plotly_single_request_and_shell_stable` lo comprueba con tolerancia ≤1px).

## 6. Flujo actual de actualización de gráfica

1. El servidor produce la figura y la serializa a JSON dentro de `<script id="unified-chart-data" type="application/json">` (inerte, CSP sin nonce) + `<div id="unified-chart-plot" class="plotly-graph-div">`.
2. HTMX (swap principal u OOB) inserta el fragmento; `htmx:load` sobre `#unified-chart-plot` → `renderUnifiedChart()`.
3. Client: `JSON.parse` → `Plotly.purge(plotEl)` → `Plotly.newPlot(plotEl, data, layout)` → `plotly_click`.
4. Plotly se carga **lazy** (una sola vez, `plotly.js-basic-dist` vía CDN con SRI); si no hay datos, `chart-empty` (450px) y **no se carga Plotly**.

## 7. Diagnóstico preliminar del parpadeo (hechos + hipótesis)

**Hechos observados en el código:**

- F1. `renderUnifiedChart` hace **`Plotly.purge` + `newPlot`** en cada render: reconstrucción total del canvas (blanqueo) en vez de `Plotly.react` (reconciliación de trazas).
- F2. `cascade.css` aplica **`chartFadeIn 0.3s`** (opacidad 0→1) a `.plotly-graph-div` / `.js-plotly-plot` en cada aparición.
- F3. Un clic en un músculo dispara **dos OOB de `#unified-chart`** (`/nivel?...&foco=` y `/grafica`) casi simultáneos → dos `renderUnifiedChart` → doble purge/newPlot (aunque `pendingXhrs` cancela el previo, el código no serializa los awaits de Plotly).
- F4. El swap sustituye `#unified-chart-data` + `#unified-chart-plot`; el render es asíncrono (promesa del CDN), por lo que entre el swap y el `newPlot` el área puede quedar en blanco.
- F5. Estado "sin datos": `renderUnifiedChart` retorna temprano **sin purgar**; dependiendo del timing, si la gráfica anterior tenía datos, el área puede mostrar datos obsoletos o quedar en blanco. **Nota (aclaración del análisis):** el swap htmx sustituye el **nodo** `#unified-chart-plot` completo (innerHTML/OOB), no lo reutiliza; en sentido estricto un plot anterior "purgado por el swap" deja de estar en el DOM. El riesgo real de *stale plot* no es que persista el canvas viejo, sino el **intervalo entre el swap y el `newPlot`** (render asíncrono de Plotly), donde el área recién insertada está en blanco antes de ser poblada. Conviene distinguir dos síntomas: (a) *blanqueo* (área vacía transitoria, ligado a purge+newPlot y al fade) vs (b) *datos obsoletos* (canvas anterior visible) — este último requiere que el render no haya llegado a sustituir el nodo y es muy dependiente de timing. La métrica del parpadeo (sección 11) debería decidir cuál de los dos se mide.

**Hipótesis a validar en el siguiente plan (chart-transition):**

- H1. `purge+newPlot` → `Plotly.react` elimina el blanqueo.
- H2. Eliminar el doble OOB (que `/nivel?...&foco` no reenvíe también la gráfica, o que `clickMuscle` no lance dos pedidos) reduce renders duplicados.
- H3. `chartFadeIn` con `prefers-reduced-motion: reduce` y/o con `react` podría omitirse.
- H4. Validar si queda parpadeo residual por `basic-dist` (no esperado; cubre scatter/líneas).

**Decisiones de arquitectura que NO cambiarán (hechos):** figura como JSON inerte (CSP sin nonce), render client-side, shell 450px, historial con `pushState`/`popstate`.

## 8. Contrato funcional actual

**Reglas de trazas (`chart_selection`):**

- Global (`tipo=global` en `/` o 0 músculos): `chart_pfr_timeline("systemic")` → **1 traza sólida `primary`** "Crecimiento".
- 1 músculo: **compilado del músculo sólido `primary`** + **ejercicios seleccionados tenues** (`alpha=0.4`, `width=3.5`), solo los que pertenecen al músculo (ajenos descartados).
- 2+ músculos: **Global (cuerpo entero) sólido `primary`** + **músculos tenues**; los ejercicios no aplican (se ignoran).
- Eje X = semana del ciclo; Y = "Crecimiento (%)" (rendimiento − 100, baseline semana 1 = 0); hover unificado con resumen (series, fallos, volumen, peso, sueño).
- Altura 450px; `plot_bgcolor`/`paper_bgcolor` transparentes (tokens).

**Del estado:**

- La selección múltiple con Shift solo es músculo-múltiple o ejercicio-múltiple (1 músculo); el global NO se muestra cuando hay 1 músculo (el compilado lo sustituye) — **decisión pendiente en el plan maestro §7**.

**Asimetría de parámetros URL (detalle crítico para R5 y para el historial):**

- **Historial** (`pushState`): `currentUrl()` persiste **`?musculos=A,B&ejercicios=a,b`** (plural, separados por coma) — `level-cascade.js:40-46`.
- **Fetch de datos** (`/grafica`): `refreshChart()` envía **`?musculo=m&ejercicios=e`** (singular) — `level-cascade.js:60-68`.
- **Restauración**: `restoreFromURL()` lee los **plurales** `musculos`/`ejercicios` y los separa por coma — `level-cascade.js:151-170`.
- Es decir: hay **dos convenciones coexistiendo** (singular en la petición de datos, plural en la URI del historial). Esto **funciona hoy** porque el constructor de la URL y el selector de lectura coinciden en la pluralidad, pero es una fuente de error silencioso (restore roto) si el rediseño toca cualquiera de los dos lados sin alinear al otro. **No se cambia en esta fase** (cero cambios), pero debe preservarse o normalizarse de forma explícita en `stable-layout`/`selection-state`. Validación manual: la recarga mantiene la selección (e2e `test_recarga_mantiene_musculo_y_ejercicios_seleccionados`), lo que confirma que la pareja escribir/leer es coherente en la práctica.

**Popup ↔ gráfica:**

- El clic en un punto abre el popup en el primer entreno de la semana (nunca cambia la selección de la gráfica); tras guardar, la gráfica **no se refresca automáticamente** (hay que recargar o reseleccionar).

**Estados de UI:** vacío (`chart-empty` 450px, sin Plotly), cargando (`.htmx-indicator` en cascada/gráfica), error seguro (notice), datos.

## 9. Cobertura y pruebas existentes

**Unit/integración (`--ignore=tests/e2e`)**: 551 pruebas (cobertura 92.8% branch). Relevantes:

- `tests/test_charts.py`: `test_chart_pfr_timeline_crecimiento_base_0`, `test_chart_muscle_exercises_compilado_solo`, `..._una_traza_por_ejercicio`, `..._filtra_ejercicios_ajenos`, `..._ejercicios_mas_tenues`, `test_chart_selection_dos_musculos_global_mas_tenues`, `test_chart_selection_dos_musculos_ignora_ejercicios`, `test_chart_html_header_ciclo...`, `test_chart_pfr_timeline_hover_incluye_resumen`.
- `tests/test_app.py`: `test_nivel_cascada_grupo_musculo_ejercicio`, `test_grafica_multi_traza_oob`, `test_nivel_foco_desconocido_no_rompe`, `test_grafica_multimusculo_global_y_sin_fila_ejercicios`, `test_nivel_and_grafica_still_live`.
- `tests/test_metrics_engine.py`, `tests/test_analysis_data.py`, `tests/test_training_service.py`: métricas y datos.

**E2E (Playwright, `tests/e2e/test_dashboard_flow.py`, `test_accessibility.py`)**: 76 totales. Relevantes:

- `test_cascade_musculo_persistente_y_multi_traza`, `test_muscle_toggle_y_escape_vuelven_al_cuerpo_completo`, `test_recarga_mantiene_musculo_y_ejercicios_seleccionados`, `test_multimusculo_con_shift_click_mantiene_global`, `test_multiejercicios_con_shift_click`, `test_grafica_atras_del_navegador_restaura`.
- `test_lazy_plotly_no_request_on_empty_chart`, `test_lazy_plotly_single_request_and_shell_stable` (estabilidad de altura ≤1px).
- `test_week_click_opens_popup_en_primer_entreno` (clic → popup).
- `test_axe_empty_dashboard`, `test_axe_populated_chart`, `test_axe_popup_editor_and_nutrition`.
- `test_wcag_contrast_critical_elements`, `test_mobile_viewport_renders`.

**Huecos de cobertura detectados:**

- No hay test que mida el **CLS/altura** provocado por la aparición de `#ejercicios-row` ni por `#history-section` (solo se cubre la estabilidad del contenedor de la gráfica).
- No hay test del **doble OOB** (que `/nivel?tipo=musculo&foco` y `/grafica` se disparen juntos).
- No hay test de **parpadeo** (solo del fade/height); el next plan deberá introducir uno (p. ej. contar `newPlot` vs `react`, o ausencia de blanqueo).
- No hay test que verifique la regla "global visible también en selección de ejercicio" (porque hoy no lo está).

### Matriz de cobertura (tests × contrato sección 8)

| Aspecto del contrato | Tests unit | Tests e2e | Estado |
|---|---|---|---|
| Reglas de trazas (global/1 músculo/2+ músculos) | `test_chart_pfr_timeline_crecimiento_base_0`, `test_chart_muscle_exercises_compilado_solo`, `test_chart_selection_dos_musculos_*` | `test_cascade_musculo_persistente_y_multi_traza`, `test_multimusculo_con_shift_click_mantiene_global` | ✅ Cubierto |
| OOB `#unified-chart` en `/nivel` y `/grafica` | `test_grafica_multi_traza_oob`, `test_nivel_and_grafica_still_live` | `test_lazy_plotly_single_request_and_shell_stable` | ✅ Cubierto |
| Selección múltiple (shift+click) | — | `test_multimusculo_con_shift_click_mantiene_global`, `test_multiejercicios_con_shift_click` | ✅ Cubierto |
| Restore por URL (`?musculos=`/`?ejercicios=`) | — | `test_recarga_mantiene_musculo_y_ejercicios_seleccionados`, `test_grafica_atras_del_navegador_restaura` | ✅ Cubierto |
| Clic en gráfica → popup | — | `test_week_click_opens_popup_en_primer_entreno` | ✅ Cubierto |
| Altura fija gráfica (CLS = 0) | — | `test_lazy_plotly_single_request_and_shell_stable` (≤1px) | ✅ Cubierto |
| **CLS de `#ejercicios-row`** | — | — | ❌ Sin test |
| **CLS de `#history-section`** | — | — | ❌ Sin test |
| **Doble OOB** (2 requests de gráfica por clic) | — | — | ❌ Sin test |
| **Parpadeo** (purge vs react) | — | — | ❌ Sin test |
| **Global visible en selección de ejercicio** | — | — | N/A (hoy no lo está) |

## 10. Riesgos

- **R1 (parpadeo)**: reconstrucción total de Plotly en cada cambio; mitigación `Plotly.react` (fase chart-transition).
- **R2 (doble OOB)**: dos renders de gráfica por clic; riesgo de condiciones de carrera (mitigado parcialmente por `pendingXhrs` + cancelación en `htmx:beforeRequest`).
- **R3 (layout)**: `#ejercicios-row` y `#history-section` sin altura reservada → CLS y saltos de scroll (fase stable-layout).
- **R4 (lazy Plotly)**: dependencia CDN (SRI fijado); si falla, notice seguro (ya cubierto); no bloquea el layout.
- **R5 (contrato de selección)**: la semántica global/músculo/ejercicio está acoplada a `chart_selection`; cambiarla sin tests previos puede romper props del historial (`?musculos=`/`?ejercicios=`).
- **Dependencias**: `chart_selection` (charts.py) y `level-cascade.js` son el núcleo; cualquier rediseño de layout debe preservar sus contratos (trazas, OOB, URI) o migrarlos con tests.

## 11. Decisiones pendientes (heredadas del plan maestro §7)

- ¿Eliminar solo el botón visible de Exportar CSV o también la ruta `/exportar/csv`? (Fase 1).
- ¿Global siempre visible también en selección de ejercicio, o el compilado lo sustituye? (Fase 3 — hoy lo sustituye).
- ¿Métricas exactas de cada resumen y granularidad (días/semanas/meses)? (Fase 4).
- ¿Popup como acceso rápido o retirado tras `/registro`? (Fase 5).
- ¿Cardio dentro del registro diario o sección colapsada? (Fase 5).
- **Nuevas (de este análisis):** ¿el parpadeo se mide como "ausencia de blanqueo de canvas" o "número de `newPlot`"? ¿se acepta el fade `chartFadeIn` con `prefers-reduced-motion: reduce`? ¿el doble OOB se elimina en stable-layout o en chart-transition?

**Decisiones pendientes que este análisis añade/refina (a resolver en `chart-transition` / `stable-layout`):**

- **Métrica del parpadeo (blanqueo vs stale-plot)**: definir qué síntoma se mide. Se recomienda medir el **intervalo swap→`newPlot` poblado** (tiempo en blanco) y el **número de `Plotly.newPlot` vs `Plotly.react`** por interacción, con la distinción del F5 (blanqueo transitorio del área recién insertada ≠ persistencia de datos obsoletos de un nodo anterior). La sonda del §12.4 + 12.6 debe generar este baseline.
- **Normalizar la asimetría `musculo`/`musculos`**: decidir si en el rediseño el historial y el fetch de datos comparten convención (recomendado: un único helper `selectionToParams()` y `parseSelectionParams()`), o conservar la coexistencia actual documentada; una u otra, **no** cambiarla a medias.
- **Preservar el contrato `chart_selection`**: la semántica global/músculo/ejercicio y su serialización (trazas, OOB, URI) deben permanecer estables o migrarse con tests que cubran restore por URL.

## 12. Tareas atómicas (línea base — solo documentar/medir, sin cambiar código)

1. **QA baseline:** ejecutar `uv run pytest` (unit) y `uv run pytest tests/e2e -q --no-cov`; fijar el estado verde como ancla (551 unit / 76 e2e).
2. **Inventario OOB/targets:** verificar que el listado de `#unified-chart`, `ejercicios-row`, `session-history`, etc. coincida con `response_fragments.py` y las rutas.
3. **Sonda de CLS/layout (read-only)** con Playwright en 1440×900, 1920×1080 y móvil: medir altura de `#cascade-row`, `#ejercicios-row`, `#unified-chart-container`, `#history-section` en cada estado (base, músculo, 2+ músculos, detalle) y registrar los deltas (respaldará `stable-layout`).
4. **Sonda de requests htmx:** registrar el número/orden de peticiones por interacción (evidencia de F3) — no modifica el framework.
5. **Matriz de cobertura:** cruzar las pruebas existentes contra el contrato (sección 8) y marcar huecos (sección 9).
6. **Escribir el documento** con estas secciones y marcar fecha/estado.
7. **Registrar decisiones pendientes** para los planes siguientes.

**Tareas añadidas tras el análisis (para dar baseline cuantitativo a `chart-transition`):**

8. **Sonda `newPlot`/`react` (read-only)**: interceptar/contar las llamadas `Plotly.purge` y `Plotly.newPlot` por interacción (clic músculo simple, shift+click, clic ejercicio, restore) — produce el baseline numérico del parpadeo (cuántos renders totales por clic) y evidencia la consecuencia del doble OOB (F3). Se registra como anexo con las sondas del §12.4.
9. **Sonda de tiempo swap→render**: medir (playwright `page.evaluate` + `performance.now`) el intervalo entre la inserción del fragmento y la finalización del `newPlot` (promesa de Plotly) para distinguir el *blanqueo* transitorio (F5-a) de un posible *stale plot* (F5-b). Si el rendimiento es imputable a la carga lazy del CDN (primer `newPlot`), documentarlo por separado del parpadeo de reconciliación.
10. **Sonda de asimetría URL**: confirmar por observación que `restoreFromURL` lee los plurales (`musculos`/`ejercicios`) y `/grafica` recibe singular (`musculo`); dejar registro explícito de la convención coexistente (sección 8) para que `stable-layout`/`selection-state` no la rompa a medias.

## 13. Criterios de aceptación (verificables)

- El documento describe el flujo de selección y de gráfica de forma **exacta contra el código** (un reviewer puede verificar cada afirmación en los ficheros citados).
- El inventario de OOB/targets coincide 1:1 con `src/response_fragments.py` (targets allow-list).
- Existen **mediciones objetivas** (sondas Playwright) del CLS de `#ejercicios-row`/`#history-section`, del **número/orden de requests por interacción** (F3), del **número de `Purge`/`newPlot` por interacción**, y del **tiempo swap→render** (blanqueo), guardadas como anexo del plan.
- La distinción **blanqueo vs datos obsoletos** del F5 está documentada y la métrica del parpadeo queda definida (sección 11), con su baseline en las sondas.
- La **asimetría `musculo`/`musculos`** entre el fetch de datos y el historial está documentada (sección 8) y registrada como decisión pendiente (sección 11), de modo que un reviewer pueda verificar que el rediseño no la rompe a medias.
- Las causas del parpadeo están listadas como **hechos separados de hipótesis** (sección 7), y cada hipótesis tiene su plan de validación futuro.
- Las reglas de trazas global/músculo/ejercicio están documentadas con referencias a `chart_selection`.
- La cobertura actual y sus huecos están inventariados.
- **No se modificó código de aplicación** (ni rutas, contratos, estilos ni dependencias); el `git diff` de la rama tras ejecutar este plan es vacío salvo por el propio documento y las sondas (en `.tmp/`).

## 14. Próximo plan recomendado

`dashboard-stable-layout.md` (Fase 1 del plan maestro): reservar alturas de `#ejercicios-row` y `#history-section`, fijar zonas de scroll y retirar los controles secundarios (Exportar CSV visible, botón `ⓘ`), usando las mediciones de la sección 12 como base de aceptación (CLS = 0). Le seguirá `dashboard-chart-transition.md` (`Plotly.react` + eliminación del doble OOB + preferencias de motion), que deberá apoyarse en el baseline de `newPlot`/`react` y de tiempo swap→render generado por las sondas §12.8/§12.9.

**Nota de estabilidad**: dado que los planes atómicos citarán este documento como base de aceptación (CLS, requests, parpadeo, contrato de selección), conviene que viva como **referencia estable** más allá de `docs/plans/` (p. ej. como anexo de `docs/architecture/current-ui-contract.md` o un `docs/baselines/`), para que las mediciones no se pierdan al archivar el plan maestro.

---

### Resumen de hallazgos principales

1. La gráfica ya tiene shell de altura fija (450px) y CLS 0.
2. Las causas reales de "la página salta" son `#ejercicios-row` y `#history-section` sin altura reservada.
3. El parpadeo se explica por `purge+newPlot` + fade de 0.3s + doble OOB de gráfica por clic.
4. Las reglas de trazas (global/músculo/ejercicio) ya están bien definidas y testeadas.
5. Hay huecos de cobertura en CLS, doble OOB y parpadeo.
6. **El parpadeo tiene dos síntomas distinguibles** (blanqueo transitorio del área recién insertada vs datos obsoletos de un nodo previo); la métrica a usar queda pendiente en la sección 11 y requiere baseline en las sondas §12.8/§12.9.
7. **Coexisten dos convenciones de parámetros URL** — singular (`?musculo=`) en el fetch de `/grafica` y plural (`?musculos=`) en el historial/`restoreFromURL` — funcionales hoy, pero punto frágil a preservar en el rediseño (secciones 8 y 11).

### Confirmación

No se modificó código de aplicación. Mediciones realizadas con:
- `uv run pytest --ignore=tests/e2e` → 551 passed, 92.80% branch coverage
- `uv run pytest tests/e2e` → 76 passed (38 dashboard + 5 accessibility + 33 nutrition/splits)
- Sondas Playwright en `.tmp/` (CLS, renders, URL) — resultados en `.tmp/baseline_measurements.json`

---

## Anexo A — Mediciones baseline (2026-08-17)

### A.1 CLS / Layout (1440×900, 1920×1080, 390×844)

| Elemento | Base (0 músculos) | 1 músculo | Delta | Detalle ejercicio | Delta vs base |
|---|---|---|---|---|---|
| `#cascade-row` | 28px | 28px | 0 | 28px | 0 |
| **`#ejercicios-row`** | **0px** | **28px** | **+28px** | 28px | **+28px** |
| `#unified-chart-plot` | 450px | 450px | 0 | 450px | 0 |
| **`#history-section`** | **0px** | **0px** | 0 | **1602px** | **+1602px** |

*Mobile (390×844): `#cascade-row` = 136px (wrapping), mismos deltas.*

**Conclusión**: la gráfica es estable (CLS = 0). Los saltos provienen de `#ejercicios-row` (+28px al aparecer chips) y `#history-section` (+1602px al cargar detalle). Ambos sin `min-height` reservado.

### A.2 Requests htmx por interacción

| Interacción | Requests | Rutas |
|---|---|---|
| Clic músculo simple | **2** | `/nivel?tipo=musculo&foco=...` + `/grafica?musculo=...` |
| Shift+click músculo | 1 | `/grafica?musculo=A&musculo=B` |
| Escape | 1 | `/nivel?tipo=global` |
| Click `ⓘ` (detalle) | **3** | `/nivel?tipo=musculo&foco=...` + `/grafica?musculo=...` + `/nivel?tipo=ejercicio&foco=...` |

**Conclusión**: clic músculo simple dispara **doble OOB de gráfica** (F3 confirmado). Click `.ini` también dispara doble OOB antes de cargar el detalle.

### A.3 Plotly.newPlot / Purge por interacción

| Interacción | Purge | newPlot | react | newPlot durations |
|---|---|---|---|---|
| Clic músculo simple | **2** | **2** | **0** | 10ms, 7ms |
| Shift+click músculo | 1 | 1 | 0 | 27ms |
| Escape | 1 | 1 | 0 | 8ms |
| Click `ⓘ` | **2** | **2** | **0** | 7ms, 6ms |

**Conclusión**: **0 llamadas a `Plotly.react`** — toda reconciliación usa `purge+newPlot` (F1 confirmado). Los tiempos de render son bajos (6–27ms), por lo que el parpadeo visual se explica por el **blanqueo del DOM** (purge antes de newPlot) y el **fade CSS de 0.3s**, no por el tiempo de render de Plotly.

### A.4 Asimetría URL (confirmada)

| Convención | Dónde | Ejemplo |
|---|---|---|
| **Plural** `musculos` | `currentUrl()` → `pushState` | `?musculos=Abdomen,Pectoral` |
| **Singular** `musculo` | `refreshChart()` → `/grafica` | `/grafica?musculo=Abdomen&musculo=Pectoral` |
| **Plural** `musculos` | `restoreFromURL()` | `params.get('musculos')` |

Restore funciona correctamente: `?musculos=Abdomen` → chips seleccionados `["Abdomen"]`. La asimetría singular/plural coexiste y es funcional, pero es un punto frágil a preservar en el rediseño.
