# Plan 5: Dashboard — Estado de selección (global / músculo / ejercicio)

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 2)
**Depende de:** `2026-08-17-dashboard-left-exercise-catalog.md` (plan 4, catálogo izquierdo) y baseline Anexo A.4
**Decisiones confirmadas por el usuario:**
- El estado debe distinguir explícitamente global / músculo / ejercicio.
- La asimetría de URL `musculo`/`musculos` debe unificarse.

## 1. Objetivo

Convertir la selección actual (2 Sets sueltos en JS + parámetros asimétricos en URL) en **estado explícito y único**, con tres ámbitos bien diferenciados (global, músculo, ejercicio). Unificar la convención de parámetros URL para eliminar la fragilidad documentada en el baseline A.4.

## 2. Alcance

- Redefinir el estado de selección client-side (objeto de estado en lugar de Sets implícitos).
- Unificar parámetros URL: `/grafica` aceptará la misma convención que el historial.
- Persistir y restaurar (pushState/popstate) el nuevo estado, incluido cardio.
- Tests unit + e2e de la nueva semántica.

## 3. Fuera de alcance

- Definir la semántica de líneas (plan 7 chart-series-semantics).
- Cambiar dimensiones y layout (plan 4 ya lo hace).
- Añadir granularidad temporal (plan 8).

## 4. Estado actual (referencias verificadas)

- `static/js/level-cascade.js`:
  - `let selectedMuscles = new Set(); let selectedExercises = new Set();` (líneas 7-8).
  - `currentUrl()` (40-46): construye `?musculos=A,B&ejercicios=a,b` (**plural**).
  - `refreshChart()` (60-68): envía `/grafica?musculo=m&ejercicios=e` (**singular**).
  - `restoreFromURL()` (151-170): lee `params.get('musculos')` y `params.get('ejercicios')` (plural, coma-separados).
  - Asimetría documentada en baseline A.4 (pushState plural vs fetch singular).
- `app.py`:
  - `grafica_view` (1336-1355): `musculo: list[str] = Query(default=[])`, `ejercicios: list[str] = Query(default=[])`.
  - `nivel_view` (1292-1333): `tipo` (global/musculo/ejercicio) + `foco`.
  - `_cascade_items(nivel, foco)` (1198-1231): obtiene categorías/músculos/ejercicios desde DB.
- `src/charts.py` `chart_selection(db, musculos, ejercicios)` (164-260): ramas global/1 músculo/2+; los ejercicios se ignoran en 2+.
- Cardio actualmente: NO está en la cascada. Está como anotaciones `cardio_annotations` sobre `health_records` `EXERCISE_SESSION` (migración v012) y se visualiza en el popup (`cardio_day.html`).

## 5. Cambios propuestos (paso a paso)

### 5.1 Objeto de estado en JS

1. En `level-cascade.js`, reemplazar los 2 Sets por un objeto:
   ```js
   const state = {
     scope: 'global',        // 'global' | 'muscle' | 'exercise'
     muscles: new Set(),
     exercises: new Set(),   // solo válidos con exactamente 1 músculo
   };
   ```
2. Mantener la API interna (`markMuscles`, `markExercises`, `refreshChart`, `refreshExerciseRow`) para que el resto del sistema no cambie de golpe, pero hacer que reflejen `state`.

### 5.2 Unificar URL

1. Usar una convención única, repetible y sin listas separadas por coma: `?musculos=Pecho&musculos=Espalda&ejercicios=Press`. Es la representación nativa de `Query(list[str])`, evita ambigüedades con nombres y se restaura sin parseo especial.
2. `refreshChart()` pasa a:
   ```js
   [...state.muscles].forEach((m) => params.append('musculos', m));
   [...state.exercises].forEach((e) => params.append('ejercicios', e));
   ```
3. `app.py grafica_view` (1336): cambiar `musculo: list[str] = Query(...)` → `musculos: list[str] = Query(default=[])`; actualizar `_chart_selection_html` y el call. Mantener compatibilidad temporal con `musculo` (alias) solo si algún test/e2e viejo depende; idealmente unificar de una vez.
4. Mantener compatibilidad de lectura con la URL con comas durante esta fase y normalizarla con `history.replaceState`; no aceptar dos escrituras permanentes.

### 5.3 Persistencia y restore

1. `pushState`/`popstate`/`restoreFromURL` se reescriben sobre `state` y preservan únicamente selecciones de fuerza válidas.
2. Mantener el comportamiento: Escape → deseleccionar (global); Shift+click multi-selección.

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
```

Nuevos tests:
- Unit: `grafica_view` acepta `?musculos=` (y rechaza/aliases `musculo`).
- E2E: la nueva URL plural se restaura correctamente con back/forward.

## 7. Riesgos

- **R1**: cambiar la representación de URL puede romper enlaces existentes; leer temporalmente ambos formatos y escribir uno solo.
- **R2**: `scope='exercise'` solo es válido con exactamente un músculo; validar y limpiar ejercicios incompatibles en el borde y en restore.

## 8. Criterios de aceptación

- La selección distingue global / músculo / ejercicio y mantiene invariantes explícitas.
- La URL escrita usa solamente parámetros repetidos `musculos` y `ejercicios`; la lectura legada con comas queda cubierta durante la transición.
- Restore tras reload y back/forward conserva selección.
- Gates verdes (pytest/ruff/mypy); axe sin violaciones en nuevo estado.

## 9. Próximo plan

`2026-08-17-dashboard-chart-series-semantics.md` (contrato de trazas sobre el nuevo estado), seguido de `2026-08-17-dashboard-chart-transition.md` (rendering sin parpadeo).
