# Current Dashboard UI Contract

> **Referencia actualizada:** el contrato funcional y visual vigente del dashboard está en
> [`dashboard-current.md`](dashboard-current.md). Este documento conserva contratos históricos
> de rutas y componentes que siguen siendo relevantes durante la migración. Cuando una sección
> antigua contradiga `dashboard-current.md`, prevalece `dashboard-current.md`.

> **Purpose:** Behavioural contract of the live application (legacy contract v3, cascada de
> niveles). Any intentional change to IDs, `data-*` attributes, form field names, htmx
> targets or `hx-swap-oob` markers documented here requires its own browser test and a
> contract-change commit.
>
> **Baseline suite:** `uv run pytest -q` (unidad + integración + e2e Playwright, cobertura
> ≥ 90 %) y gates `ruff` + `mypy`. El conteo exacto de tests no es parte del contrato.

---

## 1. Rutas y su contrato

### `GET /` (index, HTML completo)

- Renderiza `index.html` (extends `base.html`).
- Sirve server-side: header (título, botón Registrar),
  **fila inicial de músculos** (`#cascade-row`, chips `data-action="select-muscle"`),
  gráfica sistémica (`#unified-chart` con `#unified-chart-data` JSON + `#unified-chart-plot`),
  `#history-section` vacío, `<noscript>` y los partials
  globales (`#notice-container` role=status, `#confirm-modal` dialog, `#app-config`).
- `#app-config` (script `type="application/json"`, inerte): `categoria_map`,
  `alimento_map`, `ciclo_start`, `csrf_token` (firmado con `GYM_CSRF_SECRET`).
- El popup de registro es un `<dialog id="editor-popup" aria-labelledby="popup-fecha-title">`.
- Assets versionados con `static_url(...)` (`?v=<sha256[:12]>`; `Cache-Control: immutable`
  solo con digest vigente).

### `GET /fecha/editor?fecha=<YYYY-MM-DD>`

- Fragmento `session_editor.html` (sin documento completo).
- Usado con `target: '#session-editor-wrap'`, `swap: 'innerHTML'`.
- Marcadores de estado: `#editor-state[data-readonly][data-has-data]` (hidden).

### `GET /editor/popup?fecha=<YYYY-MM-DD>`

- Cuerpo del popup de registro: `editor_popup.html` (navegador de fechas + título +
  alimentación + editor de sesión + cardio + plantillas).
- Incluye `#editor-notice` (role=status, aria-live) y `#save-outcome[data-ok]` (hidden).
- Cargado por `editor-popup.js` con `htmx.ajax(target: '#popup-body')`; el popup se abre
  con `showModal()` y la fecha viaja en `?registro=<iso>` (historial).

### `GET /cardio/day?fecha=<YYYY-MM-DD>`

- Fragmento del panel de cardio de la fecha (`cardio_day.html`), usado por
  `date-navigation.js` (`doNav`) para refrescar `#cardio-day` al navegar fechas dentro
  del popup (sin esto, el panel queda con el día de apertura).
- Mismo contenido que el bloque `#cardio-day` del popup; `POST /cardio/annotation`
  responde OOB `#cardio-day` (outerHTML) tras guardar.

### `POST /entrenamiento/session/save`

- Campos: `fecha` (ISO), `ejercicio[]`, `kg[]`, `reps[]`, `rir[]`, `descanso[]`
  (arrays paralelos; form `#session-form`, `hx-swap="none"`).
- OOB éxito: `#editor-notice` (success, `data-dismiss="3000"`), `#save-outcome`
  (outerHTML, `data-ok="1"`), y `#editor-state` o `#session-editor-wrap` según filas.
- OOB error de dominio (400): `#editor-notice` (error, `data-dismiss="4500"`),
  `#save-outcome` (`data-ok="0"`).
- Gating cliente: submit interceptado si `#session-editor[data-editmode] !== '1'`.
- Efectos: backup pre-mutación, journal `undo_entries` (kind `sesion`, solo `before`).

### `POST /entrenamiento/session/eliminar`

- Campo: `fecha` (ISO). Disparado por `eliminarSesion()` tras confirmación.
- OOB: `#editor-notice` ("Entreno eliminado."), `#save-outcome` (`data-ok="1"`),
  `#session-editor-wrap` (editor readonly fresco).
- Efectos: backup + journal (`sesion`).

### `GET /nivel?tipo=<global|musculo|ejercicio>[&foco=]`

- Cascada de niveles:
  - `tipo=musculo` sin foco → fila de músculos (`cascade_row.html`, chips
    `data-action="select-muscle"`).
  - `tipo=musculo` con foco → `ejercicios_row.html` (chips `data-action="toggle-exercise"`,
    `aria-pressed`) + OOB `#unified-chart` (compilado del músculo).
  - `tipo=ejercicio` con foco → `exercise_detail.html` en `#history-section`.
  - `tipo=global` → fila de músculos + OOB gráfica sistémica.
- Selección múltiple con Shift+click; `Escape` deselecciona (salvo popup abierto);
  historial `?musculos=A,B&ejercicios=a,b` con popstate.

### `GET /grafica?musculo[]=&ejercicios[]=`

- OOB `#unified-chart` (innerHTML) con el compilado de la selección: 1 músculo →
  compilado + ejercicios; 2+ → global + músculos. Con 1 músculo también OOB
  `#ejercicios-row` (outerHTML).
- El fragmento usa el mismo shell que `chart_html` (header h2 + `chart-empty`/plot 450px).

### `GET /semana/primer-entreno?semana=<n>`

- JSON `{"fecha": "<iso>"|null}`: primera fecha de entrenamiento de la semana del ciclo.
- Consumido por `chart-interaction.js` al hacer clic en un punto: abre el popup en esa
  fecha. `response.ok` exigido; un reintento para fallos transitorios; aviso de error
  si persiste.

### `POST /cardio/annotation`

- Campos: `hc_id`, `velocidad_kmh`, `inclinacion_pct`, `notas`, `fecha`.
- Upsert de anotación sobre una sesión `EXERCISE_SESSION` espejada; anotación vacía se
  elimina. OOB de aviso vía `#notice-container`.
- El submit del popup convierte `FormData` a objeto plano (htmx no serializa FormData
  como `values`) y omite los campos vacíos (`float | None = Form(None)`).

### `POST /ejercicio/nuevo`

- Campos: `ejercicio`, `grupo_muscular`, `categoria` (form `#exercise-create-form`,
  `hx-swap="none"`).
- OOB: `#notice-container` (success/error), y en éxito `#exercise-create` (outerHTML)
  + `#app-config` (outerHTML, `alimento_map` no afecta pero `categoria_map` sí).
- Errores: nombre vacío / grupo faltante / categoría inválida / ejercicio duplicado.

### Plantillas de entrenamiento

- `GET /plantillas[?editar=<id>]` → fragmento `plantillas_list.html`
  (`target: '#plantillas-section'`). Tarjetas `#plantillas-list .pt-card[data-pt-id]`
  con acciones Aplicar/Editar/Eliminar; se reordenan arrastrando el cuerpo de la tarjeta.
- `POST /plantilla/guardar` — `nombre`, `ejercicio[]` (hidden sync). OOB
  `#notice-container` + `#plantillas-section` (outerHTML). Journal (`entrenos`).
- `POST /plantilla/editar/{id}` — mismo patrón; error conserva `editing_id`.
- `POST /plantilla/eliminar/{id}` — confirmación nativa (`#confirm-modal`).
- `POST /plantilla/reordenar` — `id[]` (orden completo). Enviado vía
  `persistOrderWithHtmx` (htmx + CSRF); fallo → restaura el DOM y avisa.
- `GET /plantilla/aplicar/{id}?fecha=` — exige modo edición; confirmación de reemplazo
  si el día tiene datos; OOB `#editor-notice` + `#session-editor-wrap`
  (con marcador `#plantilla-applied` para el dirty-baseline).
- Reordenamiento **solo con ratón** (decisión explícita del usuario; desviación de WCAG
  2.1.1 documentada en `web-standards.md`): tarjetas y filas de editor se arrastran desde
  cualquier parte no-control de la fila (el `dragstart` de las tarjetas excluye
  `input/select/button`; Sortable de filas filtra esos mismos controles). El Sortable de
  filas está **siempre activo**: si el editor está en solo lectura (día con datos), el
  `onStart` entra solo en modo edición para que el reorden persista al guardar. En las
  tarjetas, el `dragend` persiste el orden completo vía `persistOrderWithHtmx` y, ante
  fallo, restaura el DOM y avisa.

### Plantillas de alimentación

- `POST /alimentacion/plantilla/guardar` — `nombre`, `alimento[]`, `cantidad[]`.
- `POST /alimentacion/plantilla/eliminar/{id}`, `POST /alimentacion/plantilla/reordenar`
  (`id[]`), `GET /alimentacion/plantilla/aplicar/{id}?fecha=` (OOB
  `#nutrition-editor-wrap` + aviso).
- Aplicar es un `<button data-action="apply-meal-template">`; confirmación de reemplazo
  si el día tiene filas (el editor de nutrición es siempre editable).

### Alimentación

- `GET /alimentacion/editor?fecha=` → fragmento `nutrition_editor.html`.
- `POST /alimentacion/save` — `fecha`, `alimento[]`, `cantidad[]`, `peso_kg`,
  `factor_proteina`, `factor_grasa`, `kcal_objetivo`. El servidor recalcula nutrientes
  contra el catálogo (`ROUND_HALF_UP(catálogo_100g × g / 100)`); nunca confía en el
  cliente. OOB `#nutrition-editor-wrap` + `#nutrition-date-navigator`.
- `POST /alimentacion/eliminar` — `fecha`.
- `POST /alimento/nuevo` — alta de alimento; OOB `#alimento-create` + `#app-config`.
- Tabla: `<caption>`, `scope="col"` en las cabeceras; filas `Objetivo`/`Consumido`
  en el `<thead>` (arriba de las filas, decisión visual del usuario) con `scope="row"`
  en sus celdas de etiqueta.

### `POST /undo`

- Campo: `fecha` (fecha actual del editor; puede ser vacía).
- OOB éxito: `#notice-container` ("Acción deshecha."); para `sesion` además
  `#undo-result` (outerHTML, `data-fecha`, `data-has-data`, hidden), `#save-outcome`
  (`data-ok="1"`) y `#session-editor-wrap` cuando se deshace la fecha actual; para
  `entrenos`: `#plantillas-section` (outerHTML); para `splits`: `#splits-section`
  (outerHTML).
- Pila vacía: `#notice-container` error "Nada que deshacer.".
- Efectos: backup pre-mutación; pop del journal `undo_entries` **solo tras un restore
  exitoso** (la entrada persiste si el restore falla).
- Accesible por Ctrl/Cmd+Z (nunca en campos de texto).

### Gestor de splits

- `GET /splits` → página completa (`splits.html`, extiende `base.html`; la
  página usa TODO el ancho disponible — sin `max-w-7xl`). **Layout de dos
  columnas** (`.splits-layout`): catálogo a la izquierda
  (`.splits-catalog-col`, `var(--split-catalog-w)` 280px, `position: sticky`
  con scroll propio; **sin título de panel**, solo buscador + grupos) y
  `#splits-section` a la derecha (`.splits-editor-col`). Móvil: una columna
  con el editor primero (CSS `order`) y el catálogo debajo. Header de página:
  título + `← Dashboard` + botón `data-action="split-new"` **Nuevo split**.
  `?abrir=<id>` valida el id y renderiza ese item ya expandido (modo vista).
- **`#splits-section`** contiene el **estado vacío** ("Todavía no hay splits
  guardados" + `data-action="split-new"` "Crear nuevo split") o
  `#splits-list` con **un item por split** (`partials/split_accordion.html` +
  `split_accordion_item.html`; `split_list.html` fue retirado). Cada item es
  un **acordeón** (`<details class="split-accordion">` nativo):
  - `<summary>`: chevron + nombre + **resumen semanal**
    `.split-summary-strip` (`role="region"` + `tabindex="0"`, `overflow-x:
    auto` con scrollbar fina; `N series · Grupo n · …` con totales en `strong`
    burdeos, orden por series desc). **La fecha de modificación NO se muestra**
    (`updated_at` se conserva en BD solo para ordenar; `_split_updated_short`
    fue retirado). Los controles viven FUERA del summary (evita que su
    activación alterne el `<details>`);
  - `.split-item-toolbar` (altura fija `--split-toolbar-h: 40px`): formulario
    por split (`hx-post="/split/guardar"`, hidden `split_id`, input `nombre`
    oculto en vista) + badges "Editando"/"Modificado" + **acciones como iconos
    agrupadas** `.split-item-actions` (`.split-action-btn` 28×28 con
    `aria-label`/`title`, focus-visible, `[disabled]` con el MISMO tamaño):
    lápiz (`split-edit`, toggle `aria-pressed` + clase **`.is-active`** cuando el
    modo edición está activo — se ilumina con acento + glow, sin texto ni badge
    "Editando"), guardar (`split-save`,
    **deshabilitado sin cambios locales o en item guardado**; `markDirty` lo
    habilita al mutar el board o teclear el nombre), papelera (`split-delete`,
    conserva `data-split-id`/`data-split-nombre` para el confirm);
  - `.split-accordion-content` (min-height `--split-expanded-height`) →
    `.split-board-scroll` (flex:1, `overflow-x: auto` SOLO aquí, fondo
    `matte-950` + `border-top`: bloque visualmente independiente) →
    `.split-columns`: grid **`repeat(7, minmax(var(--split-day-min-width),
    1fr))` con `width: 100%`** (estira a todo el ancho; sin hueco tras
    Domingo; scroll solo si el viewport no da) → **7 tarjetas de día**
    `.split-day-zone` de **dimensiones invariantes** (`--split-day-min-width:
    146px`, `--split-day-height: 620/580/560px` por breakpoint,
    `--split-summary-h: 260/240/220px`): header fijo (day-select
    `aria-pressed` + count), `.split-day-section-label` **"Resumen"**,
    `.split-day-summary` (altura fija, scroll interno) — **sin fila de total**
    (el total vive en el header de la tarjeta) —, `.split-day-section-label`
    **"Ejercicios"** con `.split-day-section-actions` (**copy-btn accesible**
    `.split-day-copy-btn` — click copia al día seleccionado — y clear-btn) y
    `.split-day-items` (flex:1, `min-height:0`, scroll interno). **Instancias:
    tamaño fijo** `--split-item-height: 28px` (`.split-item-card` y
    `.split-catalog-chip`) con botón `.split-item-remove` de
    `--split-item-action-size: 18px` **visual + hit area >= 24px** (WCAG 2.5.8
    vía `::before`) que se oculta con `visibility: hidden` en vista (reserva su
    espacio: la tarjeta nunca cambia de tamaño). **Scrollbars internas
    delgadas**: `--split-scrollbar-size: 3px` (summary/items/board/strip/
    catálogo; thumb `overlay-white-014` redondeado; best-effort en Firefox y
    overlay de macOS). Tamaños SOLO vía variables canónicas en `:root`.
- **Resumen jerárquico por tarjeta** (server-rendered, recalculado al
  guardar): por grupo un
  `button.split-summary-group-toggle[data-action="split-summary-toggle"]`
  con `aria-expanded`/`aria-controls` (ids únicos por item×día×grupo) y
  chevron; el body `.split-summary-group-body[hidden]` anida los ejercicios
  con sus series (`SplitDaySummary.by_group_exercises` por día). Grupos
  inician colapsados; la expansión NO cambia el tamaño de la tarjeta (scroll
  interno). **No hay fila de total** (redundante con el header de la
  tarjeta). El resumen semanal de la cabecera se actualiza en la preview
  client-side (`rebuildStrip`: total + grupos desc).
- `GET /split/nuevo` → fragmento del **item de un split nuevo** (vacío, sin
  persistir, `data-editmode="1"`, 7 tarjetas). GET puro sin efectos; el JS lo
  inserta al tope de `#splits-list` (creándola si había estado vacío) y solo
  persiste al Guardar. `split_list.html` retirado; **la ruta
  `GET /split/{split_id}` fue retirada** (los boards viven dentro de la
  sección; 404).
- `POST /split/guardar` — igual que v3 (arrays alineados `dia[]`/`item_type[]`/
  `ejercicio[]`, servidor autoritativo, upsert por nombre, límite 300,
  mínimo 1 ejercicio, renumera `orden`). OOB: `#notice-container` +
  `#splits-section` (outerHTML). `POST /split/eliminar/{split_id}`: idem
  (confirmación `#confirm-modal`).
- **Modo visualización / edición por item**: un split guardado renderiza
  `data-editmode="0"` (sin `.row-btn`/copy-handle/clear-btn/input/Guardar,
  tarjetas `draggable=false`, sortables deshabilitados, **`pointer-events:
  none` en `.split-day-items`** — el board en vista no es destino de drop
  ni siquiera para el DnD nativo HTML5). "Editar" togglea a
  `data-editmode="1"` (+ badge "Editando", borde burdeos en las tarjetas,
  `aria-pressed` en el botón). Toda mutación marca `dirty` ("Modificado").
- **Borrar día**: `data-action="split-day-clear"` por día (visible solo en
  edición) con confirmación; vacía solo ese día, recalcula preview + total
  semanal y marca modificado; el servidor lo aplica al Guardar.
- Regla de negocio: **1 instancia = 1 serie**. `SplitMetrics` cubre los 7
  días (vacíos con 0) y expone `total_series`, `by_group`, `by_exercise`,
  `by_group_exercises` (semanal y por día vía `SplitDaySummary`) y `days`.
  Sin "Días activos" ni "Ejercicios distintos"; el panel ledger semanal
  (`#split-summary-panel`) fue retirado (cabecera + resúmenes por tarjeta).
- **REGLA CENTRAL DEL DnD**: **arrastre normal = MOVER; Shift + arrastre =
  COPIAR; solo el catálogo clona automáticamente** (`pull:'clone'` SOLO en
  `buildCatalogSortable`; los días usan `pull:true` = movimiento real, sin
  `cloneNode` en movimientos normales — criterio: 10 instancias antes de mover
  = 10 después, solo cambia día/posición).
- **SortableJS con `forceFallback: true` + `fallbackOnBody: true` +
  `fallbackClass: 'split-fallback'`** (días y catálogo; el catálogo añade
  `removeCloneOnHide: true` y `revertClone: true`). Las tarjetas/chips **no
  llevan `draggable`** (con forceFallback, `draggable=true` hace que el drag
  nativo HTML5 secuestre el arrastre y el fallback quede en `chosen` sin
  arrancar). El ghost está estilizado (`.split-day-items .sortable-ghost`:
  opacidad .35 + borde punteado) para que nunca se vea una segunda tarjeta
  opaca tras el cursor. **Shift se excluye con `filter` FUNCIÓN**
  (`e.shiftKey || target.tagName === 'BUTTON'`) → jamás coexisten mover y
  copiar; la tecla decide el modo desde el inicio.
- **Item**: arrastre normal mueve; Shift duplica vía drag por puntero propio
  (mousedown captura + seguimiento + inserción por Y en la posición exacta).
- **Día completo (header)**: todo el `.split-day-header` (nombre + series +
  área libre, `cursor: grab`) es el área de arrastre con **umbral de
  movimiento** (5px: el clic en el day-select sigue seleccionando; derivar el
  día NO inicia el drag accidental). Sin Shift **MUEVE** el bloque (re-parenta
  las tarjetas sin `cloneNode`, `dia` destino, orden conservado, destino
  intacto: inserción por mitad de tarjeta si cae sobre la lista, **append si
  cae sobre el header**); con Shift **COPIA** (`cloneNode` + `finalizeCard`,
  `+N`, notice). Guardas de límite ANTES de tocar el DOM (rechazo → origen
  intacto); día origen vacío → notice breve y no arranca. Alternativa
  accesible: `.split-day-copy-btn` (click → copia al día seleccionado).
- **Listeners delegados + snapshot/restore (A1/B1)**: `splits.js` re-sincroniza
  `split_id`/`max_items`/`editmode`/`nombre` tras cada OOB de `#splits-section`
  (snapshot en `htmx:beforeRequest`, restore en `htmx:oobAfterSwap`; los items
  con cambios no guardados conservan su DOM; los nuevos sin persistir se
  re-insertan al tope). Sin listeners duplicados tras swaps htmx.

### Exports

- `GET /exportar/health-connect.csv[?incluir_borrados=1]` → `health_records` activos
  (o con borrados para auditoría) ordenados `record_type, start_epoch_ms`, BOM.

### Semántica de series de la gráfica

La gráfica `#unified-chart` muestra trazas según el estado de selección
(`src/charts.py:chart_selection`). Contrato blindado con tests parametrizados
(`tests/test_charts.py:test_chart_semantics_decision_matrix`):

| Estado | Trazas | Estilo |
|---|---|---|
| **Global** (0 músculos) | 1: "Crecimiento" (sistema) | Sólida `primary` (`#e56d88`), width 2.5, marker 8 |
| **1 músculo**, 0 ejercicios | 2: "Global" + "Compilado" del músculo | Global sólida + Compilado sólida `primary`, width 2.5 |
| **1 músculo**, N ejercicios válidos | N+1: compilado + ejercicios | Compilado sólido; ejercicios `alpha=0.4`, width 3.5, marker 6 |
| **1 músculo**, ejercicio ajeno | Se descarta (no aparece) | — |
| **2+ músculos** | 1 global + N músculos | Global sólida; músculos `alpha=0.4`, width 3.5; ejercicios ignorados |
| **Cardio** (sin datos de entrenamiento) | "Sin datos para esta selección" | `chart-empty` |

Eje X = semana del ciclo; Y = "Crecimiento (%)" (rendimiento − 100, baseline semana 1 = 0);
hover unificado (series, fallos, volumen, peso, sueño).

### Sincronización LAN

- `POST /sync/health-connect` (API JSON, no htmx): autenticada con `X-Sync-Token`;
  exenta del CSRF de formularios por igualdad exacta de ruta; lotes ≤ 500 ops / 1 MiB;
  upsert por revisión + baja lógica; acuse individual. Contrato completo en
  `docs/architecture/health-sync-contract.md`.
- Gate LAN (`GYM_LAN_SYNC_ONLY=1`): remoto solo este POST; el resto de la UI remota es
  403/429 (ver `docs/architecture/security-model.md` §2.6).

### Rutas retiradas

- `GET /select`, `GET /grupo/reset`, `GET /ejercicio` **no existen** (404 desde la
  retirada de 2026-08-15). El cliente actual solo usa `/nivel` y `/grafica`.
- `GET /docs`, `/redoc`, `/openapi.json` deshabilitados (sin inventario público).

## 6. Vocabulario de componentes (2026-08-15)

Todo el styling vive en `static/css/components.css` sobre los design tokens; los
templates usan solo estas clases canónicas (las clases que el JS/tests usan como
hook se conservan como alias):

- **Botones:** `.btn` + `.btn-primary` (acción principal), `.btn-ghost`
  (Cancelar/Guardar de paneles), `.btn-outline` (+`.btn-outline-danger`) (acciones
  de tarjetas), `.btn-text` (enlace con borde). Alias compatibles: `.row-btn`,
  `.btn-x`, `.btn-check`, `.edit-toggle`, `.pt-btn`, `.today-btn`, `.nav-arrow`,
  `.rir-step`, `.collapse-chevron`.
- **Inputs:** `.cell-input`/`.cell-select` (celdas de tabla; +`.cell-input-sm` para
  parámetros), `.field-input` (+`.field-input-sm`) (formularios de alta).
- **Contenedores:** `.panel` (+`.panel-tight`/`.panel-default`/`.panel-spacious`),
  `.panel-title` (+`.panel-title-neon`, `.panel-title-divider`), `.card`.
- **Splits:** `.splits-page`, `.splits-page-header`, `.splits-layout`,
  `.splits-editor-col`, `.splits-catalog-col`, `.split-columns`,
  `.split-board-scroll`, `.split-day-zone` (+`.drop-target` durante el
  arrastre), `.split-day-header`, `.split-day-select`, `.split-day-count`,
  `.split-day-section-label`, `.split-day-section-actions`,
  `.split-day-summary`, `.split-day-items`, `.split-day-copy-btn`,
  `.split-day-clear-btn`, `.split-catalog-group`, `.split-catalog-summary`,
  `.split-catalog-body`, `.split-catalog-chip`, `.split-item-card`
  (+`.dragging`, `.copy-mode`), `.split-item-name`, `.split-item-remove`,
  `.split-fallback`, `.split-accordion-item`, `.split-accordion`,
  `.split-accordion-summary`, `.split-accordion-name`,
  `.split-accordion-chevron`, `.split-accordion-content`,
  `.split-summary-strip`, `.split-summary-strip-sep`, `.split-item-toolbar`,
  `.split-item-form`, `.split-item-actions`, `.split-name-input`,
  `.split-action-btn`, `.split-dirty-hint`,
  `.split-summary-row`, `.split-summary-total`, `.split-summary-name`,
  `.split-summary-group`, `.split-summary-group-toggle`,
  `.split-summary-group-body`, `.split-summary-exercise`,
  `.split-summary-chevron`, `.split-empty-state`, `.split-empty-state-title`,
  `.split-metric`, `.split-empty`.
- El gate `scripts/audit_consistency.py` (CI, `tests/test_ui_consistency.py`) prohíbe
  reintroducir utilidades de color inline, micro-tipografía y hex literales.

---

## 2. Contrato htmx / OOB

- Los markers OOB se generan con `src/response_fragments.py` (targets allow-listed);
  los avisos usan `partials/oob_notice.html` con `role="alert"` en errores.
- `htmx:beforeSwap` permite el swap en 4xx (respuestas propias de dominio); los 500 se
  mantienen sin renderizar.
- CSRF: `htmx:configRequest` inyecta `X-CSRF-Token` desde `#app-config`; el middleware
  valida token + Origin (`Host` header).

## 3. Diálogos y foco

- `#editor-popup` y `#confirm-modal` son `<dialog>` nativos (`modal-dialog.js`):
  `showModal`/`close`, foco inicial en el primer control, restauración de foco al
  origen, Escape cerrando solo el diálogo superior. Sin focus-trap manual.
- El popup conserva `?registro` en el historial; el popstate no reabre recursivamente
  (flag `suppressPopstate`).

## 4. Navegador de fechas

- Ventana de 31 días centrada en la selección, recortada a
  `[ciclo_start, fin del mes siguiente]`. Input date = salto preciso; flechas = ±15 días
  (ventana); HOY = salto al día actual. Flechas de teclado solo con foco dentro de
  `#date-navigator`. Puntos `.date-dot` = días con datos.

## 5. Estados de UI (siempre diseñados)

- Vacío: "Sin datos" / "Aún no hay entrenos" / placeholder del día.
- Carga: `htmx-indicator` en filas de la cascada; Plotly se carga bajo demanda
  (un único script SRI tras JSON de gráfica no vacío; fallo → aviso `role="alert"`).
- Error: notices `role="alert"`; éxito: regiones `role="status" aria-live="polite"`.
- El shell de la gráfica (header + 450px) no cambia entre vacío y cargado (CLS 0).
