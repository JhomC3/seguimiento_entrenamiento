# Plan maestro del proyecto

**Estado:** activo y único documento de priorización.
**Última revisión:** 2026-08-27.
**Fuente de verdad funcional:** [`docs/architecture/dashboard-current.md`](../architecture/dashboard-current.md).
**Regla:** solo una línea de trabajo puede estar `EN PROGRESO`; las demás deben estar `PENDIENTE`, `PAUSADA`, `BLOQUEADA`, `COMPLETADA` o `SUPERADA`.

Este documento consolida los planes abiertos. Los documentos de `docs/plans/archive/` son
históricos y no constituyen trabajo pendiente. Ningún agente debe iniciar un plan individual sin
comprobar primero su estado aquí.

## Estado de la cola

| Prioridad | Línea | Estado | Documento rector | Dependencia |
|---|---|---|---|---|
| P0 | Reconciliar working tree y separar contaminación semántica | COMPLETADA | Este documento + `P0-reconciliation-report.md` | Ninguna |
| P1 | Cerrar comparación de puntos y refinamiento visual del dashboard | PENDIENTE | `dashboard-ux-refinement.md` | P0 |
| P2 | Actualizar contratos, pruebas y hacer commit de Fase 2 | PENDIENTE | Este documento | P1 |
| P3 | Retirar deuda Fase 3 del dashboard | PENDIENTE | Este documento | P2 |
| P4 | Modularizar `app.py` en routers | PAUSADA | `app-router-modularization.md` | P2/P3 |
| P5 | Factorizar `src/database.py` | PAUSADA | `codebase-factorization-plan.md` | P4 |
| P6 | Factorizar `static/js/splits.js` | PAUSADA | `codebase-factorization-plan.md` | P5, si sigue siendo necesario |
| P7 | Evaluar separación de `charts.py` y tests E2E | CONDICIONAL | `codebase-factorization-plan.md` | Después de P1–P3 |

El detalle ejecutable de los nuevos requisitos está en [`dashboard-ux-refinement.md`](dashboard-ux-refinement.md).
Sus tareas UX-1 a UX-3 son P1; UX-4 a UX-6 son P2 y dependen de las anteriores. No se ejecutan en paralelo.

P0 está cerrada. P1 permanece pendiente y debe ejecutarse de forma secuencial, sin iniciar P2 ni
trabajo de dominio paralelo. El commit visual `2a1c7de` es un baseline de Fase 2 preparado antes de
P1; el cierre formal de P2 queda pendiente hasta completar la validación funcional, visual y de
contrato posterior a P1.

## P0 — Reconciliación del árbol

Durante la reconciliación el working tree contenía cambios sin commit en código de dashboard y
también en archivos semánticos. Antes de cualquier commit había que clasificar cada cambio:

- visual/dashboard y comparación;
- documentación y tests correspondientes;
- semántica de dominio no autorizada.

Los cambios semánticos no relacionados deben revertirse de forma selectiva o separarse en un plan
propio, nunca mezclarse con el commit visual. No se usa `git reset --hard` ni se revierte trabajo
sin inspeccionar el diff.

**Cierre 2026-08-27:** `git diff` revisado archivo por archivo; la contaminación fue separada en
`.tmp/P0-pure-contamination.patch` (RIR/daily_volume, 6 archivos) y
`.tmp/P0-domain-metrics-cohortes.patch` (métricas/cohortes, 7 archivos, 645 líneas). La
documentación se registró en `137cde3` y el baseline visual en `2a1c7de`. El working tree quedó
limpio, con `.tmp/` ignorado y conservado; la suite base pasó con 682 tests y 92.96% de cobertura.
Ver `P0-reconciliation-report.md`.

## P1 — Cierre funcional del dashboard

Orden de trabajo atómico:

1. Catálogo izquierdo alineado y rail vertical completo; el resumen derecho permanece siempre visible.
2. Gráfica Día con padding solo visual y espacio superior revisado.
3. Controles Día/Semana/Mes con estilo glass real y contraste AA.
4. Comparación de puntos: clic, `Shift + clic`, múltiples puntos y `Escape`.
5. Comparación con periodo corto, VAR, Series, Reps, Peso, RIR y RM ajustado.
6. Orden dinámico compartido entre catálogo y resumen.

Cada punto requiere evidencia Playwright a 1280×800 y 390×800, además de tests. No se acepta una
entrega basada solo en un resumen textual del agente.

## P2 — Contrato y release de Fase 2

- Actualizar [`docs/architecture/dashboard-current.md`](../architecture/dashboard-current.md).
- Mantener `current-ui-contract.md` como contrato histórico complementario, sin contradicciones.
- Actualizar tests y `docs/operations/release-checklist.md`.
- Ejecutar todos los gates frescos.
- El baseline visual de Fase 2 quedó registrado en `2a1c7de` después de la aprobación del alcance.
- Tras completar P1, actualizar contratos, pruebas y checklist; cualquier commit adicional de cierre
  debe contener únicamente el alcance aprobado y contar con validación visual del usuario.

## P3 — Fase 3: limpieza de deuda dashboard

Cada retirada será una tarea independiente con auditoría de consumidores:

1. `#history-section` y su contenido deprecated.
2. `GET /nivel?tipo=ejercicio` cuando no haya consumidores.
3. `trackXhr('/nivel')` cuando la cascada ya no lo necesite.

No se retira una ruta solo porque desaparezca su botón visible. Deben existir pruebas de ausencia,
revisión de enlaces y actualización del contrato.

## P4–P7 — Refactor estructural posterior

Los refactors no deben ejecutarse durante el cierre visual. Se reactivan solo con árbol limpio,
contrato congelado y suite verde:

- P4: `app.py` → routers bajo `src/web/`, sin cambiar URLs, HTML, OOB ni comportamiento.
- P5: `src/database.py` → paquete con fachada, conservando imports públicos y SQL seguro.
- P6: `static/js/splits.js` → módulos solo si el tamaño y la mezcla de responsabilidades siguen
  justificándolo después de P4–P5.
- P7: separar `charts.py` o `tests/e2e/test_dashboard_flow.py` únicamente si el churn y el
  tamaño posteriores lo justifican; no por líneas aisladas.

## Protocolo para agentes

Cada tarea debe:

1. leer este plan y el contrato actual;
2. verificar `git status` y el diff;
3. declarar el alcance y los archivos permitidos;
4. implementar solo una tarea;
5. ejecutar pruebas funcionales y visuales reales;
6. devolver evidencia y archivos modificados;
7. detenerse antes de iniciar la siguiente prioridad.

No se hacen commits ni pushes automáticamente. El commit requiere aprobación explícita después de
la revisión visual.

## Criterio global de cierre

La Fase 2 solo se cierra cuando:

- el dashboard coincide con `dashboard-current.md`;
- el panel izquierdo es el único plegable;
- el panel derecho siempre está visible;
- la comparación funciona sin fetch al seleccionar puntos;
- no quedan cambios semánticos contaminantes;
- tests, lint, tipos, CSS y auditorías pasan;
- el usuario aprueba visualmente;
- el commit contiene únicamente el alcance aprobado.
