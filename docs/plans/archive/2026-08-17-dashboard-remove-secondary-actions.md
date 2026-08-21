# Plan 2: Dashboard — Retirar acciones secundarias (export y detalle ⓘ)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 1)
**Depende de:** `2026-08-17-dashboard-baseline-and-contract.md` (baseline completo)
**Decisiones confirmadas por el usuario:**
- Retirar el botón visible de exportación CSV del dashboard y el botón `ⓘ`.
- **Conservar** `/exportar/health-connect.csv`.
- Eliminar el botón `ⓘ` (`data-action="exercise-detail"`), pero **conservar** la ruta `?tipo=ejercicio` y la plantilla `exercise_detail.html` (se reubicará en el panel derecho en el plan `left-exercise-catalog`).

## 1. Objetivo

Retirar del dashboard los controles secundarios que no aportan al flujo actual: exportación CSV (entrenamiento y alimentación) y el botón de información `ⓘ` de cada ejercicio. El objetivo es reducir ruido visual en el header y en la fila de ejercicios, sin romper rutas de auditoría de Health Connect ni la funcionalidad de detalle.

## 2. Alcance

- Retirar el enlace visible a `GET /exportar/csv` (entrenamiento).
- **NO** tocar `GET /exportar/health-connect.csv` → `app.py:1393`.
- Retirar el botón "Exportar CSV" del header → `templates/index.html:8-12`.
- Ajustar el enlace del `<noscript>` → `templates/index.html:53`.
- Retirar el botón `ⓘ` de `templates/ejercicios_row.html` (`data-action="exercise-detail"`).
- Eliminar el handler `exercise-detail` de `static/js/level-cascade.js:189-191`.
- Limpiar tests, auditoría y documentación asociadas a las rutas eliminadas.

## 3. Fuera de alcance

- Cambiar la semántica de la gráfica, la selección o el layout.
- Cambiar contratos htmx de mutaciones (save/eliminar/undo).
- Eliminar la ruta `?tipo=ejercicio` ni la plantilla `exercise_detail.html`.
- Eliminar el export de Health Connect.

## 4. Estado actual (referencias verificadas)

- Header del index (`templates/index.html:5-22`): dos botones `btn btn-outline` → "Exportar CSV" (`href="/exportar/csv"`, líneas 8-12) y "Splits". El **único** botón de export del UI es entrenamiento.
- `<noscript>` (`index.html:53`): "…puedes exportar los datos en CSV" enlaza a `/exportar/csv`.
- Botón `ⓘ` (`templates/ejercicios_row.html:15-19`): `<button class="detail-link" data-action="exercise-detail" data-foco="{{ item }}">ⓘ</button>` por cada ejercicio.
- Handler JS (`static/js/level-cascade.js:189-191`): en `initLevelCascade`, `else if (el.dataset.action === 'exercise-detail') { refresh('#history-section', '/nivel?tipo=ejercicio&foco=...'); }`.
- Ruta detalle (`app.py:1305-1321`): `?tipo=ejercicio` renderiza `exercise_detail.html` (tablas Resumen por Sesión + Datos Crudos) en `#history-section`. **Conservada**.
- Rutas de export (app.py): `/exportar/csv` (1186), `/alimentacion/exportar/csv` (886), `/exportar/health-connect.csv` (1393).

## 5. Cambios propuestos (paso a paso)

### 5.1 Límites de la exportación

1. Implementar en este plan únicamente la retirada del control visible de entrenamiento y su texto asociado en `<noscript>`.
2. Mantener vivas, sin cambios, `/exportar/csv` y `/alimentacion/exportar/csv` hasta que el usuario autorice retirar cada contrato HTTP. Ocultar una acción no justifica eliminar una ruta potencialmente usada por marcadores, automatizaciones o el usuario.
3. Conservar intacto `@app.get("/exportar/health-connect.csv")` y su lógica `?incluir_borrados=1`.

### 5.2 Frontend — retirar botón Exportar CSV

1. `templates/index.html:8-12`: eliminar el `<a href="/exportar/csv" class="btn btn-outline">Exportar CSV</a>`.
2. `templates/index.html:53`: reescribir el `<noscript>` para que avise sin enlazar a export (p. ej. "Sin JS puedes ver la vista inicial; los datos se editan desde la app."). Verificar que no queden referencias a `/exportar/csv`.

### 5.3 Frontend — retirar botón `ⓘ`

1. `templates/ejercicios_row.html:15-19`: eliminar el `<button class="detail-link" data-action="exercise-detail">ⓘ</button>` dentro del loop (conservar el `.exercise-chip`).
2. `static/js/level-cascade.js:189-191`: eliminar la rama `else if (el.dataset.action === 'exercise-detail')`.

### 5.4 Tests

1. Conservar los tests de las tres rutas CSV: este plan no modifica los contratos HTTP.
2. Añadir/ajustar únicamente tests que confirmen que el dashboard ya no muestra el enlace ni el texto de exportación.
3. Buscar en `tests/e2e/` referencias a "Exportar" o `/exportar/csv` y ajustar (p. ej. algún test que verifique el botón del header).
4. `scripts/audit_ui.py:522-524`: eliminar los pasos de `/exportar/csv` y `/alimentacion/exportar/csv` del barrido (conservar `/exportar/health-connect.csv`).

### 5.5 Documentación

1. Actualizar el contrato UI para indicar que la exportación ya no se expone como acción visible.
2. No eliminar rutas del inventario de arquitectura ni de operaciones hasta que se retire cada endpoint en un plan específico.
3. `docs/plans/2026-08-17-dashboard-baseline-and-contract.md`: no editar (documenta el estado previo, es el ancla).

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
```

Verificación manual de huecos:
```bash
rg -n "exportar/csv|exportar\s+csv|Exportar CSV|exercise-detail|detail-link" app.py templates static tests scripts docs --glob '!docs/plans/archive/**'
```
Debe quedar solo la referencia a `/exportar/health-connect.csv` (y las de los planes que documentan el estado previo).

## 7. Riesgos

- **R1**: eliminar imports ahora sin uso (`Response`, `read_connection`) → mypy/ruff lo detecta; resolver.
- **R2**: algún test o e2e depende del botón de export o del `ⓘ` → el `rg` de 6 y la suite lo detectan.
- **R3**: eliminar por accidente el export de health-connect → se conserva; verificado con test 200 + BOM.
- **R4**: romper el clic de detalle que usan tests de `tipo=ejercicio` → la ruta y el template se preservan, solo se elimina el botón visible.

## 8. Criterios de aceptación

- `GET /exportar/csv` y `GET /alimentacion/exportar/csv` conservan su comportamiento actual y sus pruebas existentes.
- `GET /exportar/health-connect.csv` → 200, `text/csv`, BOM `\ufeff` (tests existentes verdes).
- El header no muestra "Exportar CSV"; el `<noscript>` no enlaza a export.
- No hay `ⓘ` ni `data-action="exercise-detail"` en el DOM de `#ejercicios-row`.
- `?tipo=ejercicio&foco=...` sigue devolviendo `exercise_detail.html` (test `test_nivel_cascada_grupo_musculo_ejercicio` verde).
- Todos los gates (pytest/ruff/mypy) verdes. DGIT: sin código muerto de rutas eliminadas.

## 9. Próximo plan

`2026-08-17-dashboard-stable-layout.md` (reservar alturas → CLS 0), usando este resultado más limpio y las mediciones del baseline A.1.
