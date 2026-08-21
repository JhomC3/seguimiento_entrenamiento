# Plan: Recuperación 1 — Dashboard vertical mínimo

**Ruta:** `docs/plans/dashboard-recovery-1-vertical-slice.md`
**Fecha:** 2026-08-18
**Precedente:** `docs/plans/dashboard-implementation-gap-and-recovery.md` §4 (Recuperación 1, "próximo trabajo autorizado")

## 1. Estado del plan

`pendiente` — documento de diseño para implementación por un agente. No se implementa código en este plan.

**Supuesto crítico de verificación:** el estado del código descrito aquí corresponde al **working tree actual de la rama** (hay cambios sin commitear en `app.py`, `src/charts.py`, `static/js/chart-interaction.js`, `static/js/level-cascade.js`, `static/css/cascade.css`, `templates/index.html`, `templates/ejercicios_row.html`, `tests/*`, entre otros — `git status`). Si se commitea antes de implementar, re-verificar las líneas citadas antes de empezar.

## 2. Objetivo

Cerrar la experiencia principal del dashboard (selección global/músculo/ejercicio, gráfica sin parpadeo con nodo Plotly persistente, detalle automático del ejercicio, layout vertical estable, sin OOB duplicados) antes de tocar `/registro`, cardio analítico, granularidad temporal, formularios compactos o el retiro del popup. Todo lo demás queda documentado como trabajo posterior, no implementado aquí.

## 3. Contexto y problema

El gap-doc (`dashboard-implementation-gap-and-recovery.md`) declara la Recuperación 1 como el siguiente plan atómico y fija su aceptación: *"un clic de músculo o ejercicio produce una sola actualización visual de la gráfica, sin área en blanco, sin cambio de `offsetTop` y con detalle automático"*. El estado actual no cumple esa aceptación: la gráfica se reconstruye por completo en cada selección, el listener `plotly_click` queda huérfano tras el primer swap, el detalle del ejercicio no es alcanzable desde la UI y hay un error silenciado con `except Exception: pass`.

Los planes de `docs/plans/archive/2026-08-17-*` son contexto histórico (diseño detallado), no evidencia de implementación ni cola activa. El único documento de cola vigente es el gap-doc.

## 4. Evidencia del estado actual

### 4.1 Hechos observados (código + tests, working tree)

**H1 — `/nivel?tipo=musculo&foco=` ya NO emite gráfica OOB.** `app.py:1328-1329` devuelve solo `_ejercicios_row_html(request, foco, [])`. El test `tests/test_app.py:1501-1504` lo documenta ("la gráfica viene de /grafica"). `current-ui-contract.md:75` sigue diciendo que emite OOB `#unified-chart` → **drift documental**.

**H2 — `/nivel?tipo=global` SÍ reemplaza `#unified-chart` completo.** `app.py:1330-1338` devuelve `_cascade_row_html(...) + chart_oob_wrapper(chart_html(...))`. `chart_oob_wrapper` (`src/response_fragments.py:158-168`) hace `hx-swap-oob="innerHTML"` sobre el shell.

**H3 — `/grafica` reemplaza `#unified-chart` completo y emite más targets.** `app.py:1353-1354` (`chart_oob_wrapper`), `app.py:1355-1362` (OOB `#ejercicios-row` outerHTML cuando hay exactamente 1 músculo) y `app.py:1376-1379` (OOB `#period-summary`) envuelto en `except Exception: pass`.

**H4 — `#unified-chart-plot` se destruye y recrea en cada selección.** El swap innerHTML del shell sustituye el script de datos y el div de render. `Plotly.react` (`static/js/chart-interaction.js:74`) se ejecuta siempre sobre un nodo recién creado → la persistencia real no existe y `chartFadeIn` (`static/css/cascade.css:14-19`) se repite en cada aparición. Consecuencia visual: blanqueo + re-pintado en cada clic.

**H5 — El listener `plotly_click` se pierde tras la primera actualización.** `static/js/chart-interaction.js:55,79-88`: flag global `_plotlyClickRegistered`. Tras el primer render el flag es `true`; los nodos nuevos (recreados por cada swap) nunca reciben el listener. Solo funciona la gráfica inicial (por eso `test_week_click_opens_registro_en_primer_entreno`, `tests/e2e/test_dashboard_flow.py:351-383`, hace clic antes de cambiar selección).

**H6 — El valor predeterminado de granularidad sigue siendo `week`.** `app.py:1302` y `app.py:1347` (`gran: str = Query(default="week")`), `static/js/level-cascade.js:50` (`_granularity = 'week'`) y `level-cascade.js:45` (se omite del URL el `week`). No es `day`.

**H7 — El clic de ejercicio NO actualiza `#history-section`.** `clickExercise` (`level-cascade.js:142-157`) solo hace `refreshChart()` + `pushState()`. Ningún JS toca `#history-section` (grep: solo el comentario de `level-cascade.js:3` y CSS). La ruta `/nivel?tipo=ejercicio&foco=` existe (`app.py:1311-1327`) pero **no tiene cliente**: el detalle es inalcanzable desde la UI.

**H8 — El layout conserva todos los targets.** `templates/index.html:24-46`: `#cascade-row`, `#ejercicios-row`, `#unified-chart-container > #unified-chart`, `#period-summary`, `#history-section` (vacía, sin placeholder). `#unified-chart` no contiene un elemento de header con id propio: el header es texto del fragmento (`src/dashboard_service.py:143-151`, `_chart_header_html`).

**H9 — URL: historial con valores separados por comas; requests con claves repetidas.** `level-cascade.js:42-43` (`params.set('musculos', [...].join(','))`); `level-cascade.js:67-69` (`params.append('musculos', m)` por músculo). E2E lo verifica: `assert "musculos=Pectoral%2CBiceps" in page.url` (`test_dashboard_flow.py:626`). FastAPI `list[str]` recibe bien las claves repetidas.

**H10 — `except Exception: pass` real en `app.py:1378-1379`** (resumen de periodo, silencioso). `get_filters` (`dashboard_service.py:48-65`) usa `try/except (sqlite3.Error, OSError)` con `logger.exception` y retorno seguro → patrón sancionado, no es error oculto.

**H11 — Contrato actual de trazas (testeado) difiere del contrato objetivo del prompt.** `test_chart_semantics_decision_matrix` (`tests/test_charts.py:251-287`) y `current-ui-contract.md:300-313`: 1 músculo → solo "Compilado"; 2+ → "Global" + músculos. El prompt exige línea global visible en estado muscular → cambio de contrato necesario. El gap-doc §3 confirma como decisión de producto: "La gráfica muscular muestra global + músculo. La gráfica de ejercicios muestra músculo guía + ejercicios".

**H12 — `/grafica` con selección vacía devuelve figura vacía ("Sin datos")**. `src/charts.py:272-286`: con `len(musculos) == 0` no entra en ninguna rama → `go.Figure()` sin trazas. Hoy es inalcanzable porque `deselectAll` usa `/nivel?tipo=global`, pero viola el contrato objetivo (estado global = 1 línea sistémica).

**H13 — Shell inicial sin datos no tiene nodo plot.** `chart_html` (`dashboard_service.py:154-181`) en el caso sin datos emite solo header + `div.chart-empty` (sin `#unified-chart-data` ni `#unified-chart-plot`). `test_lazy_plotly_no_request_on_empty_chart` (`test_dashboard_flow.py:734-741`) asume `#unified-chart-data` detached.

**H14 — Existe cancelación parcial de respuestas obsoletas.** `pendingXhrs`/`cancelPending` (`level-cascade.js:12-30`) aborta `/nivel` y `/grafica` en toggles y popstate. **Hueco:** `/grafica` re-emite `#ejercicios-row` y una respuesta `/nivel` posterior con `seleccionados=[]` puede pisar el `aria-pressed` de la fila (no hay re-marcado tras swap de `#ejercicios-row`, solo de `#cascade-row`, `level-cascade.js:207-211`).

### 4.2 Hipótesis (no verificadas aún)

- **IP1:** `Plotly.react` sobre nodo persistente elimina el parpadeo sin CSS adicional (el fade `chartFadeIn` no se re-dispara en un nodo no recreado; `react` transiciona internamente). Verificar en e2e midiendo blancos (`test_plotly_newplot_once_react_always`).
- **IP2:** `Plotly.react` sobre un nodo previamente `purge`-ado (transición datos→vacío→datos) funciona sin reinicializar layout de cero. Verificar en e2e roundtrip vacío↔datos.
- **IP3:** htmx procesa OOB con `outerHTML` de un `<script type="application/json">` (inerte) sin ejecutarlo y dispara `htmx:load` sobre él. Verificar en e2e (el patrón ya se usa con `#app-config`, `response_fragments.py:112-127`).

### 4.3 Separación de responsabilidades (objetivo)

- `/nivel` → catálogo (filas) y detalle. Nunca gráfica.
- `/grafica` → targets de gráfica exclusivamente. Nunca filas ni resumen.
- Ninguna respuesta emite el mismo target OOB dos veces; las respuestas obsoletas se abortan o se vetaron antes del swap.

## 5. Alcance

Archivos permitidos: `app.py`, `src/response_fragments.py`, `src/charts.py` (solo para la matriz de series), `src/dashboard_service.py`, `static/js/chart-interaction.js`, `static/js/level-cascade.js`, `static/css/cascade.css`, `templates/index.html`, `templates/ejercicios_row.html`, `templates/exercise_detail.html`, tests unitarios/integración/E2E del dashboard. Se añade la actualización de `docs/architecture/current-ui-contract.md` (obligación de `backend-standards.md` §10: un contrato cambiado sin documento actualizado es un defecto). Nuevo template `templates/history_empty.html` (o bloque dentro de `exercise_detail.html`, ver T6) para el estado vacío del detalle.

## 6. Fuera de alcance

`/registro` (nueva página), retiro del popup, formularios compactos, rediseño de alimentación, cardio como serie analítica, granularidad día/semana/mes (el default `week` se conserva y se pinea en tests), tabla de resúmenes por periodo (`#period-summary`), rutas CSV, migraciones, nuevas dependencias, Health Connect, `/splits`. Cada aparición como dependencia se registra como trabajo posterior (Recuperaciones 2-5 del gap-doc).

## 7. Contrato funcional objetivo

- Un clic en músculo o ejercicio produce una única actualización visual de la gráfica, sin área en blanco ni cambio de `offsetTop`/altura.
- El nodo `#unified-chart-plot` permanece en el DOM durante toda la sesión.
- El detalle del ejercicio seleccionado se carga automáticamente en `#history-section`; sin botón `ⓘ`.
- La gráfica y el detalle se actualizan por rutas/targets disjuntos (nunca una respuesta sobrescribe la otra).
- El estado (músculos/ejercicios) se restaura desde URL en reload, back y forward.
- Errores nunca silenciados con `except Exception: pass`.

## 8. Matriz global/músculo/ejercicio (contrato objetivo de `src/charts.py:chart_selection`)

| Estado (entrada) | Trazas | Estilo | Cambio vs. actual |
|---|---|---|---|
| 0 músculos, 0 ejercicios (**global**) | 1: línea sistémica ("Crecimiento") | sólida `primary`, w2.5, marker 8 | **Corrige H12** (hoy figura vacía) |
| 1 músculo, 0 ejercicios (**muscular**) | 2: "Global" + "Compilado" | Global sólida; Compilado sólida `primary` w2.5 | **Cambio de contrato** (hoy 1 traza "Compilado") |
| 1 músculo, N ejercicios válidos (**ejercicio**) | N+1: "Compilado" (guía) + ejercicios | Compilado sólida; ejercicios alpha 0.4, w3.5, marker 6 | Sin cambios (contrato actual) |
| 1 músculo, ejercicio ajeno | Se descarta (no aparece) | — | Sin cambios (H: charts.py:255-264, testeado) |
| 2+ músculos | 1 "Global" + N músculos | Global sólida; músculos alpha 0.4 | Sin cambios |
| Sin datos (incl. "Cardio" virtual) | `chart-empty` | — | Sin cambios |

**Decisión D2 (resuelta con evidencia):** en estado ejercicio la línea global **se oculta**. Fuentes: `current-ui-contract.md:310` (matriz actual N+1 = compilado + ejercicios, sin global) y gap-doc §3 ("músculo guía + ejercicios"). No es bloqueo; queda documentada.

**Decisión D1 (impuesta por el prompt + gap-doc):** en estado muscular la línea global permanece visible, incluso con 1 solo músculo. Implica actualizar `test_chart_muscle_exercises_compilado_solo` y las filas de `test_chart_semantics_decision_matrix`.

## 9. Contrato de endpoints y OOB

### `GET /nivel` (responsabilidad: catálogo + detalle; NUNCA gráfica)

| Llamada | Contenido | Target |
|---|---|---|
| `?tipo=musculo` (sin foco) | fila de músculos (`cascade_row.html`) | `#cascade-row` |
| `?tipo=musculo&foco=<m>` + `ejercicios=<lista-comas>` (**nuevo param**) | fila de ejercicios con `aria-pressed` servidor-side (`ejercicios_row.html`) | `#ejercicios-row` |
| `?tipo=ejercicio&foco=<e>` | detalle (`exercise_detail.html`) | `#history-section` |
| `?tipo=ejercicio` (sin foco) (**nuevo**) | placeholder de detalle (estado vacío diseñado) | `#history-section` |
| `?tipo=global` | fila de músculos únicamente (**se retira el OOB de gráfica**, H2) | `#cascade-row` |

Cambios: `nivel_view` acepta `ejercicios: list[str]` (claves repetidas) para renderizar `seleccionados`; la rama `tipo=ejercicio` sin foco renderiza el placeholder; se elimina `chart_oob_wrapper` de la rama `global`.

### `GET /grafica?musculos=&ejercicios=&gran=` (responsabilidad: gráfica; targets únicos)

OOB emitidos (todos `outerHTML` salvo nota, vía builders nuevos en `response_fragments.py`):
- `#unified-chart-header` (título + "Ciclo N").
- `<script id="unified-chart-data">` (JSON de la figura, escapado con `_json_for_inline`).
- `#unified-chart-empty` (`hidden` si hay datos; texto "Sin datos" / "Sin datos para esta selección" según contexto).

**Retirados de `/grafica`:** OOB `#ejercicios-row` (H3) y OOB `#period-summary` (decisión D5). `#unified-chart` y `#unified-chart-plot` **nunca** son target de swap. Selección vacía → `chart_selection([], [])` → sistémica (D3).

**Nuevos targets allow-list** en `OOB_FRAGMENT_TARGETS`: `"unified-chart-header"`, `"unified-chart-data"`, `"unified-chart-empty"`. Se retiran `"unified-chart"` y `"period-summary"` (sin emisores tras la refactorización) y se elimina `chart_oob_wrapper`.

### Tabla de emisiones (invariante)

| Ruta | Targets que puede emitir | Prohibido |
|---|---|---|
| `/nivel` | `cascade-row`, `ejercicios-row`, `history-section` | cualquier target de gráfica |
| `/grafica` | `unified-chart-header`, `unified-chart-data`, `unified-chart-empty` | `ejercicios-row`, `history-section`, shell |

## 10. Estrategia de persistencia del nodo Plotly

**Alternativa A (seleccionada — viable y es la intención de `archive/2026-08-17-dashboard-chart-transition.md` §5.1):**

1. **Shell permanente** en `#unified-chart` (inmutable, sin swap): `#unified-chart-header` + `<script id="unified-chart-data" type="application/json">` + `<div id="unified-chart-plot" class="plotly-graph-div">` + `<div id="unified-chart-empty" hidden>`. Todos presentes siempre, también en vacío (H13 deja de ser cierto; `chart_html` y `_chart_selection_html` se unifican en `dashboard_service.chart_shell_html(title, fig_json|None, empty_text)`).
2. **CLS 0:** exactamente un hijo de 450 px visible a la vez: `#unified-chart-plot` (altura en `cascade.css:27-30`) o `#unified-chart-empty` (misma altura, clase `chart-empty`); el otro lleva `hidden`. El cliente alterna `hidden` al cambiar vacío↔datos.
3. **Render disparado por el nodo de datos:** el listener de `htmx:load` se fija en `e.target.id === 'unified-chart-data'` (el script reemplazado), no en el plot (que ya no se reinserta). `renderUnifiedChart()` lee el JSON del script reemplazado y ejecuta sobre el MISMO `#unified-chart-plot`.
4. **Vacío:** JSON sin `data` → `Plotly.purge(plotEl)` (si Plotly está cargado), `plotEl.hidden = true`, `emptyEl.hidden = false`, y **no** se llama `loadPlotly()` (mantiene `test_lazy_plotly_no_request_on_empty_chart` en su espíritu, con la actualización de H13).
5. **Datos:** `emptyEl.hidden = true`, `plotEl.hidden = false`, `Plotly.react(plotEl, fig.data, fig.layout, {displayModeBar:false})`.
6. **`plotly_click` una vez por nodo:** `WeakSet` de nodos vinculados en lugar del flag global (H5); al ser el nodo persistente, el binding efectivo ocurre una sola vez; si defensivamente el nodo se reemplazara, se re-vincula.
7. **Obsolescencia (dos capas):** (a) `cancelPending()` aborta `/nivel` y `/grafica` en vuelo al emitir una nueva petición o en Escape/popstate (ya existe, se amplía a la petición de detalle); (b) **secuencia**: `let cascadeSeq` monótono; `htmx:beforeRequest` estampa `e.detail.xhr._seq = ++cascadeSeq` en cada petición de cascada; `htmx:beforeSwap` pone `e.detail.shouldSwap = false` si `xhr._seq < cascadeSeq` (veta el swap de la respuesta vieja antes de tocar el DOM).
8. **Fade:** `chartFadeIn` queda como está (ya gateado con `prefers-reduced-motion`, `cascade.css:14-19`); con nodo persistente solo se reproduce en el primer montaje (IP1 a verificar).

Si la alternativa A fallara en validación (IP2/IP3 negativas), se documentaría la alternativa B (shell por `Content-Security`-amigable con `out-of-band` de solo el script) — no se asume.

## 11. Diseño de estado frontend y URL

- **Estado client:** `selectedMuscles: Set`, `selectedExercises: Set` (invariantes: los ejercicios seleccionados deben pertenecer al músculo; el servidor descarta ajenos, D8). `cascadeSeq` para obsolescencia.
- **URL (historial):** se mantiene `?musculos=A,B&ejercicios=a,b` (comas, D6 — contrato estable, e2e existentes lo verifican). **Requests:** claves repetidas (`musculos=A&musculos=B`), compatibles con FastAPI `list[str]`.
- **Flujo de acciones:**
  - Clic músculo (simple): `selectedMuscles = {m}`, `selectedExercises = {}` → `refreshExerciseRow()` (/nivel musculo+foco+ejercicios), `refreshChart()` (/grafica), `refreshDetail()` (/nivel tipo=ejercicio sin foco → placeholder), `pushState`.
  - Shift+click músculo: toggle en el Set (si queda vacío → flujo deselección).
  - Clic ejercicio: `selectedExercises = {e}` → `refreshChart()`, `refreshDetail(foco=e)` (D7: el detalle muestra el último ejercicio clickeado).
  - Shift+click ejercicio: toggle; tras quitar el último ejercicio → `refreshDetail()` placeholder.
  - Escape / re-clic del único músculo: `deselectAll()` → `/nivel?tipo=musculo` (fila) + `/grafica` vacío (sistémica) + placeholder detalle + `pushState('/')`. **El cliente deja de usar `/nivel?tipo=global`** (H2 resuelto).
  - `restoreFromURL()` (init/popstate): además de fila + gráfica, restaura `#ejercicios-row` con `aria-pressed` (el servidor la renderiza con `ejercicios`) y `refreshDetail()` del último ejercicio si la URL los trae.
- **Estados de UI:** detalle con placeholder diseñado ("Selecciona un ejercicio para ver su detalle" — server-rendered, sin strings HTML en JS); gráfica vacía (`.chart-empty`) y con datos; indicadores `htmx-indicator` existentes.

## 12. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `src/dashboard_service.py` | `chart_shell_html` (unifica `chart_html`/`_chart_selection_html`: header+data+plot+empty siempre presentes); `_chart_header_html` pasa a elemento con id `unified-chart-header` |
| `src/response_fragments.py` | builders `chart_header_oob`, `chart_data_oob` (script outerHTML, JSON escapado), `chart_empty_oob`; allow-list actualizada; retirar `chart_oob_wrapper` |
| `app.py` | `nivel_view` (sin OOB gráfica; `ejercicios` param; placeholder detalle); `grafica_view` (targets gráfica únicos, selección vacía→sistémica, sin `except Exception: pass`) |
| `src/charts.py` | `chart_selection` según matriz §8 (0 músculos→sistémica; 1 músculo→Global+Compilado) |
| `static/js/chart-interaction.js` | render por `#unified-chart-data`; WeakSet bind; purge/empty toggle; seq |
| `static/js/level-cascade.js` | `refreshDetail`, placeholder, `ejercicios` en /nivel, seq en beforeRequest/beforeSwap, `deselectAll`/`loadMuscles` sin `tipo=global` |
| `static/css/cascade.css` | exclusión visual plot/empty (hidden), ajustes CLS del shell persistente si aplican |
| `templates/index.html` | shell permanente con empty + placeholder `#history-section` |
| `templates/exercise_detail.html` | estado vacío (placeholder) cuando no hay `ejercicio` |
| `templates/ejercicios_row.html` | sin cambios funcionales (verificar marcas server-side) |
| `tests/test_app.py`, `tests/test_charts.py`, `tests/e2e/test_dashboard_flow.py`, `tests/e2e/test_accessibility.py` | ver §14 |
| `docs/architecture/current-ui-contract.md` | §1 (`/nivel`, `/grafica`), §2 (targets OOB), "Semántica de series de la gráfica" (matriz §8) |

## 13. Tareas atómicas ordenadas

- **T1** — Servidor: shell persistente. `chart_shell_html` en `dashboard_service.py`; builders OOB en `response_fragments.py`; `index.html` con el shell + placeholder detalle. *Prueba:* `test_index_serves_initial_muscles_noscript_and_seo` adaptado (shell completo presente).
- **T2** — `/grafica` conforme al contrato §9: targets únicos, selección vacía → sistémica, `#ejercicios-row` y `#period-summary` retirados, `except Exception: pass` eliminado. *Pruebas:* reescribir `test_grafica_multi_traza_oob`, `test_grafica_multimusculo_global_y_sin_fila_ejercicios`; nuevo `test_grafica_seleccion_vacia_sistemica`.
- **T3** — `/nivel` conforme: sin OOB de gráfica (`tipo=global` → solo fila), param `ejercicios[]`, placeholder `tipo=ejercicio` sin foco. *Pruebas:* actualizar `test_nivel_cascada_grupo_musculo_ejercicio`; nuevos asserts "sin `hx-swap-oob` de gráfica".
- **T4** — Matriz de series (`src/charts.py`). *Pruebas:* `test_charts.py` actualizado + casos nuevos (ver §14.1).
- **T5** — `chart-interaction.js`: render por data-node, WeakSet, purge/empty, seq. *Pruebas:* e2e §14.3 (11, 12).
- **T6** — `level-cascade.js`: detalle automático, placeholder, secuencia/veto, restauración URL. *Pruebas:* e2e §14.3 (4, 6, 7, 8, 10).
- **T7** — CSS: exclusión visual plot/empty y estabilidad del shell (regresión en e2e §14.3 9).
- **T8** — Templates: `exercise_detail.html` estado vacío; `ejercicios_row.html` verificación de `aria-pressed`.
- **T9** — Tests backend actualizados + nuevos (unit/integración).
- **T10** — Tests e2e nuevos/actualizados (dashboard_flow + accessibility).
- **T11** — `current-ui-contract.md` (sección 12) y, si aplica, `AGENTS.md`/gap-doc.
- **T12** — Gates completos: `uv sync --locked` (cache en `.tmp/`), `pytest` completo, `ruff format --check .`, `ruff check .`, `mypy app.py src tests`, cobertura módulos (`scripts/check_module_coverage.py src/charts.py src/dashboard_service.py --min 90`), `scripts/audit_consistency.py`, y `./scripts/build_css.sh` si cambió CSS (el cambio es mínimo; verificar igualmente).

## 14. Plan de pruebas

Entorno (cache dentro del proyecto, sandbox):

```bash
UV_CACHE_DIR=.tmp/uv-cache uv sync --locked
UV_CACHE_DIR=.tmp/uv-cache uv run pytest --ignore=tests/e2e
UV_CACHE_DIR=.tmp/uv-cache uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
UV_CACHE_DIR=.tmp/uv-cache uv run pytest tests/e2e/test_accessibility.py -q --no-cov
```

### 14.1 Backend (unit/integración)

1. `/nivel?tipo=musculo&foco=...` **no** emite OOB de gráfica (assert `hx-swap-oob` ausente) — actualiza `test_nivel_cascada_grupo_musculo_ejercicio`.
2. `/grafica` emite únicamente `unified-chart-header` + `unified-chart-data` + `unified-chart-empty`, nunca `#unified-chart`/`#ejercicios-row`/`#period-summary` — reescribe `test_grafica_multi_traza_oob`/`test_grafica_multimusculo_*`.
3. Matriz §8 parametrizada: `test_chart_semantics_decision_matrix` actualizado (1 músculo → `["Global","Compilado"]`; 1 músculo+ejercicio → `["Compilado","Press Convergente"]`; 2+ → `["Global",...]`; ajeno → descartado) + nuevo caso 0 músculos → `["Crecimiento"]` + vacío sin datos → 0 trazas.
4. Ejercicios incompatibles: se descartan (test existente, mantener).
5. Detalle: `/nivel?tipo=ejercicio&foco=` sigue sirviendo tablas; `/nivel?tipo=ejercicio` (sin foco) sirve el placeholder; `test_nivel_foco_desconocido_no_rompe` sin regresión.

### 14.2 JavaScript (vía e2e)

1. Primer render con datos: `Plotly.newPlot` como máximo una vez (patch en `page.evaluate` tras carga: contadores en `window.__plotlyCalls`).
2. Renders posteriores: solo `Plotly.react`; mismo `#unified-chart-plot` (identidad capturada en `window.__plotNode` y comparada tras selecciones).
3. Sin listeners `plotly_click` duplicados: clic en punto tras varias selecciones sigue abriendo `/registro` (extiende `test_week_click_opens_registro_en_primer_entreno` con una selección previa de músculo+ejercicio).
4. Clic rápido (músculo A → músculo B sin esperar): el estado final corresponde a B (veto por seq).
5. Restauración URL: reload (ya existe), back **y forward** (extiende `test_grafica_atras_del_navegador_restaura`).
6. `#unified-chart-data` con JSON vacío → sin petición a Plotly (actualiza `test_lazy_plotly_no_request_on_empty_chart` a H13: el script existe con `{"data":[]}` y el empty visible).

### 14.3 E2E (14 ítems exigidos)

1. **Carga inicial global** — actualizar `test_empty_state_chart` (empty dentro del shell persistente) + assert 1 traza "Crecimiento" con datos.
2. **Selección de 1 músculo** — `test_cascade_musculo_persistente_y_multi_traza` (matriz: 2 trazas Global+Compilado; `aria-pressed` de la fila servido por `/nivel`).
3. **Selección múltiple de músculos** — `test_multimusculo_con_shift_click_mantiene_global` (3 trazas; sin cambios salvo verificación de targets OOB).
4. **Selección de 1 ejercicio** — `test_cascade_musculo_persistente_y_multi_traza` (compilado + ejercicio).
5. **Selección múltiple de ejercicios** — `test_multiejercicios_con_shift_click`.
6. **Detalle automático** — **nuevo** `test_exercise_detail_auto_load`: clic en ejercicio → `#history-section` con "Resumen por Sesión" del ejercicio; deselección → placeholder.
7. **Escape / deselección** — `test_muscle_toggle_y_escape_vuelven_al_cuerpo_completo` (añadir: placeholder detalle + gráfica sistémica vía `/grafica` vacío).
8. **Back/forward** — extender el test existente con forward y con detalle restaurado.
9. **Altura y `offsetTop`** — `test_cls_stable_shell_and_history` extendido: `offsetTop` y altura de `#unified-chart-container`, `#unified-chart` y `#history-section` antes/después de seleccionar músculo, ejercicio y cargar detalle (Δ ≤ 1 px).
10. **Conteo de respuestas OOB** — **nuevo** `test_oob_targets_single_emission`: intercepta respuestas; cada respuesta emite cada target OOB a lo sumo una vez; `/nivel` nunca emite targets de gráfica y `/grafica` nunca filas/detalle.
11. **`newPlot` vs `react`** — nuevo test (14.2.1-2).
12. **Estado sin datos** — roundtrip vacío→datos→vacío con nodo persistente (extiende `test_lazy_plotly_single_request_and_shell_stable` y `test_lazy_plotly_no_request_on_empty_chart`).
13. **Viewport desktop y móvil** — `test_mobile_viewport_renders` extendido: cascada, gráfica y detalle en 375 px sin overflow horizontal.
14. **Accesibilidad** — `test_axe_populated_chart` extendido (selección de músculo + ejercicio + detalle auditados); `test_axe_empty_dashboard` con el shell persistente; `test_wcag_contrast_critical_elements` (selector del empty → `#unified-chart-empty`).

## 15. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `Plotly.react` en nodo purgado (IP2) falla | Roundtrip vacío↔datos en e2e antes de cerrar T5; si falla, no purgar y usar `react` con `data:[]` más empty overlay |
| htmx no dispara `htmx:load` sobre el script de datos OOB (IP3) | Fallback: listener en `htmx:afterSwap` de `#unified-chart-data` (mismo detalle de `e.detail`) |
| Veto por seq rompe popstate (peticiones de restauración marcadas viejas) | `restoreFromURL` incrementa `cascadeSeq` antes de emitir; el popstate ya cancela pendientes |
| Regresión en tests que asumen shell innerHTML | Actualización explícita de T9/T10 antes de cerrar cada tarea; correr suite completa en T12 |
| `#unified-chart-empty`/plot simultáneos rompen CLS | Regla "un hijo visible" con `hidden`; verificado en e2e 9 y 12 |
| `except Exception: pass` reintroducido | Gate: grep `except Exception: pass` en `app.py`/`src` en T12 (solo se permiten los patrones sancionados con log) |
| Drift documental (H1 ya existía) | T11 obligatoria en el mismo cambio de contrato (backend-standards §10) |

## 16. Decisiones pendientes

**Ninguna bloqueante.** Decisiones tomadas con evidencia (todas documentadas en §4.1/§8): D1 (global visible en estado muscular), D2 (global oculta en estado ejercicio), D3 (selección vacía → sistémica), D4 (separación /nivel vs /grafica), D5 (**recomendada:** retirar `#period-summary` de `/grafica` y diferirlo a Recuperación 3 — si el usuario prefiere conservar el resumen, T2 lo mantiene con manejo de error real en lugar de `pass`), D6 (URL con comas), D7 (detalle = último ejercicio clickeado), D8 (ejercicios ajenos ignorados, no rechazados).

## 17. Criterios de aceptación verificables

1. `git diff` del plan implementado toca solo los archivos de §12; sin rutas/endpoints nuevos fuera del contrato §9; sin dependencias nuevas; sin migraciones.
2. E2E 1-14 verdes en `test_dashboard_flow.py` + `test_accessibility.py` (con `--no-cov`).
3. Suite unit/integración verde con cobertura ≥90 % (gate `addopts`), `ruff` y `mypy` limpios; `audit_consistency.py` verde.
4. `#unified-chart-plot` es el mismo nodo (identidad) tras ≥3 selecciones consecutivas (e2e 11).
5. Clic de ejercicio → `#history-section` con el detalle de ese ejercicio en ≤1 respuesta y sin botón `ⓘ` (e2e 6).
6. `#unified-chart-container`/`#history-section` sin cambio de altura ni `offsetTop` (>1 px) entre estados vacío/cargado/global/muscular/ejercicio (e2e 9).
7. Un clic de músculo o ejercicio = exactamente una actualización visual de la gráfica, sin blanqueo (e2e 10-11).
8. Sin `except Exception: pass` en `app.py` ni `src/` (grep en T12).
9. `current-ui-contract.md` refleja el contrato §9 y la matriz §8 (backend-standards §10).

## 18. Orden recomendado de implementación

T1 → T2 → T3 → T4 (backend + unit tests en paralelo) → T5 → T6 → T7 → T8 (frontend + e2e) → T9 → T10 → T11 → T12. T2 depende de T1; T4 es independiente de T1-T3 (puede ir en paralelo); T5-T6 requieren T1-T3 servidas. Ninguna tarea se declara completa sin su prueba §14 asociada.

## 19. Próximo plan posterior

**Recuperación 2 — Catálogo izquierdo definitivo** (gap-doc §4): panel izquierdo como catálogo navegable tipo `/splits` (agrupación estable, selección/expansión sin cambio de altura de la columna analítica, scroll interno, responsive, teclado). Después: Recuperación 3 (granularidad + tabla de periodos, que retomará `#period-summary` y el default `day`), Recuperación 4 (`/registro`), Recuperación 5 (decisión del popup).
