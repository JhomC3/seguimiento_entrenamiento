# Current Dashboard UI Contract

> **Purpose:** Behavioural contract of the live application (contract v3, cascada de
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
- Sirve server-side: header (título, export CSV, botón Registrar),
  **fila inicial de músculos** (`#cascade-row`, chips `data-action="select-muscle"`),
  gráfica sistémica (`#unified-chart` con `#unified-chart-data` JSON + `#unified-chart-plot`),
  `#history-section` vacío, `<noscript>` con enlace a `/exportar/csv` y los partials
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

- `GET /splits` → página completa (`splits.html`, extiende `base.html`). **Layout
  de dos columnas** (`.splits-layout`): escritorio = catálogo a la izquierda
  (`.splits-catalog-col`, 300px, `position: sticky` con scroll propio dentro del
  viewport) + editor a la derecha (`.splits-editor-col`); móvil = una columna con
  el orden del DOM: editor (`#split-board`) → resumen → catálogo → lista
  (`#splits-section`). Header: form `#split-save-form` (hidden `split_id`/`nombre`,
  botón **"Editar"** visible cuando hay un split abierto, hint `#split-dirty-hint`
  "Modificado" cuando hay cambios sin guardar, "Nuevo", "Guardar").
  `?abrir=<id>` precarga un split (nombre precargado en el input).
- **Catálogo desplegable:** un `<details class="split-catalog-group">` por grupo
  muscular (nativo: `aria-expanded`, teclado y focus; inicia cerrado) con chips
  `div.split-item-card.split-catalog-chip[role=button][tabindex=0]` que muestran
  SOLO el nombre (`data-ejercicio`/`data-grupo`/`data-item-type` como atributos).
  HIIT es un `<details>` propio (`data-group="HIIT"`, `data-item-type="hiit"`).
  Search `split-catalog-search`: abre los grupos con resultados, oculta el resto
  y restaura el estado cerrado al vaciar.
- `GET /split/{split_id}` → fragmento `#split-board` (innerHTML) con el split y
  sus métricas; 400 "El split no existe." para ids desconocidos.
- `POST /split/guardar` — `split_id` (opcional), `nombre` (≤200), arrays alineados
  `dia[]`, `item_type[]`, `ejercicio[]` en orden visual (día a día, instancia a
  instancia; `syncSplitForm` serializa el DOM, que es el orden visual de Sortable).
  El servidor renumera `orden` por día, deriva `grupo_muscular` del catálogo
  (o `HIIT`) y **nunca confía en datos del cliente**. Upsert por nombre; con
  `split_id` edita/renombra. Límite `MAX_SPLIT_ITEMS=300` (server `_check_lote` +
  guard client-side `data-max-items` en `#split-open-state`: si se supera, no se
  toca el DOM y se muestra notice seguro). Un split sin ningún ejercicio se
  rechaza ("El split debe tener al menos un ejercicio."). OOB `#notice-container`
  + `#splits-section` (outerHTML) + `#split-board` (innerHTML).
- `POST /split/eliminar/{split_id}` → confirmación client-side (`#confirm-modal`);
  OOB notice + `#splits-section` + `#split-board` (board vacío).
- **Modo visualización / edición:** un split guardado se abre en modo
  visualización (`#split-board-week[data-editmode="0"]`: sin botones de eliminar
  ni borrar día, Sortables deshabilitados, drag inerte). El botón **"Editar"**
  (header o `split-edit-open` en la lista) activa el modo edición
  (`data-editmode="1"` + `aria-pressed` en el botón). Toda mutación marca el
  editor como modificado (`data-dirty` + `#split-dirty-hint`); Guardar persiste y
  el OOB vuelve a modo visualización. Un split nuevo/vacío arranca en edición.
- **Borrar día:** botón `data-action="split-day-clear"` por día (icono papelera,
  `aria-label="Borrar todos los ejercicios del {día}"`) con confirmación
  (`#confirm-modal`): elimina solo las instancias de ese día (el servidor lo
  aplica al Guardar), recalcula la preview y marca modificado. No afecta a los
  demás días ni borra el split.
- Regla de negocio: **1 instancia = 1 serie** (duplicados permitidos, sin fusión).
  `SplitMetrics` (server-authoritative) cubre los 7 días (vacíos con 0) y expone
  `total_series`, `by_group`, `by_exercise`, `by_group_exercises` (grupo →
  ejercicios, jerarquía del ledger) y `days`. **Resumen compacto tipo ledger**
  (`#split-summary-week` + `#split-summary-days`): "Semana — N series" una sola
  vez; por grupo (destacado, total a la derecha) sus ejercicios anidados con
  total a la derecha y separadores sutiles; diario denso "Lunes — N series —
  Grupo n · Grupo n" (7 filas). Sin "Días activos" ni "Ejercicios distintos";
  el detalle por ejercicio solo aparece en el resumen semanal. La preview
  client-side de `splits.js` se descarta en cada render OOB.
- **DnD estándar (SortableJS, mismo patrón que `row-sortable.js`):**
  - catálogo: fuentes `group:{name:'split-days', pull:'clone', put:false}`,
    `sort:false` — el clon aterriza con `finalizeCard` (uid nuevo, `data-dia` del
    destino, botón de eliminar) y el chip original permanece;
  - días: `group:{name:'split-days', pull:true, put:true}`, `filter:'button'`,
    `animation:150`, `ghostClass:'sortable-ghost'`, `chosenClass:'sortable-chosen'`,
    `disabled` según editmode; inserción en la posición exacta del puntero
    (mitad de la tarjeta destino);
  - `onMove` pinta `drop-target` en la zona (y devuelve `false` con Shift para
    neutralizar a Sortable en el modo duplicación); `onEnd` limpia;
  - **arrastre normal mueve; Shift duplica** (instancia o día completo). Chromium
    headless no inicia el drag de Sortable con Shift: el modo Shift usa un drag
    por puntero propio (`mousedown` con `shiftKey` → `mousemove` → `mouseup`),
    con inserción por Y (mitad de la tarjeta destino; final si cae debajo);
  - **copia de día completo:** handle `button.split-day-copy-handle` por día con
    `data-action="split-day-copy"`, `aria-label` y `title`; Shift+arrastre copia
    el bloque (cada copia con `dia` del destino y uid propio); Shift+click copia
    al día seleccionado; sin Shift el handle solo selecciona el día y el drag
    no se inicia; el día origen nunca se mueve ni se borra;
  - alternativas accesibles: click en chip (`split-add-item`, Enter/Espacio) y
    Shift+click en el handle de día.
- `splits.js` re-sincroniza `split_id`/`max_items`/`editmode`/`nombre` tras cada
  OOB de `#split-board` (marcador `#split-open-state[data-split-id][data-max-items]
  [data-editmode][data-nombre]`), recrea los Sortables de los días
  (`initBoardSortables`: destroy + create) y re-vincula los handles
  (`bindDayCopyHandles`, por elemento) y tras `/undo` refetches el board del
  split abierto. **El re-init escucha `htmx:oobAfterSwap` además de
  `htmx:afterSwap`** (los swaps OOB disparan el primero, con target = elemento
  OOB): sin esto, tras abrir/guardar un split los días quedan sin Sortable y el
  drag muere. No queda DnD nativo paralelo a nivel `document` (los drags de items
  son SortableJS; el drag por puntero del modo Shift se registra en
  `mousedown`/`mousemove`/`mouseup`, no en `dragstart`). `initSplits` es
  resiliente: guard `typeof Sortable` en las sub-inits (CDN caído → click-add y
  el resto siguen vivos, con `console.warn`), try/catch por sub-init y reintento
  en `window load`.

### Exports

- `GET /exportar/csv` → `text/csv` de `training_sets` ordenado por `fecha, set_orden`
  (`filename="entrenamientos.csv"`), con BOM UTF-8.
- `GET /alimentacion/exportar/csv` → `diario_alimentacion` (`alimentacion.csv`, BOM).
- `GET /exportar/health-connect.csv[?incluir_borrados=1]` → `health_records` activos
  (o con borrados para auditoría) ordenados `record_type, start_epoch_ms`, BOM.

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
- **Splits:** `.splits-layout`, `.splits-editor-col`, `.splits-catalog-col`,
  `.split-columns`, `.split-day-zone` (+`.drop-target` durante el arrastre),
  `.split-day-header`, `.split-day-select`, `.split-day-count`, `.split-day-items`,
  `.split-day-copy-handle`, `.split-day-clear-btn`, `.split-catalog-group`,
  `.split-catalog-summary`, `.split-catalog-body`, `.split-catalog-chip`,
  `.split-item-card` (+`.dragging`, `.copy-mode`), `.split-item-name`,
  `.split-summary-row`, `.split-summary-total`, `.split-summary-name`,
  `.split-summary-group`, `.split-summary-exercise`, `.split-summary-day`,
  `.split-summary-groups`, `.split-metric`, `.split-empty`.
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
