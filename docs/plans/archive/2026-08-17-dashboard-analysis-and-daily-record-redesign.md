# Plan maestro: rediseño del dashboard y registro diario

**Fecha:** 2026-08-17  
**Estado:** Reconciliado el 2026-08-18; consultar `docs/plans/dashboard-implementation-gap-and-recovery.md` para la ejecución vigente  
**Alcance:** dashboard analítico, selección de ejercicios, gráficas, resúmenes y flujo de registro diario.

## 1. Propósito

> **Aviso de ejecución:** este documento conserva el diseño y el historial de decisiones. La implementación real quedó parcial; desde el 2026-08-18 la cola operativa y el estado verificable viven en [dashboard-implementation-gap-and-recovery.md](dashboard-implementation-gap-and-recovery.md). Los planes atómicos fechados del 2026-08-17 no deben ejecutarse nuevamente sin pasar por esa reconciliación.

Rediseñar la experiencia principal del dashboard para que use el espacio como la página de splits, mantenga un layout estable al seleccionar músculos y ejercicios, presente gráficas coherentes por nivel de análisis y separe el análisis histórico del registro diario de entrenamiento y alimentación.

El trabajo se dividirá en planes atómicos. Cada plan deberá poder implementarse, probarse y revisarse de forma independiente.

## 2. Problemas que se quieren resolver

### Layout y navegación

- El catálogo de músculos y ejercicios ocupa una posición poco eficiente.
- La página no aprovecha todo el ancho disponible.
- La aparición de ejercicios cambia la altura de los paneles y desplaza la gráfica.
- Hay controles secundarios que ocupan demasiado espacio.
- El botón de información de cada ejercicio no aporta valor suficiente.
- El botón visible de exportar CSV no forma parte del flujo actual.

### Selección y gráfica

- La gráfica parpadea al cambiar la selección.
- El scroll y la posición visual cambian cuando se actualiza la cascada.
- Las líneas globales, musculares y de ejercicios no siguen una jerarquía suficientemente clara.
- Las transiciones de Plotly son bruscas o provocan reconstrucciones innecesarias.

### Análisis temporal

- El análisis está demasiado orientado a semanas.
- No existe un selector integrado para días, semanas y meses.
- El resumen no está sincronizado claramente con la granularidad de la gráfica.

### Registro diario

- El popup concentra demasiadas funciones diferentes.
- Alimentación, entrenamiento, cardio, plantillas y creación de catálogos aparecen mezclados.
- Los formularios de nuevo ejercicio y nuevo alimento ocupan demasiado espacio.
- Las plantillas de entrenamiento quedan visualmente separadas del editor.
- Los controles de RIR necesitan revisión funcional.
- El panel de cardio debe simplificarse o integrarse como sección secundaria.

## 3. Principios de diseño

1. **Layout estable:** seleccionar elementos no debe cambiar la altura de los paneles ni desplazar la gráfica.
2. **Server-first:** el servidor sigue siendo responsable de la selección, agregación, métricas y resúmenes; JavaScript solo mejora la interacción.
3. **Actualizaciones parciales:** HTMX debe reemplazar únicamente las zonas necesarias.
4. **Estado explícito:** la interfaz debe distinguir entre global, músculo y ejercicio.
5. **Una sola fuente visual:** utilizar componentes y tokens existentes, especialmente los patrones consolidados en `/splits`.
6. **Análisis y registro separados:** el dashboard sirve para entender la progresión; el registro diario sirve para introducir datos.
7. **Cada cambio de contrato lleva pruebas:** backend, HTML, comportamiento HTMX y E2E cuando corresponda.

## 4. Resultado objetivo

```text
Dashboard analítico
├── Panel izquierdo fijo
│   ├── Global
│   ├── Músculos
│   │   └── Ejercicios desplegables
│   └── Selector: días / semanas / meses
└── Panel derecho
    ├── Gráfica con transiciones suaves
    ├── Resumen de la selección y del periodo
    └── Detalle del músculo o ejercicio

Registro diario
├── Navegación de fecha
├── Resumen del día
├── Entrenamiento
├── Alimentación
└── Complementos: cardio y plantillas
```

## 5. Fases de trabajo

### Fase 0 — Contrato y línea base

Documentar el comportamiento actual, identificar los fragmentos HTMX implicados y establecer pruebas de regresión antes de modificar el layout.

**Salida:** contrato funcional revisado y lista de casos de prueba.

### Fase 1 — Estabilidad visual y limpieza

- Retirar el botón visible de exportar CSV.
- Retirar los botones de información de ejercicios.
- Fijar alturas, espacios y zonas de scroll.
- Evitar cambios de layout al expandir músculos.
- Corregir el parpadeo básico causado por swaps HTMX.

**Salida:** el dashboard deja de saltar aunque la lógica de selección todavía sea la actual.

### Fase 2 — Layout tipo splits

- Llevar el catálogo de ejercicios al lado izquierdo.
- Crear una columna analítica derecha.
- Aplicar panel sticky y scroll interno según el patrón de `/splits`.
- Mantener una estructura reservada para ejercicios aunque no haya ninguno visible.
- Verificar responsive y teclado.

**Salida:** dashboard de ancho completo con layout estable.

### Fase 3 — Semántica de selección y líneas

- Definir estado global.
- Definir estado de músculo.
- Definir estado de ejercicio.
- Mantener global en la vista global.
- Mostrar global más músculo en la vista muscular.
- Mostrar músculo guía más ejercicios en la vista de ejercicio.
- Mantener selección, foco y acordeones después de cada actualización.

**Salida:** selección y gráfica siguen una jerarquía predecible.

### Fase 4 — Grupos temporales y resúmenes

- Añadir agrupación diaria como valor por defecto.
- Añadir agrupación semanal.
- Añadir agrupación mensual.
- Sincronizar agrupación, ejes, tooltip y resumen.
- Definir métricas de resumen para cada granularidad.

**Salida:** gráfica y resumen responden al mismo periodo de análisis.

### Fase 5 — Página de registro diario

- Crear la página dedicada de registro diario.
- Reutilizar los servicios y fragmentos existentes.
- Reordenar entrenamiento, alimentación, cardio y plantillas.
- Convertir creación de ejercicio y alimento en diálogos compactos.
- Mantener el popup como acceso rápido desde la gráfica, si sigue siendo necesario.
- Revisar y corregir los controles de RIR.

**Salida:** flujo diario claro, compacto y utilizable.

### Fase 6 — Validación y limpieza final

- Pruebas unitarias e integración.
- Pruebas E2E de selección y registro.
- Auditoría visual y de consistencia.
- Verificación de accesibilidad.
- Revisión de rutas de exportación y eliminación de código muerto solo después de confirmar el alcance.

**Salida:** cambio listo para revisión final, sin commit automático.

## 6. Backlog de planes atómicos

Planes activos creados (2026-08-17):

1. `2026-08-17-dashboard-baseline-and-contract.md` — ✅ completado: investigación y línea base, sin cambios de aplicación.
2. `2026-08-17-dashboard-remove-secondary-actions.md` — pendiente: retira el botón visible de exportación y el botón `ⓘ`; retirar rutas de exportación requiere una decisión explícita.
3. `2026-08-17-dashboard-stable-layout.md` — ✅ revisado. Estabilidad de zonas y criterios de medición.
4. `2026-08-17-dashboard-left-exercise-catalog.md` — ✅ revisado. Layout 2 columnas tipo splits.
5. `2026-08-17-dashboard-selection-state.md` — pendiente: estado global/músculo/ejercicio y URL única. Cardio queda separado hasta confirmar su analítica.
6. `2026-08-17-dashboard-chart-transition.md` — pendiente: nodo Plotly persistente, una sola responsabilidad por respuesta y motion reducido.
7. `2026-08-17-dashboard-chart-series-semantics.md` — pendiente: implementar y blindar el contrato de líneas solicitado.
8. `2026-08-17-dashboard-time-granularity.md` — ✅ revisado. Día/semana/mes, día por defecto y decisión sobre días imputados.
9. `2026-08-17-dashboard-period-summary.md` — ✅ revisado. Resumen + tabla; métricas pendientes de definición final.
10. `2026-08-17-daily-record-page.md` — pendiente: página `/registro` en convivencia temporal con el popup.
11. `2026-08-17-daily-record-editor-controls.md` — pendiente: auditoría de RIR, cardio como sección y reorden.
12. `2026-08-17-daily-record-secondary-forms.md` — ✅ revisado. Diálogos compactos de altas/plantillas.
13. `2026-08-17-daily-record-popup-retirement.md` — pendiente: decisión y retiro seguro del popup, solo tras validar `/registro`.
14. `2026-08-17-dashboard-e2e-validation.md` — pendiente: validación final.

Todos los archivos llevan prefijo `2026-08-17-` en `docs/plans/`. Salvo las decisiones explícitamente listadas a continuación, los planes son propuestas de implementación que requieren revisión al iniciarse; no son aprobaciones implícitas del usuario.

## 7. Decisiones y límites de producto

### Confirmadas por la solicitud inicial

- El catálogo de músculos y ejercicios pasa a la izquierda, con el uso de espacio y estabilidad de `/splits` como referencia.
- Se elimina el botón visible de exportación CSV del dashboard y el botón de información `ⓘ` de cada ejercicio.
- Los paneles no deben cambiar de tamaño ni desplazar la gráfica al seleccionar elementos.
- La vista temporal predeterminada es por día, con alternativas por semana y mes.
- Gráfica muscular: global como referencia permanente más la línea del músculo seleccionado.
- Gráfica de ejercicios: la línea guía pasa a ser el músculo y se añaden los ejercicios seleccionados.

### Pendientes de una decisión explícita

- Retirar rutas de exportación (`/exportar/csv` y/o `/alimentacion/exportar/csv`) frente a ocultar únicamente la UI.
- Mantener u ocultar global también en la vista de ejercicio. La interpretación operativa propuesta es ocultarlo para priorizar músculo + ejercicios, pero debe confirmarse antes de codificarla.
- Métricas, definición de "peso" y alcance de la tabla de resumen.
- Crear `/registro` como página principal y retirar el popup: el usuario pidió evaluar esta opción, no confirmó todavía la eliminación del popup.
- Tratar cardio como grupo analítico del dashboard. Por ahora queda como sección secundaria del registro; su modelo de métricas no es equivalente al PFR de fuerza.

## 8. Criterios globales de aceptación

- La selección de músculos y ejercicios no produce parpadeos visibles.
- La página no cambia de altura de forma perceptible al expandir o contraer elementos.
- El catálogo de ejercicios está a la izquierda en escritorio y es usable en móvil.
- La gráfica conserva su contenedor, escala y posición durante las actualizaciones.
- Las reglas de líneas global, músculo y ejercicio son consistentes.
- La vista diaria es la predeterminada.
- Semanas y meses muestran gráfica y resumen coherentes.
- El registro diario permite editar entrenamiento y alimentación sin recorrer un popup excesivamente largo.
- Los controles de RIR funcionan y persisten correctamente.
- Se mantienen los estándares de tokens, accesibilidad, seguridad, HTMX y cobertura del proyecto.

## 9. Orden recomendado para iniciar

Este orden histórico queda sustituido por la cola de recuperación del documento de reconciliación.

El primer plan atómico debe ser `dashboard-baseline-and-contract.md`. No conviene empezar por el rediseño visual sin registrar antes los estados actuales de `/nivel`, `/grafica`, `#unified-chart` y el editor popup. Después deben ejecutarse, en este orden:

1. Contrato y línea base. **Completado.**
2. Retirar acciones visibles secundarias.
3. Layout estable.
4. Catálogo izquierdo.
5. Estado de selección y contrato de series.
6. Transición de gráfica con nodo persistente.
7. Periodos y resumen/tablas.
8. Página `/registro` en convivencia con el popup; decidir su retiro después de validarla.
9. Validación final.
