# Plan 10: Página de registro diario (`/registro`)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de decisión e implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 4)
**Depende de:** baseline y los fragmentos/servicios actuales. La navegación desde la gráfica depende además del plan de granularidad.
**Decisiones confirmadas por el usuario:** se evaluará una página de registro diario como posible flujo principal. El retiro del popup no está decidido y se gestiona en `daily-record-popup-retirement.md`.

## 1. Objetivo

Crear la página dedicada **`/registro?fecha=`** para introducir datos del día (entrenamiento, alimentación, cardio), **reutilizando los servicios y fragmentos existentes**, en convivencia temporal con el popup actual. La comparación de ambos flujos determina el plan posterior de retiro.

## 2. Alcance

- Nueva ruta `GET /registro` (página completa, mismo shell `base.html`).
- Mover los fragmentos del popup (`editor_popup.html`, `session_editor.html`, `nutrition_editor.html`, `cardio_day.html`, plantillas, altas) a la página.
- Añadir un acceso visible a `/registro` desde el dashboard.
- Mantener temporalmente el popup y el comportamiento actual de clic en gráfica.
- Mantener sin cambios los contratos de mutación (`POST /entrenamiento/session/save|eliminar`, `POST /alimentacion/save|eliminar`, `POST /cardio/annotation`, etc.).

## 3. Fuera de alcance

- Rediseñar los controles internos del editor (plan 11: RIR, cardio como músculo, reorden).
- Hacer diálogos compactos de altas/plantillas (plan 12).
- Cambiar la semántica de la gráfica o selección (plans 5/7/8).

## 4. Estado actual (hechos verificados)

- `templates/editor_popup.html`: navegador de fecha (`#date-navigator`) + título fecha + `#nutrition-templates-section` + `#nutrition-panel` (`#nutrition-editor-wrap`) + `#session-editor` (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`) + `#cardio-day` + `#exercise-create` + `#alimento-create`.
- `templates/index.html:58-66`: `<dialog id="editor-popup">` con slider `#popup-body`.
- `static/js/editor-popup.js`: `openEditorPopup(fecha)`, `showModal`, `?registro=` en historial, navegador de fechas, `POST /cardio/annotation`.
- `static/js/chart-interaction.js` (95-117): `firstTrainingOfWeek(semana, attempt)` → `fetch('/semana/primer-entreno?semana=')` → si `data.fecha` → `openEditorPopup(data.fecha)`.
- Rutas de mutación usadas por el popup (app.py): `/fecha/editor`, `/editor/popup`, `/entrenamiento/session/save`, `/entrenamiento/session/eliminar`, `/alimentacion/save`, `/alimentacion/eliminar`, `/alimento/nuevo`, `/ejercicio/nuevo`, `/cardio/annotation`, `/plantilla/*`, `/alimentacion/plantilla/*`.
- Test e2e que dependen del popup: `test_week_click_opens_popup_en_primer_entreno` (351), `test_popup_dialog_focus_roundtrip` (779), `test_confirm_dialog_*` (800/819), `test_navigate_por_fecha_del_navegador_del_popup` (499), `test_cardio_annotation_saves_from_popup` (1009), `test_cardio_refreshes_when_navigating_in_popup` (1089), `test_axe_popup_editor_and_nutrition` (accessibility:75).

## 5. Cambios propuestos (paso a paso)

### 5.1 Ruta y plantilla nueva

1. Nueva plantilla `templates/registro.html` (extiende `base.html`), con:
   - Header con título "Registro" + enlace al dashboard.
   - `#date-navigator` (navegador de fechas ya existente).
   - Resumen del día (si aplica, enganche del plan 9 para el día).
   - `#nutrition-templates-section`, `#nutrition-panel` (`#nutrition-editor-wrap`).
   - `#session-editor` (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`).
   - `#cardio-day` (o sección colapsable según plan 11).
   - `#exercise-create`, `#alimento-create` (se moverán a diálogos en plan 12; aquí mantener como placeholders o ya diálogos).
2. Ruta en `app.py`:
   ```python
   @app.get("/registro", response_class=HTMLResponse)
   def registro_page(request: Request, fecha: str | None = None): ...
   ```
   - Reutilizar `_render_body` y los mismos helpers del popup (navigator, editor, nutrición, cardio) — server-side, idéntico contrato de render que `/editor/popup`.

### 5.2 Reutilizar fragmentos (sin duplicar lógica)

1. Idealmente, el cuerpo de `/registro` = el mismo HTML que hoy produce `editor_popup.html` (reutilizar los mismos contenedores y ids para que el JS y htmx funcionen sin cambio).
2. Si se refactoriza para compartir un fragmento "cuerpo del registro" (`_registro_body_html(request, fecha)`) que hoje usan `/registro` (página) y ya no el popup. Los targets OOB (`#session-editor-wrap`, `#nutrition-editor-wrap`, etc.) deben mantenerse idénticos.

### 5.3 Convivencia y evaluación

1. Añadir un enlace de regreso al dashboard y preservar el flujo popup para que la nueva página pueda validarse sin pérdida de función.
2. Extraer, si hace falta, un fragmento de cuerpo compartido para evitar duplicar markup; los ids OOB deben existir una sola vez en cada página.
3. Registrar qué flujos son equivalentes y cuáles necesitan rediseño antes de decidir el retiro en el plan 13.

### 5.4 Migración de tests

- Añadir pruebas equivalentes para `/registro` sin eliminar las pruebas del popup.
- Cubrir navegador de fechas, save/eliminar de sesión, alimentación, cardio, foco/teclado y axe en la nueva página.

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
```

## 7. Riesgos

- **R1**: duplicar markup puede divergir; extraer un fragmento común y no duplicar lógica de servidor.
- **R2**: el clic-en-punto y la fecha por granularidad se decide solo si se aprueba retirar o redirigir el popup.
- **R3**: el foco/Escape de diálogos (plan 12) debe funcionar en página completa sin dialog nativo → usar `confirm_modal.html` existente.
- **R4**: perdida de `?registro=` en historial (era del popup) → con página ya no hace falta; simplificar.

## 8. Criterios de aceptación

- `GET /registro?fecha=YYYY-MM-DD` renderiza la página completa con navegador, sesión, alimentación y cardio, editables.
- El popup actual sigue funcionando mientras se valida `/registro`.
- Existe una comparación E2E de ambos flujos y evidencia para la decisión de retiro.
- Todas las mutaciones (save/eliminar/undo/cardio/plantillas) siguen funcionando con los mismos OOB.
- Tests migrados (foco, cardio, axe) verdes.
- Gates todos verdes.

## 9. Próximo plan

`2026-08-17-daily-record-editor-controls.md` (revisión de RIR, cardio como sección secundaria y reorden del `/registro`).
