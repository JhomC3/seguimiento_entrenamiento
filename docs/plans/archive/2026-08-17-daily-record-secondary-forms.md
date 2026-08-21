# Plan 12: Registro diario — Formularios secundarios en diálogos compactos

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 4)
**Depende de:** `2026-08-17-daily-record-page.md` (plan 10) y `2026-08-17-daily-record-editor-controls.md` (plan 11)
**Objetivo de diseño propuesto:** formularios de alta y plantillas en **diálogos compactos**. Se valida en `/registro` antes de retirar las versiones actuales.

## 1. Objetivo

Convertir los formularios de alta (ejercicio y alimento) y las listas de plantillas (entrenamiento y comida) en **diálogos compactos** dentro del registro diario `/registro`, eliminando el espacio que ocupan inline (problema del master §2: "Los formularios de nuevo ejercicio y nuevo alimento ocupan demasiado espacio", "plantillas visualmente separadas").

## 2. Alcance

- `templates/exercise_create_form.html` y `templates/alimento_create_form.html` → diálogos de trabajo específicos, no el modal de confirmación.
- `templates/plantillas_list.html`, `templates/plantillas_alimentacion_list.html` → diálogos/paneles colapsables compactos.
- Reubicar en `/registro` como accesos rápidos (botones "+ ejercicio", "+ alimento", "Plantillas").
- Mantener intactas las rutas de mutación (`POST /ejercicio/nuevo`, `POST /alimento/nuevo`, `/plantilla/*`, `/alimentacion/plantilla/*`, `GET /plantilla/aplicar/{id}`, `GET /alimentacion/plantilla/aplicar/{id}`).
- Migrar tests.

## 3. Fuera de alcance

- Cambiar la lógica de negocio de los formularios (validación server-side intacta).
- Cambiar el contrato OOB de altas (`#exercise-create`, `#alimento-create`, `#app-config`).

## 4. Estado actual (hechos verificados)

- `templates/editor_popup.html`: `#exercise-create` y `#alimento-create` inline (formularios visibles siempre).
- `templates/exercise_create_form.html` / `templates/alimento_create_form.html`: formularios full-width con campos (server-owned).
- `templates/plantillas_list.html` / `templates/plantillas_alimentacion_list.html`: listas de plantillas con acciones (guardar/editar/eliminar/reordenar/aplicar).
- Rutas (app.py): `POST /ejercicio/nuevo` (OOB `#exercise-create` + `#app-config`), `POST /alimento/nuevo` (OOB `#alimento-create` + `#app-config`), `GET /plantillas`, `POST /plantilla/*`, `GET /plantilla/aplicar/{id}`, `/alimentacion/plantilla/*`.
- Modal existente: `templates/partials/confirm_modal.html` (`#confirm-modal`) + `static/js/modal-dialog.js` (si existe).
- Tests asociados: `test_hostile_exercise_notice_creates_no_image_node` (322), `test_template_crud_and_reorder` (195), `test_apply_template` (176), `test_template_delete_uses_custom_modal` (487), `test_nutrition_apply_confirms_replacement` (984), `test_training_cards_reorder_and_persist` (908).

## 5. Cambios propuestos (paso a paso)

### 5.1 Diálogo base reutilizable

1. Añadir un diálogo de trabajo específico y reutilizable; no reutilizar `confirm_modal.html`, que conserva responsabilidad de confirmaciones destructivas. El diálogo contiene un único host persistente para formularios/plantillas y sus targets OOB.
2. Asegurar: focus dentro del diálogo, Escape cierra, aria-modal/dialog, teclado (gate axe). Patrón de `test_confirm_dialog_focus_and_escape` como referencia.

### 5.2 Alta de ejercicio (conservar contrato)

1. `templates/exercise_create_form.html`: mantenerlo como contenido del diálogo (mismo form, mismo `hx-post` y `#app-config`). Garantizar que `#exercise-create` permanece dentro del host mientras el diálogo está cerrado para que el OOB sea válido.
2. En `registro.html` (y wherever corresponda), sustituir el bloque inline por un botón "+ ejercicio" que abre el diálogo.
3. Verificar que `#exercise-create` como target OOB sigue presente (la respuesta de `/ejercicio/nuevo` actualiza el form del diálogo y `#app-config`).

### 5.3 Alta de alimento

1. Igual que 5.2 con `templates/alimento_create_form.html` → diálogo, `hx-post` a `/alimento/nuevo`, OOB `#alimento-create` + `#app-config`.

### 5.4 Plantillas de entrenamiento y comida como diálogos

1. `templates/plantillas_list.html` y `templates/plantillas_alimentacion_list.html`: presentarlas en diálogos/paneles colapsables accesibles desde el editor correspondiente (junto a sesión y junto a nutrición — master: "plantillas de entrenamiento no separadas del editor").
2. Mantener el CRUD/reorden drag de plantillas (patrón `test_template_crud_and_reorder`, `_simulate_drag`).

### 5.5 Ajax/htmx de los diálogos

1. Adaptar el módulo existente `static/js/modal-dialog.js` con listeners delegados; no crear un segundo sistema de modales.
2. Asegurar que al guardar se cierra el diálogo limpio y se actualiza el target OOB + `#app-config` (el `htmx:afterRequest` de `app.js` ya relee config).

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_nutrition_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
```

## 7. Riesgos

- **R1**: convertir a diálogo rompe tests que asumen formularios visibles — migrarlos (clic en "+ ejercicio" antes de rellenar/verificar).
- **R2**: el drag&drop interno de plantillas dentro de un diálogo pequeño — mantener DnD intacto y ajustar layout del diálogo.
- **R3**: focus trap/Escape en diálogos con htmx OOB — reutilizar las primitivas de `modal-dialog.js`, con axe.
- **R4**: un solo target OOB `#exercise-create`/`#alimento-create` en la página (evitar ids duplicados al cerrar/reabrir) — garantizar que el diálogo reutiliza el mismo node.

## 8. Criterios de aceptación

- Alta de ejercicio y alimento desde diálogo compacto, con la misma validación server-side y OOB (`#app-config` actualizado). No hay formularios inline grandes en `/registro`.
- Plantillas (entrenamiento y comida) accesibles como diálogos junto a su editor, con CRUD/reorden intactos.
- Teclado: focus dentro del diálogo, Escape cierra, aria correcto (axe sin violaciones).
- Tests migrados verdes; gates verdes.

## 9. Próximo plan

`2026-08-17-daily-record-popup-retirement.md` (decisión y retiro seguro del popup, si se aprueba).
