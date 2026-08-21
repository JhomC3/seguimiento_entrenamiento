# Dashboard — Reconciliación de implementación y recuperación de fase

**Fecha:** 2026-08-18  
**Estado:** Fuente de verdad para la ejecución a partir de ahora  
**Alcance:** reconciliación entre los planes del 2026-08-17 y el código actualmente modificado.

## 1. Propósito

Los planes anteriores describen el resultado deseado, pero la implementación actual es parcial. Este documento reemplaza la lista anterior como cola de ejecución: cada tarea debe pasar de `pendiente` a `implementada` únicamente con código, pruebas y verificación visual.

Los planes fechados del 2026-08-17 se conservan en [`archive/`](archive/) como contexto y diseño detallado. No deben ejecutarse de nuevo de forma independiente ni interpretarse como evidencia de que el cambio ya está terminado.

## 2. Estado real observado

### Implementado parcialmente

- Layout de dashboard con dos columnas en `templates/index.html` y `static/css/cascade.css`.
- Ruta `/registro` y plantilla `templates/registro.html`.
- Eliminación visible del botón de exportación del header y del botón `ⓘ`.
- Parámetro experimental de granularidad `gran`.
- Cálculo parcial de gráficas por día/semana/mes en `src/charts.py`.
- Componente inicial `period_summary.html`.
- Uso de `Plotly.react` en el cliente.
- Navegación desde un punto de la gráfica hacia `/registro`.

### Implementado de forma incorrecta o incompleta

1. La vista sigue usando `week` como valor por defecto en backend y frontend; el requisito es `day`.
2. No existe un selector visible para cambiar entre día, semana y mes.
3. `chart_oob_wrapper` todavía reemplaza el shell `#unified-chart`; por tanto el nodo Plotly no es realmente persistente y `Plotly.react` no elimina por sí solo el parpadeo.
4. El listener de `plotly_click` usa un estado global (`_plotlyClickRegistered`), que puede impedir registrar el listener en un nodo nuevo si HTMX reemplaza el nodo.
5. La selección de un ejercicio actualiza la gráfica, pero no carga automáticamente el detalle en `#history-section`.
6. El catálogo no funciona todavía como el catálogo completo de `/splits`; los ejercicios siguen cargándose como una fila secundaria al seleccionar un músculo.
7. Cardio fue añadido como músculo virtual en `_cascade_items`, aunque no existe todavía un contrato de métricas comparable al de fuerza.
8. `/registro` conserva formularios grandes inline, plantillas separadas y el orden alimentación → entrenamiento.
9. El popup `#editor-popup` sigue activo y continúa siendo el acceso principal de registro.
10. El resumen es un grupo de tarjetas; todavía no existe la tabla por periodo solicitada.
11. Las rutas `/exportar/csv` y `/alimentacion/exportar/csv` fueron eliminadas, aunque la decisión aprobada era retirar la acción visible; la eliminación de los contratos HTTP no estaba confirmada.
12. `grafica_view` oculta errores del resumen con `except Exception: pass`, lo cual impide diagnosticar fallos.

## 3. Decisiones de producto para esta recuperación

Estas decisiones se consideran confirmadas por la solicitud inicial:

- El dashboard usa un catálogo izquierdo tipo `/splits`.
- La gráfica inicia por días.
- La gráfica muscular muestra global + músculo.
- La gráfica de ejercicios muestra músculo guía + ejercicios.
- El detalle del ejercicio aparece automáticamente al seleccionarlo.
- Los paneles conservan dimensiones estables.

Estas decisiones deben quedar bloqueadas antes de implementar sus tareas:

- Si global también aparece en la vista de ejercicio.
- Si las rutas CSV se restauran o se retiran definitivamente.
- Si `/registro` reemplaza al popup o ambos conviven.
- Si cardio tendrá analítica en el dashboard o solo será una sección del registro.
- Qué métricas exactas tendrá la tabla de resumen.

## 4. Nueva cola de ejecución

### Recuperación 1 — Dashboard vertical mínimo

**Objetivo:** completar el dashboard analítico sin tocar todavía `/registro`.

Incluye:

- Elegir y documentar las decisiones pendientes de la sección 3.
- Mantener el shell de `#unified-chart` y actualizar únicamente datos inertes.
- Usar un nodo Plotly persistente con `Plotly.react`.
- Eliminar respuestas OOB duplicadas entre `/nivel` y `/grafica`.
- Hacer que el clic de ejercicio actualice gráfica y detalle.
- Mantener la gráfica en la vista actual mientras se corrige la interacción.

**Archivos probables:** `app.py`, `src/response_fragments.py`, `static/js/chart-interaction.js`, `static/js/level-cascade.js`, `templates/index.html`, `templates/ejercicios_row.html`, tests del dashboard.

**Aceptación:** un clic de músculo o ejercicio produce una sola actualización visual de la gráfica, sin área en blanco, sin cambio de `offsetTop` y con detalle automático.

### Recuperación 2 — Catálogo izquierdo definitivo

**Objetivo:** que el panel izquierdo funcione como catálogo navegable, no como una fila que aparece debajo.

Incluye:

- Músculos y ejercicios agrupados de forma estable.
- Selección y expansión sin cambiar la altura de la columna analítica.
- Scroll interno y responsive.
- Sin búsqueda nueva en esta tarea.

**Aceptación:** desktop tipo `/splits`, móvil sin overflow horizontal, teclado usable y selección restaurada desde URL.

### Recuperación 3 — Granularidad y tabla

**Objetivo:** completar el análisis temporal.

Incluye:

- Selector visible día/semana/mes.
- Día como valor por defecto en backend, URL y UI.
- Tabla de periodos sincronizada con la gráfica.
- Definición explícita de días con datos frente a días imputados.
- Cálculos server-side y estado vacío/error visible.

**Aceptación:** cambiar el selector actualiza gráfica, tooltip, tabla y URL sin perder selección.

### Recuperación 4 — Registro diario

**Objetivo:** convertir `/registro` en un flujo diario realmente usable.

Incluye:

- Orden: fecha → resumen → entrenamiento → alimentación → cardio → complementos.
- Plantillas junto al editor correspondiente.
- Formularios de alta en diálogos compactos.
- Auditoría de RIR.
- Pruebas de save, eliminar, undo, navegación y accesibilidad.

El popup permanece durante esta recuperación.

### Recuperación 5 — Decisión del popup y cierre

Solo después de utilizar y probar `/registro` se decide si el popup se retira. La decisión y sus cambios de rutas quedan documentados en [`archive/2026-08-17-daily-record-popup-retirement.md`](archive/2026-08-17-daily-record-popup-retirement.md).

## 5. Criterios de cierre de la fase

- No quedan requisitos del usuario clasificados como “parcial” sin una tarea asociada.
- Todas las tareas de recuperación tienen tests unitarios/integración y E2E cuando corresponda.
- `day` es el valor predeterminado comprobado por backend, URL, UI y tests.
- No hay swaps que reemplacen el nodo Plotly persistente.
- La selección de ejercicio muestra su detalle automáticamente.
- `/registro` tiene el orden y densidad visual definidos.
- No se eliminan rutas HTTP sin decisión documentada.
- La suite se ejecuta con una caché dentro de `.tmp/` si la caché externa de `uv` permanece bloqueada:

```bash
UV_CACHE_DIR=.tmp/uv-cache uv sync --locked
UV_CACHE_DIR=.tmp/uv-cache uv run pytest --ignore=tests/e2e
```

## 6. Próximo trabajo autorizado

El siguiente plan atómico debe ser **Recuperación 1 — Dashboard vertical mínimo**. No se debe comenzar por `/registro`, meses, cardio analítico ni eliminación del popup hasta que la interacción base del dashboard esté cerrada.
