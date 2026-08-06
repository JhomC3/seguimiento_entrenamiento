# Densidad y visibilidad de controles del editor — Plan de implementación

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminar el recorte de los controles del encabezado y recuperar el ancho desperdiciado al extremo derecho de la tabla de sesión, sin alterar el flujo de edición, guardado, arrastre ni el scroll vertical interno.

**Architecture:** El cambio queda completamente en la capa de presentación: `session_editor.html` aporta hooks semánticos y una distribución de columnas explícita; `base.html` define dimensiones compactas solo dentro del editor y conserva un gutter de scrollbar estrecho y estable. No se modifican endpoints, SQLite, métricas ni el protocolo htmx.

**Tech Stack:** Jinja2, Tailwind vía CDN, CSS propio, JavaScript del navegador, FastAPI TestClient, Playwright mediante `scripts/verify_editor.py`, pytest/uv.

---

## Criterios de aceptación deducidos de la captura

1. Los tres controles del encabezado (guardar entreno, eliminar y editar) se ven completos, quedan alineados a la derecha y no fuerzan ni invaden el título.
2. La fila usa una columna de acciones mínima y consistente: los botones `−` y `+` siguen siendo visibles al hover en edición, son operables y no se superponen con el RM ajustado.
3. El área de scroll reserva únicamente un carril estrecho; no reaparece un bloque vacío grande cuando aún no hay overflow.
4. Con overflow, las columnas no saltan de ancho, el encabezado sigue sticky y la fila adicional sigue accesible mediante scroll interno.
5. Se preservan los estados actuales: readonly oculta acciones de fila, el lápiz habilita edición, añadir/eliminar/reordenar actualiza la tabla y guardar/cancelar conserva su comportamiento.

## Decisión de diseño

Aplicar una compactación localizada, no ampliar la tarjeta ni eliminar el gutter del scrollbar. Reducir el padding del panel o quitar `scrollbar-gutter: stable` resolvería parcialmente la imagen, pero dañaría el área útil de la tabla o provocaría saltos de columnas cuando aparecen muchas series. Se mantendrá el gutter estable con un scrollbar explícitamente fino; el grupo superior se compactará a controles de 22 px y 4 px de separación, y la columna de acciones de fila tendrá 30 px máximos con botones de 14 px.

### Task 1: Fijar los contratos visuales antes de modificar estilos

**Files:**
- Modify: `tests/test_app.py`
- Modify: `scripts/verify_editor.py`

**Step 1: Write the failing server-render contract test**

Añadir junto a `test_editor_botones_texto_en_panel_e_iconos_en_form` una prueba que solicite `GET /fecha/editor` y compruebe que la respuesta contiene los hooks nuevos:

```python
def test_editor_usa_hooks_de_controles_compactos(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    html = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}").text

    assert 'class="editor-header-actions' in html
    assert 'class="row-actions' in html
    assert 'class="set-actions-column' in html
```

**Step 2: Run the focused test and verify failure**

Run: `uv run pytest tests/test_app.py::test_editor_usa_hooks_de_controles_compactos -v`

Expected: FAIL because the semantic classes are not rendered yet.

**Step 3: Add visual assertions to the browser verifier**

En la sección Q de `scripts/verify_editor.py`, añadir una comprobación con `getBoundingClientRect()` que mida:

```javascript
(() => {
  const editor = document.querySelector('#session-editor');
  const actions = editor.querySelector('.editor-header-actions');
  const controls = [...actions.querySelectorAll('.edit-toggle')];
  const actionsBox = actions.getBoundingClientRect();
  const editorBox = editor.getBoundingClientRect();
  const actionColumn = editor.querySelector('.set-actions-column').getBoundingClientRect();
  return {
    headerInsideEditor: actionsBox.right <= editorBox.right,
    allControlsVisible: controls.every(button => button.getBoundingClientRect().width >= 20),
    actionColumnWidth: Math.round(actionColumn.width),
  };
})()
```

Comprobar `headerInsideEditor`, que los tres controles existen y se ven, y que `actionColumnWidth <= 30`. Conservar las aserciones existentes de altura constante y anchos invariantes.

**Step 4: Run the verifier and record baseline failure**

Run: `uv run python scripts/verify_editor.py`

Expected: falla en los nuevos checks por la ausencia de hooks/clase de columna; las comprobaciones previas siguen pasando.

**Step 5: Commit the test contract**

```bash
git add tests/test_app.py scripts/verify_editor.py
git commit -m "test: cover compact session editor controls"
```

### Task 2: Reestructurar el marcado del encabezado y las acciones de fila

**Files:**
- Modify: `templates/session_editor.html:2-51`
- Modify: `templates/session_editor.html:56-115`

**Step 1: Add explicit, scoped layout hooks**

Cambiar el contenedor del encabezado a una fila resistente a estrechamiento: el bloque de fecha tendrá `min-w-0`, y el contenedor de botones recibirá `editor-header-actions flex-none` y `gap-1`. No cambiar funciones `onclick`, clases funcionales ni atributos ARIA.

**Step 2: Keep the title readable rather than colliding**

Permitir que el texto de fecha se trunque solo en anchos extremos (`truncate` en el `h3` o su contenedor), mientras `Semana {{ semana }}` permanece como información secundaria. Así los botones no se cortan ni salen del panel.

**Step 3: Compact the table action column**

Reemplazar la última cabecera `w-10 py-0 px-1.5` por una cabecera con la clase `set-actions-column`, ancho de 30 px y padding horizontal cero. Aplicar la misma clase al `<td>` correspondiente; conservar dentro `row-actions`, sus `onclick` y las dos acciones en el orden actual (`−`, `+`).

**Step 4: Avoid hidden spacing in the action group**

Cambiar `justify-end` por centrado y declarar el grupo como `w-full`, con `gap-px`. La columna conserva exactamente el espacio necesario para dos controles compactos y no agrega margen lateral artificial.

**Step 5: Run the focused rendering test**

Run: `uv run pytest tests/test_app.py::test_editor_usa_hooks_de_controles_compactos tests/test_app.py::test_editor_botones_texto_en_panel_e_iconos_en_form -v`

Expected: PASS.

**Step 6: Commit the semantic markup**

```bash
git add templates/session_editor.html tests/test_app.py
git commit -m "feat: compact session editor action layout"
```

### Task 3: Aplicar la compactación visual sin romper las invariantes de scroll

**Files:**
- Modify: `templates/base.html:199-222`
- Modify: `templates/base.html:290-333`
- Modify: `templates/base.html:470-485`

**Step 1: Scope the smaller dimensions to the session editor**

No cambiar `.edit-toggle` ni `.row-btn` globales, ya que también sirven formularios de plantillas. Añadir reglas específicas:

```css
#session-editor .editor-header-actions .edit-toggle {
    width: 22px;
    height: 22px;
}
#session-editor .editor-header-actions svg {
    width: 13px;
    height: 13px;
}
#session-editor .set-actions-column { width: 30px; }
#session-editor .row-actions .row-btn {
    width: 14px;
    height: 14px;
    font-size: 10px;
}
```

El tamaño visual reducido se limita al editor; la accesibilidad existente se preserva con `aria-label`/`title`, estado de foco visible y los controles grandes fuera de este contexto.

**Step 2: Hacer fino el carril del scroll sin eliminar su reserva estable**

Mantener `scrollbar-gutter: stable` en `.table-scroll` y añadir reglas WebKit limitadas a ese selector para un scrollbar de 6 px y thumb discreto. Mantener `scrollbar-width: thin` para Firefox. Con ello se conserva la prueba de columnas invariantes, reduciendo el hueco derecho señalado en la captura.

**Step 3: Recalcular la altura solo si cambia la altura medida de las filas**

Ejecutar el verificador antes de tocar `ROWS_VISIBLE`, `PANEL_BUFFER` o la fórmula de `fitRowsToPanel()`. Los controles reducidos caben dentro de la altura de fila actual; si el check revela un cambio, ajustar únicamente el fallback de `rowHMeasured`, sin cambiar el objetivo de 17.5 filas ni el comportamiento de overflow.

**Step 4: Run the full browser verifier**

Run: `uv run python scripts/verify_editor.py`

Expected: todos los checks pasan, incluidos: controles superiores dentro de la tarjeta, columna de acciones <= 30 px, altura estable, columnas invariantes y scroll a partir de la fila 18.

**Step 5: Commit styling and verification**

```bash
git add templates/base.html scripts/verify_editor.py
git commit -m "style: reduce session editor control density"
```

### Task 4: Ejecutar regresión de la aplicación y revisión visual final

**Files:**
- Verify only: `templates/session_editor.html`
- Verify only: `templates/base.html`
- Verify only: `templates/index.html`
- Verify only: `tests/`

**Step 1: Run all automated tests**

Run: `uv run pytest`

Expected: PASS, sin regresiones de rutas, editor, plantillas, guardado, undo ni métricas.

**Step 2: Launch the local UI**

Run: `uv run uvicorn app:app --reload`

Expected: servidor disponible localmente.

**Step 3: Verify the two representative UI states**

En una sesión con datos (readonly) y tras activar el lápiz (editable), comprobar visualmente a 1280 px:

1. Cabecera: los tres iconos no quedan cortados y su borde derecho respeta el padding de la tarjeta.
2. Tabla: RM ajustado mantiene lectura clara; el carril `−/+` ocupa solo lo necesario y no hay banda vacía gruesa a la derecha.
3. Con 18 filas: aparece scroll vertical interno fino, sin cambiar el ancho de columnas ni la altura de la tarjeta.
4. Hover sobre una fila editable: ambos botones se muestran, se pueden pulsar y no alteran la alineación.

**Step 4: Capture the outcome as a regression artifact if the repository already keeps screenshots**

Reutilizar el flujo existente de `scripts/verify_editor.py`; no introducir una dependencia de capturas nueva si no hay una convención vigente. Cualquier discrepancia debe resolverse ajustando CSS scoped, no ampliando el alcance a backend.

**Step 5: Commit the verified final state**

```bash
git status --short
git add templates/session_editor.html templates/base.html tests/test_app.py scripts/verify_editor.py
git commit -m "fix: prevent clipping in session editor controls"
```
