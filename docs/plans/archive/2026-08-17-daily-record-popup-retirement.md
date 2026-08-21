# Plan 13: Registro diario — Decisión y retiro seguro del popup

**Estado:** Pendiente de decisión de producto e implementación  
**Depende de:** `2026-08-17-daily-record-page.md`, `2026-08-17-daily-record-editor-controls.md` y `2026-08-17-daily-record-secondary-forms.md`.

## Objetivo

Decidir, con la página `/registro` ya validada, si el popup de registro se retira definitivamente o continúa como acceso rápido. No debe eliminarse antes de comprobar que el flujo diario nuevo cubre entrenamiento, alimentación, cardio, plantillas, foco, teclado y navegación por fecha.

## Alternativas

1. Retiro definitivo: los clics de gráfica navegan a `/registro?fecha=…` y se eliminan `#editor-popup`, `editor-popup.js`, `/editor/popup` y sus pruebas específicas.
2. Acceso rápido: se conserva el popup reducido, con un enlace visible a `/registro`, y se limita a la consulta o edición mínima del día.

## Criterios para decidir

- El registro diario resulta más rápido y claro en uso real durante varios días.
- No se pierde ninguna mutación ni flujo de recuperación/undo.
- La navegación desde la gráfica abre una fecha inequívoca para día, semana y mes.
- Las pruebas E2E de registro y accesibilidad cubren el flujo elegido.

## Fuera de alcance

No rediseña controles ni datos. Solo retira o acota el popup una vez aprobada la alternativa.

## Próximo paso

Si se aprueba el retiro, ejecutar `2026-08-17-dashboard-e2e-validation.md`. Si se conserva el popup, actualizar ese plan para validar ambos accesos.

## Criterios de aceptación

- Existe una decisión documentada de producto.
- Si se retira, no quedan rutas, módulos, marcadores de contrato ni pruebas muertas del popup.
- Si se conserva, su alcance y relación con `/registro` están documentados y cubiertos por pruebas.
