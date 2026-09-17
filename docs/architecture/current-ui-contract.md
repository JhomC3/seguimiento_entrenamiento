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

> **Dashboard congelado (armonización Diario/Splits → Dashboard):** el Dashboard
> es la referencia visual y no se modifica. Archivos congelados:
> `templates/index.html`, `partials/dashboard_catalog.html`, `cascade_row.html`,
> `ejercicios_row.html`, `partials/period_summary_panel.html`,
> `static/css/cascade.css` y la variante `dashboard` del navegador de fechas.
> Los fragmentos compartidos con el popup (`session_editor.html`,
> `nutrition_editor.html`, `cardio_day.html`, `date_navigator.html`,
> `exercise/alimento_create_form.html`, `plantillas*_list.html`) solo admiten
> cambios aditivos con scope (`#daily-page …`, `.splits-*`) que no alteren el
> render del Dashboard. Pins en `tests/test_dashboard_freeze.py`: si fallan,
> el lote ha tocado el Dashboard y requiere consulta previa.
> Excepción 2026-09-10 (orden expresa): sin títulos de eje ni leyenda en las
> gráficas del dashboard (`src/charts.py`), con sus tests y este contrato
> actualizados en el mismo lote.
> Ajuste 2026-09-10 (orden expresa): gap de la columna central 24→12px y
> nutricional `clamp(140px,18vh,330px)` (+`25vh/400px` desde 1100px) para
> alinear su base con los paneles laterales sin scroll.

---

## 1. Rutas y su contrato

### `GET /` (index, HTML completo)

- Renderiza `index.html` (extends `base.html`).
- Sirve server-side: header (título, navegación común Dashboard/Diario/Splits
  vía `workspace_nav.html` con `aria-current` en la página activa),
  **fila inicial de músculos** (`#cascade-row`, chips `data-action="select-muscle"`),
  gráfica sistémica (`#unified-chart` con `#unified-chart-data` JSON + `#unified-chart-plot`),
  `#history-section` vacío, `<noscript>` y los partials
  globales (`#notice-container` role=status, `#confirm-modal` dialog, `#app-config`).
- `#app-config` (script `type="application/json"`, inerte): `categoria_map`,
  `alimento_map`, `ciclo_start`, `csrf_token` (firmado con `GYM_CSRF_SECRET`).
- El Dashboard no contiene botón Registrar ni popup de registro: es solo análisis.
  La captura de datos vive en `/diario`, la única pantalla canónica de registro.
- Assets versionados con `static_url(...)` (`?v=<sha256[:12]>`; `Cache-Control: immutable`
  solo con digest vigente).

### `GET /fecha/editor?fecha=<YYYY-MM-DD>`

- Fragmento `session_editor.html` (sin documento completo).
- Usado con `target: '#session-editor-wrap'`, `swap: 'innerHTML'`.
- Marcadores de estado: `#editor-state[data-readonly][data-has-data]` (hidden).

### `GET /diario?fecha=<YYYY-MM-DD>&vista=<entrenamiento|alimentacion>`

- Página completa del Diario: navegador compacto, selector de Entrenamiento/Alimentación,
  editor de la fecha, cardio y diálogos de plantillas/altas.
- `vista` es local a la página y por defecto es `entrenamiento`.
- `#date-navigator` usa el formato diario corto `dd/mm/aa`, sin etiqueta Semana.

### `GET /editor/popup?fecha=<YYYY-MM-DD>` (compatibilidad interna)

- Fragmento heredado para integraciones antiguas. No forma parte de la navegación ni de la
  experiencia visible del Dashboard; el Diario usa sus propios contenedores server-side.

### `GET /cardio/day?fecha=<YYYY-MM-DD>`

- Fragmento del panel de cardio de la fecha (`cardio_day.html`), usado por
  `date-navigation.js` (`doNav`) para refrescar `#cardio-day` al navegar fechas dentro
  del Diario (sin esto, el panel queda con el día de apertura).
- Mismo contenido que el bloque `#cardio-day` del Diario; `POST /cardio/annotation`
  responde OOB `#cardio-day` (outerHTML) tras guardar.

### `POST /entrenamiento/session/save`

- Campos: `fecha` (ISO), `ejercicio[]`, `kg[]`, `reps[]`, `rir[]`, `descanso[]`
  (arrays paralelos; form `#session-form`, `hx-swap="none"`).
- OOB éxito: `#editor-notice` (success, `data-dismiss="3000"`), `#save-outcome`
  (outerHTML, `data-ok="1"`), y `#editor-state` o `#session-editor-wrap` según filas.
- OOB error de dominio (400): `#editor-notice` (error, `data-dismiss="4500"`),
  `#save-outcome` (`data-ok="0"`).
- Gating cliente: submit interceptado si `#session-editor[data-editmode] !== '1'`.
  Cancelar (`data-action="cancel-session-edit"` / `"cancel-nutrition-edit"`) pasa
  por el mismo dirty-check que el lápiz (confirmación si hay cambios, `doNav`
  forzado al descartar); nunca hace `hx-get` directo.
- Estado del botón de guardado: en modo readonly `#edit-actions` está `invisible` y el
  botón `Guardar cambios` (submit, `btn-primary`) deshabilitado. Al entrar en modo
  edición las acciones (Guardar cambios / Cancelar) quedan **siempre visibles** (con o
  sin cambios). Durante el vuelo htmx el botón se deshabilita y muestra `Guardando…`
  (anti doble-submit); se restaura al terminar. Los 5xx/fallos de red muestran un aviso
  genérico en `#editor-notice` (htmx no intercambia 5xx).
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
- Selección múltiple con Shift+click; `Escape` deselecciona;
  historial `?musculos=A,B&ejercicios=a,b` con popstate.

### `GET /grafica?musculo[]=&ejercicios[]=`

- OOB `#unified-chart` (innerHTML) con el compilado de la selección: 1 músculo →
  compilado + ejercicios; 2+ → global + músculos. Con 1 músculo también OOB
  `#ejercicios-row` (outerHTML).
- El fragmento usa el mismo shell que `chart_html` (header h2 + `chart-empty`/plot 450px).
- Sin títulos de eje ni leyenda (2026-09-10, a petición expresa): la granularidad
  la indica el selector Día/Semana/Mes y el tooltip cristal identifica las
  trazas. Márgenes `l48 r20 t20 b28`; la estabilidad entre estados la dan
  márgenes/altura idénticos.

### `GET /semana/primer-entreno?semana=<n>`

- JSON `{"fecha": "<iso>"|null}`: primera fecha de entrenamiento de la semana del ciclo.
- Conservado para compatibilidad con enlaces históricos. El Dashboard actual no abre un
  editor al hacer clic en la gráfica; la captura de datos se inicia desde Diario.

### Sugerencia de rutina (`GET /sugerencia/banner` + `GET /sugerencia/aplicar`)

- `GET /sugerencia/banner?fecha=` → fragmento `partials/suggestion_banner.html`
  en `#suggestion-banner` (carga con `hx-trigger="load"` y se refresca en cada
  `doNav` con fuente propia, como `#cardio-day`): rutina → botón minimalista
  `btn btn-suggest` ("Usar sugerencia", sin texto); descanso → aviso corto;
  nada → vacío. Nunca 500 visible (error → vacío).
- `GET /sugerencia/aplicar?fecha=` — exige modo edición (misma guarda que
  aplicar plantilla, anti doble-submit); rellena el editor con la sugerencia
  (filas del split en orden con últimos valores posicionales por ejercicio)
  sin guardar, con marcador
  `#plantilla-applied` y aviso con la explicación. Sin rutina → solo aviso.
- `GET /ejercicio/ultimo?ejercicio=&fecha=` — JSON solo lectura para autofill:
  últimas series del ejercicio con `pos` (misma fuente que la rueda);
  `fecha` excluye ese día y posteriores. El editor (`editor.js`) lo pide al
  cambiar un select (siempre sobrescribe esa fila según su ordinal entre
  filas del mismo ejercicio) y al pulsar `+` (hereda el ejercicio origen con
  su siguiente ordinal); sin historial o sin red deja blancos. Paridad móvil
  vía `GET /api/v1/ejercicio/ultimo`.

### `POST /cardio/annotation`

- Campos: `hc_id`, `velocidad_kmh`, `inclinacion_pct`, `notas`, `fecha`.
- Upsert de anotación sobre una sesión `EXERCISE_SESSION` espejada; anotación vacía se
  elimina. OOB de aviso vía `#notice-container`.
- El submit del Diario convierte `FormData` a objeto plano (htmx no serializa FormData
  como `values`) y omite los campos vacíos (`float | None = Form(None)`).
- El formulario de anotación vive en el fragmento compartido con el popup del
  Dashboard: su convergencia a las etiquetas de los editores queda diferida
  (cambiarlo altera el render del popup; requiere consulta previa).

### `POST /ejercicio/nuevo`

- Campos: `ejercicio`, `grupo_muscular` (select cerrado del form
  `#exercise-create-form`, `hx-swap="none"`). La `categoria` viaja en hidden
  (auto-relleno client-side) pero el servidor **siempre la deriva del grupo**
  (`MUSCLE_CATEGORIES`); grupo desconocido → 400. El formulario vive bajo el
  catálogo en `/splits`, en grupo colapsable (ya no hay botón en el Diario).
- OOB: `#notice-container` (success/error), y en éxito `#exercise-create` (outerHTML)
  + `#app-config` (outerHTML, `alimento_map` no afecta pero `categoria_map` sí).
  Si la petición viene de `/splits` (`HX-Current-URL`), además OOB
  `#splits-catalog` (innerHTML) con los grupos refrescados; el cliente
  re-inicializa sus Sortable y reaplica el filtro de búsqueda.
- Errores: nombre vacío / grupo faltante o desconocido / ejercicio duplicado.

### Plantillas de entrenamiento

- En el Diario viven dentro del diálogo nativo `#training-templates-dialog`
  (sin botón en la vista de entreno; el conteo `Plantillas · N` se retiró y
  las mutaciones ya no emiten su OOB).
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
  (con marcador `#plantilla-applied` para el dirty-baseline). No escribe en SQLite:
  solo rellena el editor; el usuario revisa y pulsa Guardar.
- Reordenamiento **solo con ratón** (decisión explícita del usuario; desviación de WCAG
  2.1.1 documentada en `web-standards.md`): tarjetas y filas de editor se arrastran desde
  cualquier parte no-control de la fila (el `dragstart` de las tarjetas excluye
  `input/select/button`; Sortable de filas filtra esos mismos controles). El Sortable de
  filas está **siempre activo**: si el editor está en solo lectura (día con datos), el
  `onStart` entra solo en modo edición para que el reorden persista al guardar. En las
  tarjetas, el `dragend` persiste el orden completo vía `persistOrderWithHtmx` y, ante
  fallo, restaura el DOM y avisa.

### Plantillas de alimentación

- En el Diario viven dentro del diálogo nativo `#food-templates-dialog`; el botón
  del panel muestra el conteo (`#daily-food-template-count`, OOB en mutaciones).
- `POST /alimentacion/plantilla/guardar` — `nombre`, `alimento[]`, `cantidad[]`.
- `POST /alimentacion/plantilla/eliminar/{id}`, `POST /alimentacion/plantilla/reordenar`
  (`id[]`), `GET /alimentacion/plantilla/aplicar/{id}?fecha=` (OOB
  `#nutrition-editor-wrap` + aviso).
- Aplicar es un `<button data-action="apply-meal-template">`; confirmación de reemplazo
  si el día tiene filas (el editor de nutrición es siempre editable).

### Alimentación

- `GET /alimentacion/editor?fecha=` → fragmento `nutrition_editor.html`.
- `POST /alimentacion/save` — `fecha`, `alimento[]`, `cantidad[]`, `peso_kg`,
  `factor_proteina`, `factor_grasa`, `kcal_objetivo` (los objetivos de micros
  son fijos DRI 38/8/1000/90/900 y no se editan en el panel). El servidor recalcula nutrientes
  contra el catálogo (`ROUND_HALF_UP(catálogo_100g × g / 100)`); nunca confía en el
  cliente. OOB `#nutrition-editor-wrap`. El botón de
  guardado (`#nutrition-edit-actions`) sigue el mismo contrato del editor de sesión:
  visible en modo edición, `Guardando…` durante el vuelo, anti doble-submit, y aviso
  genérico en `#notice-container` en 5xx.
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
  con scroll propio; **sin título de panel**, solo buscador + grupos, y debajo
  el formulario `#exercise-create` de alta de ejercicios con el mismo
  vocabulario — `panel`, `field-input`, `btn btn-primary`) y
  `#splits-section` a la derecha (`.splits-editor-col`). Móvil: una columna
  con el editor primero (CSS `order`) y el catálogo debajo. Header de página:
  título + `← Dashboard` + botón `data-action="split-new"` **Nuevo split**.
  `?abrir=<id>` valida el id y renderiza ese item ya expandido (modo vista);
  sin `?abrir`, el split actual (si hay) se renderiza primero y abierto.
- **`#splits-section`** contiene el panel vacío `#splits-empty` (solo
  `data-action="split-new"` "Crear nuevo split", sin letrero) o
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
    agrupadas** `.split-item-actions` (`.icon-btn.split-action-btn` 28×28 con
    `aria-label`/`title`, focus-visible, `[disabled]` con el MISMO tamaño):
    lápiz (`split-edit`, toggle `aria-pressed` + clase **`.is-active`** cuando el
    modo edición está activo — se ilumina con acento + glow, sin texto ni badge
    "Editando"), guardar (`split-save`,
    **deshabilitado sin cambios locales o en item guardado**; `markDirty` lo
    habilita al mutar el board o teclear el nombre), papelera (`split-delete`,
    conserva `data-split-id`/`data-split-nombre` para el confirm) y check de
    actual (`split-activate`, `aria-pressed`, clase **`.is-active`** cuando el
    split es el actual — mismo lenguaje que el lápiz);
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
  (confirmación `#confirm-modal`). `POST /split/activar/{split_id}`: marca el
  split actual (único, idempotente; 400 si no existe); OOB idem y el activo
  queda primero y abierto. El activo viaja en `training_splits.activo` (v016,
  índice parcial único) y el undo (`kind "splits"`) lo restaura.
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
| **RIR** (todos los estados con datos) | 1: "RIR" (RIR medio pooled del ámbito) | Blanco translúcido discontinuo (`rgba(255,255,255,0.35)`, dash), eje Y derecho; existe siempre que el ámbito tenga series (ausente = 0, como el hover) |

Eje X = semana del ciclo (sin título; lo indica el selector); Y = rendimiento − 100,
baseline semana 1 = 0, sin título (la unidad % vive en tooltip e Historial);
eje Y derecho = RIR medio con rango ajustado a los datos visibles (sin base en 0);
hover unificado (series, fallos, volumen, peso, sueño) + bloque RIR. Sin leyenda
(2026-09-10): el tooltip es el único identificador de traza.

### Sincronización LAN

- `POST /sync/health-connect` (API JSON, no htmx): autenticada con `X-Sync-Token`;
  exenta del CSRF de formularios por igualdad exacta de ruta; lotes ≤ 500 ops / 1 MiB;
  upsert por revisión + baja lógica; acuse individual. Contrato completo en
  `docs/architecture/health-sync-contract.md`.
- Gate LAN (`GYM_LAN_SYNC_ONLY=1`): remoto solo este POST **más la API v1 del
  diario** (entreno, nutrición, plantillas, altas y undo;
  contrato en `training-api-contract.md`); el resto de la UI remota es
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
  de tarjetas), `.btn-text` (enlace con borde). Botón de icono canónico
  `.icon-btn` 28×28 (base de armonización; `.split-action-btn` es su alias
  directo). Alias compatibles: `.row-btn`
  (hit area 24px vía `::before`), `.btn-x`, `.btn-check`, `.edit-toggle` (24px),
  `.pt-btn` (24px), `.today-btn`, `.nav-arrow`, `.rir-step`, `.collapse-chevron`.
  (La migración de `.edit-toggle`/`.row-btn`/`.nav-arrow` a `.icon-btn` queda
  diferida: viven en fragmentos compartidos con el popup del Dashboard.)
- **Inputs:** `.cell-input`/`.cell-select` (celdas de tabla; +`.cell-input-sm` para
  parámetros), `.field-input` (+`.field-input-sm`) (formularios de alta).
- **Shell global:** `.skip-link` (WCAG 2.4.1, `#main-content`), `.workspace-nav`
  (+`aria-current="page"`), `.workspace-brand` (título + nav sin ruptura).
- **Gráfica:** `.unified-chart-header`/`.unified-chart-title` (server-render con
  título fijo "Rendimiento", mismo en `src/dashboard_service.py` y
  `src/response_fragments.py`).
- **Nutrición:** `.nutri-params`, `.nutri-target-row`, `.nutri-consumed-row`.
- **Formularios:** `.form-error` (errores, color semántico por token).
- **Contenedores:** `.panel` (+`.panel-tight`/`.panel-default`/`.panel-spacious`),
  `.panel-title` (+`.panel-title-neon`, `.panel-title-divider`), `.card`.
- **Estados vacíos:** sin letreros (2026-09-17, a petición expresa): los días
  sin datos, las listas de plantillas y el catálogo vacíos se renderizan sin
  placa informativa. `.empty-state` se conserva como vocabulario para avisos
  con función (p. ej. `#split-catalog-empty` "Sin resultados").
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
  `.split-summary-chevron`, `.split-empty-state`,
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

- Shell global: `.skip-link` → `#main-content` (span `sr-only` en Dashboard/Diario,
  `main#main-content` en Splits); `h1` idéntico en las 3 páginas (utilidades
  `text-xl font-black tracking-[0.2em] text-white uppercase`); secciones con
  `h2.panel-title`; Splits usa `h2.split-accordion-name` y `h3.split-day-section-label`.
- Fechas: `.date-num.selected` + `aria-current="date"` (servidor y `doNav`).
  Título del Diario `#daily-date-title.panel-title-neon` (`DÍA dd/mm/aa`);
  leyenda sr-only `#navigator-legend` (texto por vista, sincronizada en `setMode`).
- Lápices de edición: `aria-pressed` sincronizado con `editmode`.
- Tabs del Diario con `aria-labelledby`; input date con anillo `:focus-within`.
- `#unified-chart-plot` focuseable con anillo visible; valores en panel Historial.

- Los diálogos de plantillas y altas del Diario, y `#confirm-modal`, son `<dialog>` nativos
  (`modal-dialog.js`): `showModal`/`close`, foco inicial en el primer control, restauración
  de foco al origen y Escape cerrando solo el diálogo superior. Sin focus-trap manual.
  Los `.daily-dialog` hablan el lenguaje del popup del Dashboard (diálogo transparente,
  backdrop `overlay-backdrop-popup` con blur 12px + tarjeta `matte-900` con glow burdeos).
- No se mantiene estado de popup en el historial. La fecha y vista canónicas viven en
  `/diario?fecha=<iso>&vista=<modo>`.

## 4. Navegador de fechas

- Ventana de 31 días centrada en la selección, recortada a
  `[ciclo_start, fin del mes siguiente]`. Input date = salto preciso; flechas = ±15 días
  (ventana); HOY = salto al día actual. Flechas de teclado solo con foco dentro de
  `#date-navigator`. Puntos `.date-dot` = días con datos.
- Dashboard (`variant="dashboard"`): formato `S{semana} · dd-mm-aa`, puntos solo de
  entrenamiento (`fechas_con_datos`), sin cambios.
- Diario (`variant="daily"`): etiquetas compactas (`dd` o `d/m` el primero de mes),
  aria `dd/mm/aa`, sin texto "Semana"; los puntos se filtran por pestaña
  (`GET /diario?vista=` y `GET /diario/navigator?vista=`): `entrenamiento` solo
  `training_sets`, `alimentacion` solo `diario_alimentacion`
  (`get_daily_data_dates(vista)`). El cambio de pestaña refresca el carrusel
  (`diario.js`) y la navegación propaga `vista` (`date-navigation.js`); los
  dots optimistas tras save/eliminar/undo solo aplican si el dominio coincide
  con la vista activa. El fragmento `GET /diario/navigator` refresca el
  carrusel en cada navegación con cola htmx propia (no descarta las
  peticiones de los editores).

## 4.1. Navegación común

- `templates/partials/workspace_nav.html` en `index.html`, `diario.html` y
  `splits.html`: enlaces Dashboard `/`, Diario `/diario` y Splits `/splits` con
  `.btn btn-outline`; la página activa se marca con `aria-current="page"` y
  color/borde borgoña (`.workspace-nav .btn[aria-current="page"]`).

## 4.2. Días vacíos del Diario (sin letreros)

- Sin placa informativa: la fecha sin datos de un dominio renderiza el editor
  directamente (vacío y editable si es hoy, solo lectura si tiene prefill).
- Los botones de crear (Nuevo ejercicio / Nuevo alimento) y Plantillas siguen
  visibles en días vacíos.

## 5. Estados de UI (siempre diseñados)

- Vacío: "Sin datos" (gráficas, con shell estable) / día sin filas.
- Carga: `htmx-indicator` en filas de la cascada; Plotly se carga bajo demanda
  (un único script SRI tras JSON de gráfica no vacío; fallo → aviso `role="alert"`).
- Error: notices `role="alert"`; éxito: regiones `role="status" aria-live="polite"`.
- El shell de la gráfica (header + 450px) no cambia entre vacío y cargado (CLS 0).
