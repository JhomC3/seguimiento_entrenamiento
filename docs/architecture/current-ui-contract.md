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

### `POST /ejercicio/nuevo`

- Campos: `ejercicio`, `grupo_muscular`, `categoria` (form `#exercise-create-form`,
  `hx-swap="none"`).
- OOB: `#notice-container` (success/error), y en éxito `#exercise-create` (outerHTML)
  + `#app-config` (outerHTML, `alimento_map` no afecta pero `categoria_map` sí).
- Errores: nombre vacío / grupo faltante / categoría inválida / ejercicio duplicado.

### Plantillas de entrenamiento

- `GET /plantillas[?editar=<id>]` → fragmento `plantillas_list.html`
  (`target: '#plantillas-section'`). Tarjetas `#plantillas-list .pt-card[data-pt-id]`
  con acciones Aplicar/Editar/Eliminar y manija de reordenar (`data-action="move-grip"`).
- `POST /plantilla/guardar` — `nombre`, `ejercicio[]` (hidden sync). OOB
  `#notice-container` + `#plantillas-section` (outerHTML). Journal (`entrenos`).
- `POST /plantilla/editar/{id}` — mismo patrón; error conserva `editing_id`.
- `POST /plantilla/eliminar/{id}` — confirmación nativa (`#confirm-modal`).
- `POST /plantilla/reordenar` — `id[]` (orden completo). Enviado vía
  `persistOrderWithHtmx` (htmx + CSRF); fallo → restaura el DOM y avisa.
- `GET /plantilla/aplicar/{id}?fecha=` — exige modo edición; confirmación de reemplazo
  si el día tiene datos; OOB `#editor-notice` + `#session-editor-wrap`
  (con marcador `#plantilla-applied` para el dirty-baseline).
- Reordenamiento por teclado: manija `[data-action="move-grip"]` por tarjeta; con el foco
  en la manija, las flechas ↑/↓ mueven el elemento (sin límites: el extremo no mueve).
  El DnD con puntero sigue siendo una mejora.

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
- Tabla: `<caption>`, `scope="col"`, filas `Objetivo`/`Consumido` en `<tfoot>`
  con `scope="row"`.

### `POST /undo`

- Campo: `fecha` (fecha actual del editor; puede ser vacía).
- OOB éxito: `#notice-container` ("Acción deshecha."); para `sesion` además
  `#undo-result` (outerHTML, `data-fecha`, `data-has-data`, hidden), `#save-outcome`
  (`data-ok="1"`) y `#session-editor-wrap` cuando se deshace la fecha actual; para
  `entrenos`: `#plantillas-section` (outerHTML).
- Pila vacía: `#notice-container` error "Nada que deshacer.".
- Efectos: backup pre-mutación; pop del journal `undo_entries` **solo tras un restore
  exitoso** (la entrada persiste si el restore falla).
- Accesible por Ctrl/Cmd+Z (nunca en campos de texto).

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
