# Plan 11: Registro diario — Controles del editor y cardio

**Fecha:** 2026-08-17
**Estado:** Borrador revisado (pendiente de implementación)
**Plan maestro:** `docs/plans/2026-08-17-dashboard-analysis-and-daily-record-redesign.md` (Fase 4)
**Depende de:** `2026-08-17-daily-record-page.md` (plan 10, página `/registro`)
**Decisiones confirmadas por el usuario:**
- Los controles de **RIR** necesitan revisión funcional (problema del master §2; test de RIR ya existe pero hay que auditar bugs).
- Reordenar secciones del registro (entrenamiento, alimentación, cardio, plantillas) de forma clara y compacta.

## 1. Objetivo

Refinar los controles del editor diario en `/registro`:
1. Auditar/corregir la interacción de **RIR** (paso `0.1`, decimales, edición de inputs y botones).
2. Integrar **cardio como sección secundaria coherente** dentro del registro.
3. Reordenar las secciones del día en un flujo claro: resumen → entrenamiento → alimentación → cardio → (complementos).

## 2. Alcance

- `templates/session_editor.html` y `static/js/editor.js` (controles RIR).
- `templates/cardio_day.html` + `POST /cardio/annotation` (cardio como sección).
- `templates/registro.html` (reorden de secciones).
- Tests (unit RIR + e2e cardio/reorden).

## 3. Fuera de alcance

- Layout general del dashboard (plans 3/4).
- Semántica de cardio en la gráfica; requiere métricas y un plan específico posterior.

## 4. Estado actual (hechos verificados)

- **RIR** en el editor:
  - `tests/e2e/test_dashboard_flow.py:272` `test_rir_any_decimal_and_01_step`: RIR `step="any"`; botones/teclado avanzan 0,1; guardado con decimal arbitrario. **El comportamiento base ya está testeado**.
  - `session_editor.html` declara inputs RIR con `step="any"` y botones `+/-`.
  - `static/js/editor.js` (o `row-sortable.js`) maneja el ajuste de valores RIR.
  - Posibles issues a revisar (buscar en el código): foco, salida de rango (RIR negativo = fallo/forzada: `is_failure_set`), redondeo de decimales en el cálculo de RM (`rm_ajustado` usa `reps + 1 + rir`).
- **Cardio**:
  - `templates/cardio_day.html`: formulario por día para `cardio_annotations` (velocidad, inclinación, notas) sobre `EXERCISE_SESSION` de Health Connect.
  - `app.py`: `POST /cardio/annotation` guarda/elimina; `cardio_day` se renderiza en el popup/registro.
  - Cardio no forma todavía parte de la selección analítica del dashboard; en el registro es una sección del día.

## 5. Cambios propuestos (paso a paso)

### 5.1 Auditar y corregir controles RIR

1. Revisar `session_editor.html` + `editor.js`:
   - Asegurar `step="any"` en inputs RIR y que el incremento de botones es exactamente `0.1` (test 272 lo cubre; mantener).
   - Verificar que **RIR negativo** (o 0) muestra la marca FALLO/FORZADA correctamente en el editor y al guardar (`is_failure_set` en metrics_engine.py:13-15: `rir <= 0` o reps decimal).
   - Corregir cualquier bug de foco/teclado (ej.: tab salta el botón, atajo de teclado no actualiza el estado) — gate teclado/axe.
   - Decisión UI pendiente de confirmar: mantener el formato actual (input + botones) o cambiarlo a un stepper. **Recomendado**: conservar input editable + botones, asegurando accesibilidad.
2. Test unit nuevo si falta (validación de límites RIR y display FALLO/FORZADA), e2e de teclado en RIR.

### 5.2 Cardio como sección secundaria

1. En `templates/registro.html`, cardio como sección propia y colapsable, reutilizando `cardio_day.html`.
2. Mantener `POST /cardio/annotation` y sus OOB. Si se añaden métricas del día, definir primero qué campos de Health Connect están garantizados; `daily_cardio_minutes` es una opción, no una equivalencia con fuerza.
4. Tests e2e: cardio aparece/colapsa en `/registro`; navegar de fecha refresca cardio (replicar `test_cardio_refreshes_when_navigating_in_popup`).

### 5.3 Reorden de secciones del registro

1. Definir orden del día en `registro.html` (recomendado):
   ```
   1. Navegador de fecha
   2. Resumen del día (plan 9, si aplica)
   3. Entrenamiento (session-editor)
   4. Alimentación (nutrition-editor)
   5. Cardio (sección secundaria)
   6. Complementos (plantillas y altas → diálogos del plan 12)
   ```
   - Nota: hoy el popup tiene alimentación antes que sesión; el reorden se decide aquí (el usuario pidió separar mejor y cuidar el espacio).
2. Las plantillas de entrenamiento y de alimentación deben quedar visualmente junto a su editor (el master pide "plantillas de entrenamiento no separadas del editor").
3. Tests: e2e de que los controles están en el orden esperado y accesibles por teclado.

## 6. Pruebas a ejecutar

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e
uv run pytest tests/e2e/test_dashboard_flow.py -q --no-cov
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
uv run ruff format --check . && uv run ruff check . && uv run mypy app.py src tests
./scripts/build_css.sh
```

## 7. Riesgos

- **R1**: cambiar el orden de secciones (alimentación antes/después de sesión) puede romper tests que dependen del orden del DOM → usar selectores por id, no por posición.
- **R2**: las anotaciones de cardio no equivalen a métricas de fuerza; limitar este plan al registro y no forzar su entrada en la gráfica.
- **R3**: RIR es delicado (paso 0.1, rango, FALLO/FORZADA) — cualquier cambio de los controles debe mantener el test 272 y añadir e2e de teclado.

## 8. Criterios de aceptación

- RIR editable y persistente con paso 0.1, decimales libres, teclado OK, FALLO/FORZADA mostrados correctamente.
- Cardio es una sección secundaria colapsable en `/registro`, conectada a `EXERCISE_SESSION`/`cardio_annotations`.
- Secciones reordenadas en el flujo definido, con plantillas junto a su editor.
- Tests RIR/cardio/reorden verdes; gates verdes; axe sin violaciones.

## 9. Próximo plan

`2026-08-17-daily-record-secondary-forms.md` (diálogos compactos de alta de ejercicio/alimento y plantillas).
