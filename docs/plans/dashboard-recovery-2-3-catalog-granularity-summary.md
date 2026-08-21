# Plan de recuperación 2–3: catálogo, granularidad y resumen del dashboard

**Fecha:** 2026-08-18  
**Estado:** aprobado para ejecución secuencial; pendiente de implementación y validación  
**Alcance:** dashboard principal (`/`), su gráfica, catálogo de selección y resumen del período

## 1. Propósito

Este documento convierte los problemas observados en la pantalla del dashboard en un plan ejecutable. Corrige tres fallas visibles de la entrega anterior:

1. El panel izquierdo no se comporta ni se ve como el catálogo de splits.
2. La gráfica sigue usando semanas y no ofrece día/semana/mes.
3. No hay una jerarquía visual clara entre Global, músculo y ejercicio.

También define el resumen que debe acompañar a la gráfica y los estados vacíos, de carga y de error.

Este plan no autoriza todavía cambios en `/registro`, el popup de registro, cardio, alimentación ni el catálogo de datos. Esas tareas pertenecen a fases posteriores.

## 2. Documentos de referencia

- [Brecha y recuperación general](./dashboard-implementation-gap-and-recovery.md): fuente de alcance y orden de recuperación.
- [Contrato vigente de UI](../architecture/current-ui-contract.md): htmx, OOB, selección y gráfica única.
- [Estándares web](../architecture/web-standards.md): server-first, tokens, accesibilidad, CLS y estados de UI.
- [Estándares backend](../architecture/backend-standards.md): separación handler/servicio/base de datos y pruebas.
- [Plan de recuperación vertical](./dashboard-recovery-1-vertical-slice.md): contiene cambios recientes de la shell persistente de la gráfica; aquí se toma como trabajo existente en el árbol, no como trabajo validado.

## 3. Estado real que debe tomarse como base

La implementación actual no debe describirse como terminada ni testeada hasta ejecutar los gates. Antes de empezar la Fase A, el agente debe registrar el estado real de la rama y comprobar, como mínimo:

- `templates/index.html` todavía usa la estructura de filas/cascada anterior en lugar de un catálogo estable tipo splits.
- `static/js/level-cascade.js` conserva estado y nombres asociados a `week` y no presenta un contrato completo para `day` y `month`.
- `src/charts.py` contiene agregación de períodos y su trazado debe revisarse: no se puede asumir que el eje utiliza correctamente día, semana y mes.
- `period_summary` está incompleto para el objetivo de una tabla por período.
- El contraste de las series Global y Compilado/Músculo no está resuelto de forma inequívoca.
- `#period-summary` puede estar presente como contenedor vacío sin un estado funcional claro.

Si una de estas observaciones ya no aplica, se documentará la evidencia y se conservará el contrato, no se duplicará trabajo.

## 4. Decisiones funcionales cerradas

### 4.1 Catálogo

- El catálogo vive a la izquierda, con ancho y posición estables, siguiendo el patrón visual y espacial del gestor de splits.
- El catálogo muestra primero músculos/grupos y, al expandir uno, sus ejercicios.
- Cada músculo y ejercicio tiene una acción de selección y una acción de expansión claramente distinguibles.
- No se añadirá búsqueda en esta fase. No es necesaria para validar la navegación y ampliaría el alcance.
- No habrá un botón de información por ejercicio. La información se muestra automáticamente en el resumen al seleccionar el elemento.

### 4.2 Granularidad

- Valores permitidos: `day`, `week`, `month`.
- El valor por defecto es `day`.
- La selección debe existir en backend, URL/estado htmx, JavaScript y UI; no se aceptará una opción que solo cambie la etiqueta.
- La vista diaria solo incluirá días con datos de entrenamiento válidos para la selección actual. No se inventarán puntos para días de descanso.
- Las etiquetas serán fechas legibles y estables: día (`18 ago`), semana (`Sem. 34` o rango) y mes (`ago 2026`).

### 4.3 Jerarquía de series

La regla depende de la selección, no de la granularidad:

| Selección | Línea guía | Series adicionales |
|---|---|---|
| Global | Global | ninguna |
| Uno o más músculos | Global | una línea por músculo seleccionado |
| Un músculo con ejercicios seleccionados | Músculo seleccionado | Global + líneas de los ejercicios seleccionados |

Global permanece visible en una única línea en los tres niveles. En el nivel ejercicio, la línea del músculo es la guía principal y Global queda como referencia secundaria. Esta decisión está cerrada; el agente no puede ocultar Global ni sustituirlo por una línea llamada únicamente `Compilado`.

Reglas visuales mínimas:

- Global: línea principal, más visible y con color de token canónico.
- Músculo compilado: color distinto y menor opacidad que Global cuando ambos aparecen.
- Ejercicios: colores derivados de la paleta de gráficos, consistentes dentro de la selección.
- La leyenda debe decir `Global`, `Músculo — <nombre>` y `Ejercicio — <nombre>`; nunca `Compilado` sin contexto.
- No se usarán hexadecimales literales en templates, JS ni CSS. Se usarán tokens y la paleta existente (`chart_color(...)`, variables CSS o equivalente aprobado).

### 4.4 Resumen

La gráfica y el resumen deben compartir exactamente selección y granularidad.

El resumen tendrá:

- tarjetas compactas: períodos con datos, sesiones, volumen/carga agregada y mejor rendimiento disponible;
- tabla de períodos, ordenada cronológicamente, con fecha/período, sesiones, ejercicios, series y métrica principal;
- encabezado que indique el nivel actual: Global, músculo o ejercicio;
- estados `loading`, `empty`, `error` y `ready`.

Las definiciones exactas de volumen y mejor rendimiento deben reutilizar las métricas existentes. Si una métrica no tiene una definición compatible con todos los niveles, se mostrará `—` y se documentará la razón; no se calculará una aproximación silenciosa.

## 5. Contratos de interacción

### 5.1 Expansión y selección del catálogo

- Clic en el control de expansión abre/cierra el grupo sin cambiar la selección.
- Clic en el nombre selecciona el grupo o ejercicio y actualiza gráfica y resumen.
- Teclado: los controles son botones nativos, tienen foco visible y funcionan con `Enter` y barra espaciadora.
- `Shift+click` conserva la multiselección de músculos solo donde ya lo contempla el contrato vigente.
- No se añadirá `role="button"` a elementos que ya sean `<button>`.
- La expansión del catálogo no debe cambiar la altura de la gráfica ni desplazar el resto de la página; el contenido expandido usará scroll interno o un espacio reservado.

### 5.2 Granularidad

- El selector será un control nativo visible (`select` o grupo de botones accesibles) ubicado fuera del contenedor que Plotly reemplaza.
- Debe permanecer montado al recibir swaps OOB de la gráfica.
- Cambiar la granularidad conserva selección, restablece la página/scroll solo si es necesario y actualiza gráfica, leyenda y resumen en una operación lógica.
- Debe existir un estado de carga no disruptivo mientras se procesa la nueva selección.

### 5.3 Transiciones

- La shell de Plotly se conserva; no se reemplaza el contenedor completo en cada clic.
- La actualización de datos usa `Plotly.react` o el mecanismo equivalente ya adoptado.
- No se deben producir parpadeos, saltos verticales ni destrucción/recreación del canvas.
- `prefers-reduced-motion` debe desactivar o reducir la animación.
- Un cambio de selección no debe modificar el tamaño de las tarjetas ni del panel principal.

## 6. Arquitectura obligatoria

### 6.1 Datos y backend

- Las consultas SQLite permanecen en `src/database.py`.
- La construcción del catálogo debe vivir en una función de lectura dedicada, por ejemplo `get_dashboard_catalog(...)`.
- La agregación de períodos y el armado del resumen deben vivir en `src/summary_service.py` o en una capa de análisis equivalente; no en `app.py`, templates ni `src/charts.py` si la función es de resumen.
- `src/charts.py` debe concentrarse en series y configuración de gráficos. Si necesita datos, los recibe ya agregados desde el servicio apropiado.
- El handler solo parsea/valida parámetros, invoca el servicio y devuelve el fragmento correspondiente.
- Los parámetros inválidos (`granularity`, nivel, foco) devuelven un error de dominio seguro, no una caída ni un fallback silencioso.

### 6.2 Respuesta y sincronización

Se preferirá una respuesta de `/grafica` que actualice objetivos OOB disjuntos:

- shell/datos de gráfica;
- leyenda o encabezado;
- resumen y tabla.

El selector y el catálogo no deben estar dentro de esos objetivos. Si se conserva un endpoint `/resumen` separado, deberá existir una secuencia explícita de selección y una prueba que demuestre que no puede quedar desfasado respecto de la gráfica. No se creará una ruta nueva sin justificarlo en el diff.

### 6.3 Errores y observabilidad

- Eliminar `except Exception: pass` y cualquier captura que oculte un fallo del resumen o la gráfica.
- No se prohíben todas las capturas amplias: las excepciones seguras ya justificadas en helpers de lectura deben conservar su contrato y registrar el fallo cuando corresponda.
- Los errores inesperados deben registrarse server-side con contexto y devolver un estado visible para el usuario.

## 7. Protocolo obligatorio para el agente ejecutor

Este documento debe ejecutarse como una secuencia de tareas atómicas. Un agente no puede interpretar “Fase A”, “Fase B”, “Fase C” o “Fase D” como permiso para modificar todo el dashboard de una vez.

Reglas obligatorias:

1. Ejecutar una sola tarea `A*`, `B*`, `C*` o `D*` por turno.
2. Leer primero los archivos indicados en la tarea y comprobar que el código coincide con la evidencia de la sección 3.
3. Modificar únicamente los archivos listados como permitidos en esa tarea.
4. No crear endpoints, migraciones, dependencias, búsquedas ni rediseños fuera de este plan.
5. Ejecutar las pruebas de la tarea antes de pasar a la siguiente.
6. Si una prueba falla por un comportamiento anterior que el contrato ahora cambia, actualizar la prueba solo si el cambio está justificado en este documento.
7. Si aparece una contradicción no resuelta, detenerse y reportarla; no elegir una solución por cuenta propia.
8. No marcar una tarea como completa si solo se escribió código: debe existir evidencia de prueba y, cuando corresponda, captura visual.
9. No hacer commit ni modificar planes archivados.

### Formato de reporte obligatorio después de cada tarea

```text
Tarea: A1
Estado: completada | bloqueada
Archivos modificados:
Cambios realizados:
Pruebas ejecutadas y resultado:
Comprobación visual:
Pendientes o riesgos:
Siguiente tarea autorizada:
```

## 8. Tareas atómicas

Las tareas deben ejecutarse en orden. Cada tarea tiene un límite claro.

### Fase 0 — Preparación y bloqueo de contrato

#### Tarea P0 — Verificación de precondiciones

**Objetivo:** confirmar que Recovery 1 ya terminó o detenerse.

**Leer:** `docs/plans/dashboard-implementation-gap-and-recovery.md`, `docs/plans/dashboard-recovery-1-vertical-slice.md`, `git status`, tests del dashboard.

**No modificar:** código de la aplicación.

**Resultado requerido:** informe de qué criterios de Recovery 1 pasan y cuáles no. Si Recovery 1 no está validada, el agente debe detenerse y no ejecutar A1.

#### Tarea P1 — Verificar el contrato de series

**Objetivo:** comprobar que el agente leyó y aplicará la matriz cerrada de la sección 4.3.

**Resultado requerido:** el reporte debe repetir la matriz: Global siempre visible; músculo añadido en selección muscular; músculo guía + ejercicios en selección de ejercicio. Si el usuario cambia esta decisión, detener el plan y actualizar este documento antes de continuar.

### Fase A — Catálogo tipo splits

#### Tarea A1 — Modelo de datos del catálogo

**Objetivo:** devolver grupos y ejercicios en una estructura estable.

**Archivos permitidos:** `src/database.py`, `src/dashboard_service.py`, tests unitarios de servicio/base de datos.

**Hacer:** crear o adaptar una lectura tipada del catálogo; ordenar grupos y ejercicios determinísticamente; no incluir lógica HTML.

**No hacer:** cambiar rutas, CSS, JS, gráfica o base de datos.

**Pruebas:** grupo vacío, grupo con ejercicios, nombres duplicados y orden estable.

**Terminado cuando:** el servicio entrega un view model completo y los tests pasan.

#### Tarea A2 — Partial HTML del catálogo

**Objetivo:** renderizar el catálogo sin conectarlo todavía a la gráfica.

**Archivos permitidos:** `templates/index.html`, un partial nuevo dentro de `templates/partials/`, tests de render.

**Hacer:** crear controles nativos separados para expandir y seleccionar; incluir estados vacío y error; retirar el botón `ⓘ`.

**No hacer:** usar `role="button"` sobre `<button>`, añadir búsqueda o modificar Plotly.

**Pruebas:** presencia de labels, botones, foco y ausencia de `ⓘ`.

**Terminado cuando:** el HTML es semántico y se puede inspeccionar sin JavaScript.

#### Tarea A3 — Layout estable del catálogo

**Objetivo:** colocar el catálogo a la izquierda como el panel de splits.

**Archivos permitidos:** `static/css/cascade.css`, CSS de componentes si es estrictamente necesario, templates del catálogo.

**Hacer:** definir columna, ancho mínimo/máximo, scroll interno, `min-height` y comportamiento responsive usando tokens existentes.

**No hacer:** hexadecimales literales, clases Tailwind no compiladas ni alterar dimensiones por contenido expandido.

**Pruebas:** `audit_consistency.py`, revisión visual desktop/móvil y medición de altura antes/después de expandir.

**Terminado cuando:** expandir el catálogo no mueve la gráfica ni cambia la altura del panel analítico.

#### Tarea A4 — Estado de selección del catálogo

**Objetivo:** conectar selección y expansión sin implementar aún el contrato final de series.

**Archivos permitidos:** `static/js/level-cascade.js`, tests E2E del dashboard.

**Hacer:** separar eventos de expandir y seleccionar; conservar selección en `pushState`/`popstate`; mantener foco visible; cancelar respuestas obsoletas.

**No hacer:** modificar la agregación de gráficos ni introducir un segundo store global.

**Pruebas:** click músculo, expandir músculo sin seleccionar, click ejercicio, back/forward y doble click rápido.

**Terminado cuando:** la UI refleja la selección correcta sin saltos y los tests E2E de interacción pasan.

#### Tarea A5 — Cierre de catálogo

**Objetivo:** verificar la Fase A antes de continuar.

**Archivos permitidos:** tests y documentación de contrato únicamente.

**Hacer:** ejecutar la matriz A1–A4, capturar pantalla y actualizar el estado de la fase.

**Terminado cuando:** no hay regresiones y el reporte obligatorio incluye diff, pruebas y captura. Si falla, corregir A1–A4; no comenzar B.

### Fase B — Granularidad y líneas de la gráfica

#### Tarea B1 — Tipo y valor por defecto de granularidad

**Archivos permitidos:** `app.py`, `src/dashboard_service.py`, `static/js/level-cascade.js`, tests de parámetros.

**Hacer:** aceptar solo `day|week|month`; usar `day` por defecto en backend, URL y estado inicial; devolver error seguro ante valor inválido.

**No hacer:** tocar todavía colores, resumen o HTML de la tabla.

**Pruebas:** ausencia del parámetro, cada valor válido y valor inválido.

#### Tarea B2 — Agregación diaria

**Archivos permitidos:** `src/charts.py`, capa de datos existente, tests de charts.

**Hacer:** usar fechas reales como eje; incluir solo días con datos válidos; comprobar orden cronológico y tooltip.

**No hacer:** reutilizar `semana` como eje diario ni inventar puntos de descanso.

**Pruebas:** un día, varios días, hueco entre entrenamientos y datos nulos.

#### Tarea B3 — Agregación semanal y mensual

**Archivos permitidos:** `src/charts.py`, tests de charts.

**Hacer:** agrupar correctamente por semana ISO y mes calendario; producir labels inequívocos.

**No hacer:** cambiar la semántica de las métricas existentes sin documentarlo.

**Pruebas:** cambio de mes, cruce de año, semanas ISO y múltiples sesiones en un período.

#### Tarea B4 — Matriz Global/músculo/ejercicio

**Archivos permitidos:** `src/charts.py`, `src/dashboard_service.py`, tests de charts.

**Hacer:** implementar exactamente la matriz cerrada: Global siempre; músculo añadido en selección muscular; músculo guía y ejercicios añadidos en selección de ejercicio.

**No hacer:** crear trazas llamadas solo `Compilado`, ocultar Global o cambiar el cálculo de rendimiento.

**Pruebas:** global, un músculo, varios músculos, un ejercicio y varios ejercicios.

#### Tarea B5 — Colores, opacidad y leyenda

**Archivos permitidos:** `src/charts.py`, tokens/paleta existente, tests de configuración de figuras.

**Hacer:** aplicar tokens; Global más visible; músculo guía diferenciado y más transparente; ejercicios identificables; leyenda contextual.

**No hacer:** hexadecimales literales ni colores idénticos para Global y músculo.

**Pruebas:** inspeccionar nombres, color, opacidad y orden de cada traza.

#### Tarea B6 — Selector estable fuera de Plotly

**Archivos permitidos:** templates del dashboard, `static/js/level-cascade.js`, CSS del dashboard, tests E2E.

**Hacer:** colocar selector fuera de `#unified-chart`/targets OOB; actualizar selección, URL, gráfica y estado de carga.

**No hacer:** insertar el selector dentro del fragmento que Plotly reemplaza.

**Pruebas:** cambiar día/semana/mes después de seleccionar músculo y comprobar que el selector permanece.

#### Tarea B7 — Shell persistente y transición

**Archivos permitidos:** `src/response_fragments.py`, `src/dashboard_service.py`, `static/js/chart-interaction.js`, CSS estrictamente necesario, tests E2E.

**Hacer:** mantener el nodo Plotly; actualizar datos con `Plotly.react`; manejar vacío/cargado; respetar `prefers-reduced-motion`.

**No hacer:** reemplazar el shell completo en cada clic ni añadir `setTimeout` como solución al parpadeo.

**Pruebas:** identidad del nodo tras tres selecciones, medición de altura/offset y cambio rápido de selección.

#### Tarea B8 — Cierre de gráfica

**Objetivo:** validar B antes del resumen.

**Terminado cuando:** B1–B7 pasan, la captura muestra las tres granularidades y la leyenda distingue Global/músculo/ejercicio.

### Fase C — Resumen y tabla

#### Tarea C1 — Consulta de datos del resumen

**Archivos permitidos:** `src/database.py`, tests de integración de lectura.

**Hacer:** exponer datos mínimos por período sin HTML ni agregación visual.

**No hacer:** SQL en `app.py`, `src/charts.py` o templates.

#### Tarea C2 — Servicio de resumen

**Archivos permitidos:** `src/summary_service.py`, `src/dashboard_service.py`, tests unitarios.

**Hacer:** convertir datos en tarjetas y filas; reutilizar definiciones de métricas; devolver `ready`, `empty` o `error` explícito.

**No hacer:** devolver un diccionario ambiguo o capturar errores con `pass`.

#### Tarea C3 — Template de tarjetas y tabla

**Archivos permitidos:** template/partial del resumen, CSS de componentes, tests de render.

**Hacer:** mostrar nivel, granularidad, tarjetas, tabla y estados; usar `—` si la métrica no aplica.

**No hacer:** dejar un contenedor blanco sin texto.

#### Tarea C4 — Sincronización con la gráfica

**Archivos permitidos:** `app.py`, `src/response_fragments.py`, `src/dashboard_service.py`, JS del dashboard, tests de integración/E2E.

**Hacer:** actualizar gráfica y resumen desde la misma selección y granularidad; preferir targets OOB disjuntos en la misma respuesta.

**No hacer:** permitir que una respuesta vieja sobrescriba el resumen actual.

#### Tarea C5 — Estados y errores

**Archivos permitidos:** servicio, template, tests.

**Hacer:** probar sin datos, error recuperable y selección sin métrica aplicable; registrar errores server-side.

#### Tarea C6 — Cierre de resumen

**Terminado cuando:** el panel ya no está vacío sin explicación, la tabla cambia con día/semana/mes y la selección del catálogo actualiza el nivel mostrado.

### Fase D — Integración y documentación

#### Tarea D1 — Suite completa

Ejecutar la matriz de pruebas de la sección 9. No corregir fallos no relacionados dentro de esta fase: registrarlos como bloqueos.

#### Tarea D2 — Auditoría visual y accesibilidad

Comprobar desktop/móvil, teclado, foco, contraste, `prefers-reduced-motion`, estados vacío/error y ausencia de layout shift.

#### Tarea D3 — CSS compilado

Si se modificaron templates o clases Tailwind, ejecutar `./scripts/build_css.sh` y verificar que el CSS generado forma parte del diff esperado.

#### Tarea D4 — Contratos documentales

Actualizar `docs/architecture/current-ui-contract.md` y `docs/plans/dashboard-implementation-gap-and-recovery.md` solo con el comportamiento realmente verificado.

#### Tarea D5 — Revisión de alcance

Confirmar que no se modificaron `/registro`, popup, cardio analítico, alimentación, CSV ni migraciones.

#### Tarea D6 — Cierre

Marcar A, B, C y D por separado. El plan completo solo se cierra si todas tienen reporte, pruebas y evidencia visual.

## 9. Matriz mínima de pruebas

| Caso | Debe comprobar |
|---|---|
| Carga inicial | Default `day`, Global visible, selector estable |
| Selección de músculo | Global + línea del músculo, leyenda inequívoca |
| Selección de ejercicio | Global + músculo guía + ejercicio, sin parpadeo |
| Cambio día/semana/mes | Eje, agregación, tabla y tarjetas sincronizados |
| Expandir/contraer catálogo | Sin cambio de tamaño ni desplazamiento de la gráfica |
| Sin datos | Estado vacío explicativo, no panel en blanco |
| Error de backend | Estado error visible, sin `pass` silencioso |
| Teclado | Expandir, seleccionar y cambiar granularidad con foco visible |
| Movimiento reducido | Sin animación incompatible con la preferencia del usuario |

Comandos obligatorios para D1 y, cuando corresponda, después de cada fase:

```bash
UV_CACHE_DIR=.tmp/uv-cache uv sync --locked
UV_CACHE_DIR=.tmp/uv-cache uv run pytest --ignore=tests/e2e
UV_CACHE_DIR=.tmp/uv-cache uv run pytest tests/e2e -q --no-cov
UV_CACHE_DIR=.tmp/uv-cache uv run ruff format --check .
UV_CACHE_DIR=.tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=.tmp/uv-cache uv run mypy app.py src tests
```

Si cambian templates o clases Tailwind:

```bash
./scripts/build_css.sh
```

## 10. Criterios de cierre

El plan se considera completado solo cuando:

- P0, P1, A1–A5, B1–B8, C1–C6 y D1–D6 tienen estado y reporte.
- Recovery 1 estaba validada antes de comenzar A1.
- La captura final demuestra catálogo izquierdo, selector día/semana/mes, Global/músculo/ejercicio diferenciados y resumen con datos o estado explícito.
- La matriz mínima pasa.
- No hay cambios visuales sin CSS compilado.
- La documentación refleja el comportamiento real.
- No se mezclan en este alcance `/registro`, popup, cardio o alimentación.

## 11. Orden de ejecución

`P0 → P1 → A1 → A2 → A3 → A4 → A5 → B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → C1 → C2 → C3 → C4 → C5 → C6 → D1 → D2 → D3 → D4 → D5 → D6`.

La única siguiente tarea autorizada, una vez cumplida la precondición, es `P0`. Si P0 confirma que Recovery 1 sigue pendiente, el agente debe detenerse y continuar con `dashboard-recovery-1-vertical-slice.md`.
