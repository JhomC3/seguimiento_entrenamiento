# Informe Forense — Cumplimiento de Web Standards (2026-08-14)

> **Propósito:** auditoría estática completa del proyecto Gym Tracker contra la guía
> `docs/architecture/web-standards.md` (v1, 2026-08-14). Cada hallazgo incluye severidad,
> ubicación `archivo:línea`, evidencia y remediación sugerida. Las mediciones de contraste
> usan la fórmula WCAG 2.x (luminancia relativa), el resto es revisión estática de código.
> **Base auditada:** commit `085659b` (working tree limpio).
>
> **Resumen del estado:** Server-First, seguridad de transporte/CSRF/SQL y cobertura de
> tests son fuertes. Las brechas se concentran en **accesibilidad WCAG 2.2 AA** (7
> hallazgos altos), **rendimiento CWV** (1 hallazgo alto), **sistema de tokens** (2 altos)
> y **medición continua** (Lighthouse/budget ausentes del release process).

---

## 1. Metodología y alcance

**Superficie auditada** (≈10.000 líneas leídas en su totalidad o por inspección dirigida):

| Capa | Archivos |
|---|---|
| Servidor | `app.py` (1.238 ln), `config.py`, `src/security.py`, `src/dashboard_service.py`, `src/response_fragments.py`, `src/view_models.py`, `src/mutation_service.py`, `src/health_sync_service.py`, `src/charts.py`, `src/db_connection.py`, `src/models.py`, `src/database.py` (parcial) |
| Templates | `base.html`, `index.html`, `session_editor.html`, `nutrition_editor.html`, `date_navigator.html`, `exercise_list.html`, `exercise_detail.html`, `cascade_row.html`, `ejercicios_row.html`, `plantillas_list.html`, `plantillas_alimentacion_list.html`, `cardio_day.html`, `editor_popup.html`, `exercise_create_form.html`, `alimento_create_form.html`, `partials/*` (8) |
| JS | `app.js`, `state.js`, `editor.js`, `nutrition-editor.js`, `templates.js`, `nutrition-templates.js`, `date-navigation.js`, `editor-popup.js`, `htmx-lifecycle.js`, `level-cascade.js`, `row-sortable.js`, `notices.js`, `chart-interaction.js`, `panel-collapse.js` |
| CSS | `app.css`, `palette.css`, `theme.css`, `components.css`, `session-editor.css`, `date-navigator.css`, `templates.css`, `input.css`, `tailwind.css` (build estático, 16 KB) |
| Infra/tests | `pyproject.toml`, `tailwind.config.js`, `.github/workflows/ci.yml`, `scripts/*` (5), `docs/operations/release-checklist.md`, `docs/architecture/current-ui-contract.md`, `AGENTS.md`, `tests/e2e/test_dashboard_flow.py`, `tests/e2e/test_nutrition_flow.py` |
| Android | `network_security_config.xml` (main+debug), `SecureTargetStore.kt`, `HealthSyncClient.kt` (parcial) |

**Herramientas:** `rg` (patrones: `focus:outline-none`, `text-[9-12px]`, hex en templates,
`on*=` inline, `placeholder=`, `aria-*`, `aria-live`), script Python de luminancia/contraste
WCAG, `git ls-files` para higiene del repo.

**Supuestos del modelo de amenaza** (heredados de `docs/architecture/security-model.md`):
aplicación personal, loopback por defecto, sin autenticación; las rutas de exportación y la
API de sync son el único flujo "externo" (Android).

---

## 2. Hallazgos por pilar del estándar

### 2.1 Principio rector — Server-First (sección 1)

**Conformidad (fuerte):** HTML renderizado en servidor + htmx; cero handlers inline
(`onclick=` etc. — verificado con `rg`, 0 coincidencias); cero `innerHTML` con datos de
usuario (allow-list de targets OOB y autoescape como única frontera); validación y cálculo
de macros siempre en servidor (`nutrition_service.py` recalcula con `ROUND_HALF_UP`, nunca
confía en el cliente); handlers `def` síncronos en threadpool; SQL parametrizado en el 100%
de las consultas (verificado con `rg` sobre `execute(`/`executemany(`).

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | **"Funciona sin JS" es solo parcial:** sin htmx/JS la página muestra la gráfica sistémica y contenedores vacíos, pero la cascada (`#cascade-row` vacío hasta `loadMuscles()`), el navegador de fechas, el editor (gating de submit) y el popup de registro quedan inertes. No hay `<noscript>` ni fallbacks `<a href>` para las operaciones principales. Si el requisito es mejora progresiva real, falta declarar el alcance sin-JS o avisar | `index.html:20-23,29-36,40-49`; `level-cascade.js:123-170`; `htmx-lifecycle.js:163-171` |
| Bajo | **Rutas legacy muertas:** `/select`, `/grupo/reset`, `/ejercicio` (`app.py:912-1179`) ya no se referencian desde templates ni JS (solo un comentario en `chart-interaction.js:50-51`); `/nivel` y `/grafica` las reemplazaron. Código muerto = superficie de ataque y deuda de mantenimiento | `app.py:912-1179` |

### 2.2 Rendimiento — Core Web Vitals (sección 2)

| Sev | Criterio | Hallazgo | Evidencia |
|---|---|---|---|
| **Alto** | LCP / INP | **3 scripts síncronos render-blocking en `<head>`:** htmx 1.9.10 + SortableJS 1.15.6 + **Plotly 2.32.0 (~3,5 MB raw / ~1 MB gzip)**. El navegador no pinta nada hasta descargar y ejecutar los tres; Plotly bloquea el LCP incluso cuando la gráfica no tiene datos. Remediar: `defer` en los tres, y Plotly bajo demanda (cargar solo cuando existe `#unified-chart-data` con `fig.data` no vacío) o con `preload`/`modulepreload` de ruta crítica | `base.html:10-14` |
| Medio | LCP | Sin `preconnect`/`dns-prefetch` para `unpkg.com`, `cdn.jsdelivr.net`, `cdn.plot.ly` → los handshakes TLS/DNS ocurren después del parseo del HTML | `base.html:10-14` |
| Medio | Caché | `no_cache_static` fuerza `Cache-Control: no-cache` en **todo** `/static` (`app.py:104-110`): cada visita revalida todos los assets; nunca se usa `max-age`/`immutable` pese a que los nombres de asset son estables (no hasheados). Penaliza visitas repetidas y el INP local | `app.py:104-110` |
| Medio | INP / DOM | El navegador de fechas genera **~150 `<button>` por render** (04/05/2026 → fin del mes siguiente a hoy ≈ 150 días) y se regenera completo en cada cambio de grupo/ejercicio; todo el strip está en el DOM aunque solo se vean ~10 | `src/dashboard_service.py:183-211` |
| Medio | CLS | `#unified-chart-container` sin altura reservada: estado "Sin datos" `h-[300px]` vs. gráfica Plotly ~450 px tras `newPlot` → el swap de gráfica puede desplazar el layout. El resto del diseño sí reserva altura (`--table-h` fijo en `session-editor.css:111-115`) | `src/dashboard_service.py:173`; `index.html:28-32`; `chart-interaction.js:8-34` |
| Bajo | LCP | Sin favicon: el navegador hace una petición extra 404 `/favicon.ico` | `base.html:3-17` |
| Bajo | INP | `fetch('/semana/primer-entreno')` con `.catch(() => {})`: fallo silencioso, sin feedback ni reintento | `chart-interaction.js:36-46` |

### 2.3 Sistema de diseño y tokens (sección 3)

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **Doble fuente de verdad para la paleta:** burgundy/matte están definidos en `tailwind.config.js:7-24` **y** en `static/css/palette.css:4-19` (duplicados manuales que hoy coinciden pero pueden derivar). Además el bloque `<style>` de `index.html:52-133` **hardcodea 8 colores hex fuera de cualquier token** (`#a3a3a3`, `#262626`, `#e5e5e5`, `#404040`, `#e56d88`, `#9b1b30`, `rgba(155,27,48,.15)`, `#737373`) para `.level-btn/.level-chip/.detail-link`. Viola el principio "si un valor no está en un token, no se usa" | `index.html:72-132`; `tailwind.config.js:7-24`; `palette.css` |
| **Alto** | **Tokens de gráfica fuera del sistema:** `src/charts.py` hardcodea `#e56d88`, `#a3a3a3`, `#333`, `#1a1a1a` y la `EXERCISE_PALETTE` (7 hex) en Python — colores del tema duplicados en una tercera ubicación | `charts.py:115-123,172,212-223,267,288-298` |
| Medio | **Tipografía micro:** ~15 usos de `text-[9px]/[10px]/[11px]` en templates; `.pt-btn` y `.cls-badge` a 9 px; `.today-btn` a 10 px. Por debajo del mínimo de legibilidad (12 px) y empeora el contraste efectivo (ver 2.4) | `templates.css:12-44`; `date-navigator.css:67-83`; `nutrition_editor.html:92-103`; `cardio_day.html:27-34` |
| Medio | **Estados de carga no implementados:** `.htmx-indicator` está definido en CSS (`index.html:53-61`) pero ningún elemento de la UI lo usa → los swaps dejan la interfaz sin feedback en LAN/red lenta. (Vacío/error/éxito sí están diseñados.) | `index.html:53-61` |

### 2.4 Accesibilidad — WCAG 2.2 AA (sección 4)

Es el pilar con más fallas. 7 hallazgos de severidad alta.

| Sev | Criterio WCAG | Hallazgo | Evidencia |
|---|---|---|---|
| **Alto** | 1.4.3 Contraste | **`text-neutral-600` (#525252) sobre matte-950 = 2.53:1** (requerido ≥4.5:1). Se usa en: placeholders de los editores (`placeholder-neutral-600`), labels "Proteína ×" / "Grasa ×", "Datos del {origen}", "Sin sesiones de ejercicio…", flechas "→" de la lista de ejercicios, `consumed-grams`. **`text-neutral-500` (#737373) = 4.18:1** (falla): "Exportar CSV", "Ciclo 1", cabeceras de tabla del editor, "Sin datos", "Aún no hay entrenos", fecha/semana del popup. **`today-btn` ≈ 2.42:1** (color con alpha al 45%). Medido con fórmula WCAG (anexo A) | `session_editor.html:77-138`; `nutrition_editor.html:92-103,153-164`; `dashboard_service.py:160,173`; `date-navigator.css:67-83`; `cardio_day.html:8` |
| **Alto** | 4.1.3 Status Messages | **Ningún contenedor de avisos es anunciable:** `#notice-container`, `#editor-notice` y todos los OOB carecen de `role="status"`/`aria-live="polite"` (y de `role="alert"` para errores). Un lector de pantalla jamás se entera de "Entrenamiento guardado", "Nada que deshacer" ni de los errores de validación | `partials/notices.html:1`; `components.css:34-52`; `response_fragments.py:14-15` |
| **Alto** | 4.1.2 / 2.4.3 | **`#editor-popup` no es un diálogo:** sin `role="dialog"`, `aria-modal`, `aria-labelledby`; **sin focus trap, sin foco inicial y sin devolución de foco** al cerrar (solo `Escape`). El Tab escapa al contenido del fondo. `#confirm-modal` tiene `role="dialog" aria-modal="true"` pero tampoco trap, ni `aria-labelledby` (el mensaje `#confirm-msg` no está asociado), ni foco inicial | `index.html:40-49`; `editor-popup.js:18-49`; `partials/confirm_modal.html:1-13`; `htmx-lifecycle.js:40-49` |
| **Alto** | 3.3.2 Labels | **11+ inputs con nombre accesible solo por placeholder** (que no es label): kg/reps/RIR/descanso del editor, alimento/cantidad, "Nombre del entreno", "ejercicio"/"grupo muscular". Las cabeceras de tabla dan contexto visual, no asociación programática | `session_editor.html:102-135`; `nutrition_editor.html:172-219`; `plantillas_list.html:18-25`; `exercise_create_form.html:5-12` |
| Medio | 2.5.8 Target size | **Objetivos táctiles < 24 px** (mínimo AA): `.row-btn` 14 px (`session-editor.css:181-184`; 16 px base en `components.css:4-7`), `.edit-toggle` 22 px (`session-editor.css:157-161`), `.pt-btn` 22 px (`templates.css:31-44`), `.btn-check/.btn-x` 28 px | `components.css:4-96`; `templates.css:31-44` |
| Medio | 2.1.1 Keyboard | **Drag & drop sin alternativa de teclado:** reordenar filas del editor (SortableJS), reordenar entrenos (HTML5 DnD) y plantillas de alimentación son mouse-only | `row-sortable.js:7-22`; `templates.js:257-359`; `nutrition-templates.js:132-200` |
| Medio | 2.1.4 / 2.4.11 | **Atajos globales que secuestran el teclado:** ArrowLeft/Right (±Ctrl) en todo el documento interceptan el scroll y las flechas esperadas fuera de inputs; **Ctrl/Cmd+Z es la única vía de undo — no hay botón "deshacer" en la UI** → la operación es indescubrible y el atajo sin documentación visible | `date-navigation.js:124-140`; `htmx-lifecycle.js:188-195,204-207` |
| Medio | 3.3.2 / 1.3.1 | **Instrucciones solo en `title`/tooltip:** RIR ("0 = fallo · negativo = forzadas"), flechas del navegador, "ⓘ" de detalle — inaccesibles en táctil y no fiables para lectores. **Tabla de nutrición:** filas "Objetivo"/"Consumido" como `<th>` dentro de `<thead>` y ninguna tabla usa `scope="col|row"` | `session_editor.html:123`; `date_navigator.html:3,21,27`; `nutrition_editor.html:137-166` |
| Bajo | 2.3.3 / 1.4.4 | Sin `prefers-reduced-motion`: `chartFadeIn` (0,3 s), `scrollIntoView({behavior:'smooth'})` y transiciones de 150 ms se ejecutan siempre | `index.html:63-70`; `date-navigation.js:69,88,143` |
| Bajo | 4.1.2 | **`focus:outline-none` en 23 clases** de templates: mitigado por `theme.css:30-36` (`:focus-visible` con `!important`), pero sin fallback para navegadores sin soporte de `:focus-visible` (Safari < 15.4) | `theme.css:23-36`; `rg 'focus:outline-none'` |

**Conformidades a11y destacables:** `lang="es"`; foco `:focus-visible` global; `aria-pressed` en los chips de ejercicio (`ejercicios_row.html:9`); `aria-label` en botones icono; `aria-expanded` en colapsables (`panel-collapse.js:20`); `aria-label` en `date-jump`; un e2e de anillo de foco (`test_dashboard_flow.py:448`).

### 2.5 Seguridad (sección 5)

**Conformidad (fuerte):** CSP estática estricta (`script-src 'self'` + CDNs pinneados con SRI, sin nonce ni `'unsafe-inline'`, `object-src 'none'`, `base-uri`, `form-action`, `frame-ancestors`); CSRF token firmado con ventana + validación de Origin; exención solo por igualdad exacta de ruta; `hmac.compare_digest` en el token de sync; límites 1 MiB / 500 ops; Android HTTPS-only (`cleartextTrafficPermitted="false"`, override solo debug con hosts explícitos) y token cifrado en Keystore; CSV export sin f-strings de datos.

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **`scripts/start_server.sh` — el arranque oficial — expone `0.0.0.0:8000` y no genera ni valida `GYM_CSRF_SECRET`.** Sin la variable, el CSRF se firma con `_DEV_SECRET` ("dev-only-secret-do-not-use-in-production", público en el código). En la configuración documentada (LAN para la app Android), **cualquier host de la red puede forjar tokens CSRF válidos** y mutar sesiones/plantillas/alimentación. El token de `/sync/health-connect` es seguro (su propio secret), pero el resto de mutaciones quedan desprotegidas | `scripts/start_server.sh:12-22`; `security.py:53-54,80-104`; `app.py:90-94` |
| Medio | **Sin rate limiting** (OWASP Top 10 / ASVS) en ninguna ruta mutante; `/sync/health-connect` solo limita tamaño de lote, sin throttle por IP ni por token. Aceptable en loopback, pero no está documentado como riesgo aceptado | `app.py:1182-1214`; `health_sync_service.py:22-23` |
| Bajo | Headers opcionales ausentes: `Permissions-Policy` y `Cross-Origin-Opener-Policy` (HSTS no aplica en loopback). `Referrer-Policy: same-origin` y `X-Content-Type-Options` presentes | `security.py:30-34` |
| Info | CSV export sin BOM UTF-8 (`export_csv`, `export_nutrition_csv`): Excel puede corromper acentos al abrir. No es seguridad, es fidelidad de datos | `app.py:710-724,900-909` |

### 2.6 UX y arquitectura de información (sección 6)

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | **Undo invisible e inestable:** única vía Ctrl/Cmd+Z (sin botón "↶"), y la pila vive **en memoria** (`deque(maxlen=10)`): se pierde al reiniciar el servidor, sin advertencia al usuario | `htmx-lifecycle.js:204-207`; `mutation_service.py:33` |
| Medio | **Fallos silenciosos:** `persistDragOrder` (reordenar entrenos) usa `fetch` sin `.catch` ni feedback → si falla la red, la UI muestra el orden nuevo pero el servidor conserva el viejo; el clic en la gráfica ignora errores (`fetch ... .catch(()=>{})`) | `templates.js:244-255`; `chart-interaction.js:36-46` |
| Medio | **Inconsistencia de flujo:** aplicar plantilla de **alimentación** no valida el modo edición (`nutrition-templates.js:48-57`) mientras la de **entrenamiento** sí exige editmode (`templates.js:34-46`) — comportamientos divergentes del mismo patrón | `nutrition-templates.js:48-57`; `templates.js:34-46` |
| Bajo | Dos mecanismos de drag&drop distintos (SortableJS para filas, HTML5 DnD para tarjetas) con estados duplicados — mantenibilidad y accesibilidad desiguales | `row-sortable.js`; `templates.js:222-359`; `nutrition-templates.js:24-200` |

**Conformidades UX:** confirmación previa a toda destrucción (modal custom), dirty-check con modal "¿Guardar los cambios?", notices OOB con auto-dismiss, estados vacíos diseñados (plantillas, cardio), backup automático antes de mutaciones, `Ctrl+Z` global.

### 2.7 SEO técnico (sección 7, acotado)

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Bajo | Sin `<meta name="description">`; `<title>` genérico "Gym Tracker" sin contexto de fecha | `base.html:6` |
| Bajo | Jerarquía de encabezados con salto: `h1` → `h3`/`h4` (sin `h2`) en la página principal | `index.html:7`; `session_editor.html:5`; `nutrition_editor.html:5` |
| Bajo | Sin favicon | `base.html` |

### 2.8 Calidad y medición continua (sección 8)

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **La guía exige auditoría Lighthouse ≥ 90 "registrada en `release-checklist.md`" (web-standards.md §8.5) y el checklist no la tiene:** `release-checklist.md:13-26` solo cubre ruff/mypy/pytest; tampoco hay presupuesto de bundle ni medición de CWV. La sección 10 del checklist tampoco verifica contraste/teclado/aria-live | `web-standards.md §8.5`; `release-checklist.md:13-26` |
| Medio | **Sin tests de accesibilidad automatizados** (axe/WAVE): solo 1 test de anillo de foco y 2 de teclado en e2e; cero tests de contraste o de `aria-live` | `tests/e2e/test_dashboard_flow.py:436-457` |
| Medio | **CI sin gates de rendimiento** (tamaño de bundle, CWV, Lighthouse); solo lint/tipos/tests | `.github/workflows/ci.yml:15-66` |
| Bajo | e2e con esperas fijas (`wait_for_timeout`/`time.sleep`) → flakiness potencial | `tests/e2e/test_nutrition_flow.py:91,107,151-153` |

**Conformidades:** 433 tests, cobertura ≥90% con gate por módulo (`scripts/check_module_coverage.py`), CI completo con Playwright aislado, gates `ruff format --check` / `ruff check` / `mypy` en CI y local.

### 2.9 Antipatrones y checklist mínimo (secciones 9-10)

Estado del checklist mínimo de `web-standards.md` §10:

| Ítem del checklist | Estado | Detalle |
|---|---|---|
| HTML semántico (sin `<div>` interactivos, headings ordenados) | **Parcial** | Backdrop `div` con `data-action` (`index.html:41`); modal sin `role="dialog"`; saltos de heading |
| Valores visuales desde tokens | **Incumple** | `index.html:72-132` (8 hex) + `charts.py` (paleta) + doble definición config/palette.css |
| Estados vacío/error/éxito con patrón de notices | **Parcial** | Estados presentes; **sin estados de carga** (`.htmx-indicator` sin uso) |
| Teclado + foco + contraste ≥4.5:1 + no color-solo | **Incumple** | Contraste 2.29–4.18:1 en varios textos; sin labels; sin trap de modales; DnD mouse-only |
| CSP intacta + CSRF + SQL parametrizado + sin secretos cliente | **Parcial** | Todo correcto excepto el arranque oficial sin `GYM_CSRF_SECRET` (2.5) |
| Mutaciones: backup + undo | **Cumple** | Con caveat: pila en memoria (2.6) |
| Sin layout shift en swaps (CLS < 0.1) | **Parcial** | Riesgo en `#unified-chart` (2.2) |
| `pytest` + `ruff` + `mypy` en verde | **Cumple** | — |
| Contratos y docs actualizados | **Incumple** | Ver 2.10 |

### 2.10 Higiene del repo y drift documental

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | **Drift en `AGENTS.md`:** declara migraciones `v001..v003` cuando existen `v001..v012`; declara "catálogo canónico de 17 tipos" para RecordTypes.kt mientras la allow-list del servidor tiene **41** tipos (`health_sync_service.py:26-69`) — hay más tipos permitidos que mapeados en la app Android | `AGENTS.md:38,103`; `health_sync_service.py:26-69`; `RecordTypes.kt` |
| Medio | **`current-ui-contract.md` desactualizado:** documenta `/select`, `/grupo/reset`, `/ejercicio` como contratos vigentes cuando ya son rutas muertas (2.1) y no documenta `/nivel`, `/grafica`, `/editor/popup`, `/cardio/annotation` | `current-ui-contract.md §1` |
| Bajo | `db_explorer.ipynb` commiteado en la raíz del repo (fuera de cualquier convención de estructura) | `git ls-files` |
| Bajo | `release-checklist.md` §5 (smoke manual) no cubre alimentación, cardio ni el popup de registro — solo entrenamiento clásico | `release-checklist.md:57-66` |

---

## 3. Ranking de remediación priorizado

| Prio | Hallazgo | Esfuerzo | Archivos |
|---|---|---|---|
| **P0** | `start_server.sh`: generar/persistir `GYM_CSRF_SECRET` (patrón ya usado con `hc_sync_token`) y abortar si no existe al exponer `0.0.0.0` | S | `scripts/start_server.sh`, `app.py:90-94` |
| **P0** | `aria-live="polite"` en `#notice-container`/`#editor-notice` (+`role="alert"` en error) | S | `partials/notices.html`, `components.css` |
| **P0** | Modales: `role="dialog" aria-modal aria-labelledby`, focus trap, foco inicial/devolución (`#editor-popup`, `#confirm-modal`) | M | `index.html`, `partials/confirm_modal.html`, `editor-popup.js`, `htmx-lifecycle.js` |
| **P1** | Contraste: subir `neutral-600`/`neutral-500` (o reasignarlos a `neutral-400`) en los usos de 2.4; `today-btn` opaco | S | `theme.css`, tokens, templates |
| **P1** | Labels programáticos en los 11 inputs (o `aria-label`/`aria-labelledby` a la cabecera de columna) | M | `session_editor.html`, `nutrition_editor.html`, `plantillas_list.html`, `exercise_create_form.html` |
| **P1** | `defer` en htmx/Sortable; Plotly bajo demanda; altura reservada para `#unified-chart` | M | `base.html`, `chart-interaction.js`, `index.html` |
| **P1** | Unificar tokens: eliminar `<style>` de `index.html`, paleta única (config o palette.css), tokens en `charts.py` | M | `index.html`, `palette.css`, `charts.py` |
| **P2** | Añadir a `release-checklist.md` + CI: Lighthouse ≥90, presupuesto de bundle, axe en e2e | S | `release-checklist.md`, `ci.yml`, `tests/e2e` |
| **P2** | Alternativa de teclado al DnD (botones mover arriba/abajo) y targets ≥24 px | M | `templates.js`, `nutrition-templates.js`, CSS |
| **P2** | Eliminar rutas muertas + actualizar `current-ui-contract.md`, `AGENTS.md` (migraciones, tipos), mover/quitar `db_explorer.ipynb` | S | `app.py`, docs |

---

## 4. Anexos

### A. Mediciones de contraste (fórmula WCAG, texto normal)

| Primer plano | Fondo | Ratio | ¿≥4.5:1? | Usos detectados |
|---|---|---|---|---|
| `#525252` (neutral-600) | `#0a0a0a` (matte-950) | **2.53** | No | placeholders, labels Proteína/Grasa, textos secundarios, `consumed-grams` |
| `#525252` | `#171717` (neutral-900) | **2.29** | No | idem sobre paneles |
| `#737373` (neutral-500) | `#0a0a0a` | **4.18** | No | "Exportar CSV", "Ciclo 1", cabeceras `<th>`, "Sin datos", "Aún no hay entrenos" |
| `#4f4f4f` (today-btn, alpha 45 %) | `#0a0a0a` | **2.42** | No | botón HOY |
| `#a3a3a3` (neutral-400) | `#0a0a0a` | 7.85 | Sí | textos secundarios de detalle |
| `#e56d88` (burgundy-400) | `#0a0a0a` / `#171717` | 6.48 / 5.87 | Sí | títulos/accentos |
| `#ffffff` | `#800020` (burgundy-700) | 10.83 | Sí | botones "Crear", badges RIR |

### B. Evidencia de conteos (rg)

- `focus:outline-none`: **23** ocurrencias en `templates/`.
- `placeholder=` sin `label`/`aria-label` asociado: **11** inputs (kg, reps, rir, descanso, alimento, cantidad, nombre entreno, nombre alimento, ejercicio, grupo muscular, categoría).
- `text-[9px]/[10px]/[11px]`: ~15 usos en templates (9 px en `cardio_day.html:27,31` y `templates.css:12,38`).
- Handlers inline `onclick=|onchange=|...`: **0** (conforme).
- `innerHTML=` con campos de usuario en JS: **0** (conforme; `innerHTML` solo con fragmentos servidor o strings constantes).

### C. Contratos y referencias cruzadas

- Guía auditada: `docs/architecture/web-standards.md` (10 secciones + checklist §10).
- Modelo de seguridad: `docs/architecture/security-model.md` (§2.1 CSP estática, "Before exposing on a network").
- Contrato de UI (desactualizado en parte): `docs/architecture/current-ui-contract.md`.
- Checklist de release (sin Lighthouse): `docs/operations/release-checklist.md`.
