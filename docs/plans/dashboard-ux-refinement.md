# Dashboard — refinamiento UX minimalista y detalle contextual

**Estado:** pendiente de ejecución secuencial.
**Prioridad:** P1–P2 del [`MASTER-PLAN.md`](MASTER-PLAN.md).
**Fuente de verdad visual:** [`docs/architecture/dashboard-current.md`](../architecture/dashboard-current.md).

Este plan recoge los requisitos de producto del 2026-08-27. No autoriza ejecutar todos los bloques
juntos: cada tarea debe implementarse, probarse y validarse antes de pasar a la siguiente.

## Principios

- Minimalismo pragmático: mostrar solo información útil para decidir o actuar.
- Abreviaciones inequívocas cuando ahorren espacio (`VAR`, `RM`, `RIR`, `S1`, `S14`).
- No repetir en tooltip lo que ya comunica el eje o la leyenda.
- No usar color como única fuente de significado.
- El resumen derecho permanece visible y ocupa la altura útil del viewport.
- El catálogo izquierdo es el único panel plegable.
- La selección de músculos y ejercicios se conserva al cambiar granularidad.

## UX-1 — Altura y scroll

**Prioridad:** P1.

El catálogo izquierdo y el resumen derecho deben ocupar toda la altura útil. La página no debe tener
scroll vertical global innecesario cuando el contenido cabe en el viewport. El scroll debe ocurrir
solo en las zonas internas diseñadas. El catálogo plegado conserva su rail de altura completa.

Playwright debe verificar a 1280×800 y 1440×900:

```text
document.documentElement.scrollHeight <= window.innerHeight + 1
catalogTop == chartTop
summaryTop == chartTop
summaryBottom <= window.innerHeight + 1
```

También se verifica catálogo abierto/plegado, resumen vacío/con datos y 390×800.

## UX-2 — Etiquetas y tooltip minimalista

**Prioridad:** P1.

Al seleccionar un ejercicio, la traza compilada se etiqueta con su músculo (`Pectoral`, por
ejemplo), nunca `Compilado`. La leyenda identifica las trazas y el tooltip no repite su nombre.

En Día, el tooltip muestra una sola fecha al inicio, en formato corto (`18 jul 2026` o `18 jul`
si el año no es ambiguo). En Semana muestra una sola fecha de inicio (`18 jul 2026`) y no repite
`S1` o `Semana 1` en cada traza. Retirar `Cobertura`. Mantener Series, VAR, Reps, Peso, RIR y RM aj.

Cada bloque de traza se separa con un divisor sutil. Los valores ausentes usan `—`. Las líneas son
continuas: no usar patrones discontinuos ni variantes tipo `_._`.

Tests unitarios y E2E deben comprobar ausencia de fechas/semana/nombre repetidos, ausencia de
Cobertura, presencia de Series y trazas continuas en global, músculo, ejercicio, día y semana.

## UX-3 — Tabla histórica única (revisada, reemplaza comparativa)

**Prioridad:** P1 — absorbe acordeón Día+ejercicio de la antigua UX-4. Decisión 2026-08-29 (corregida).
**Histórico = todo el ciclo disponible (gráfica respeta ventana 1..8, tabla no).**
**Jerarquía:** Global → [Rendimiento global][Músculo …] → histórico por periodo · Músculo → [Ejercicio …] → histórico por periodo · Ejercicio+Día → fila desplegable → series.

- Eliminar tabla secundaria `#ps-comparison`/`.ps-comparison-table`/`Base`/`Comparado N`. No existe pestaña genérica `Resumen`. Clic/`Shift+clic` no crea tabla.
- `Escape` conserva prioridad existente (diálogo/drawer > highlight+acordeón); sin diálogo/drawer limpia highlight sutil + cierra acordeones. Sin botón visible de limpieza.
- Tabla única `#period-summary-wrap` con estados `ready/empty/error`, orden desc, scroll único en `.ps-panels` (detalle sin scroll propio). Pestañas siempre horizontales, scroll horizontal si no caben, sin romper layout.
- **Global sin selección:** `[Rendimiento global][Pectoral][Espalda][Bíceps]…` (todos los músculos). `Rendimiento global` activa por defecto, histórico global por periodo; cada músculo histórico por periodo.
- **Músculo seleccionado:** `[Press inclinado][Press convergente][Contractor]…` (todos sus ejercicios). Sin `Resumen`. Cada ejercicio histórico por periodo, primera activa, cambio local sin fetch.
- **Ejercicio:** histórico por periodo (`S17 · 24-08-26` / `27-08-26 · S17` / `ago-26`), orden desc, **todos los periodos del ciclo** (no solo ventana). No reemplazar histórico por lista de entidades.
- Formato minimalista: Día `DD-MM-YY · S<n>` (ej `27-08-26 · S17`), Semana `S<n> · DD-MM-YY` con `week_start_date(n,ciclo_start)` reutilizado (no ISO week), Mes `mmm-YY` minúsculas (`ago-26`). No `Semana 17`/`Base`/`2026-08-27` visible (ISO solo `data-*`/aria). `aria-label` largo único (`27 de agosto de 2026 · Semana 17`) sin duplicar lectura visible (`aria-hidden`).
- ID canónico gráfica→fila: `gran|periodo_norm|entity_norm` donde `periodo_norm` es `YYYY-MM-DD` (Día, `pt.x` normalizado), `str(semana)` (Semana), `YYYY-MM` (Mes) — **nunca `customdata[0]` (tooltip). No modificar las 9 posiciones de `customdata`. Entidad `strip().casefold()`. Python y JS idénticos, `week_start_date` reutilizado.
- Detalle Día+ejercicio: una query batch `LOWER(ejercicio) IN (...)` sin filtro de fechas y sin `kg/reps IS NOT NULL` (mostrar `—` si falta, excluir solo sin fecha/ejercicio). SSR de `SetDetail` para todo el ciclo, acordeón solo `exercise+Día`, cerrado por defecto, `aria-expanded`/`aria-controls`, sin scroll anidado.

## UX-4 — Detalle diario contextual jerárquico (pendiente)

**Prioridad:** P2; depende de UX-3 revisada.

UX-3 incorpora únicamente acordeón por ejercicio en Día. Queda pendiente para UX-4 el detalle
jerárquico completo músculo→ejercicio→series en multi-selección y Semana/Mes.
No crear scroll anidado. Conservar selección al cambiar contexto.

## UX-5 — Resumen temporal inequívoco

**Prioridad:** P2; depende de UX-2.

Para la selección y granularidad actuales:

- `actual`: último periodo con datos válidos;
- `inicio`: primer periodo comparable con datos válidos;
- `VAR`: variación de actual respecto de inicio.

Así, Día compara días, Semana compara semanas y Mes compara meses. La definición debe quedar en
`summary_service.py` y en tests; la UI no debe dejar ambiguo si muestra un último periodo o una
ventana completa.

Cambiar granularidad conserva músculos y ejercicios, recalcula el agrupamiento y elimina puntos
comparados que ya no pertenecen a la nueva figura.

## UX-6 — Documentación y cierre

Actualizar el contrato del dashboard, el checklist de release y este plan con cada decisión cerrada.
No cerrar el plan mientras DOM, navegador, tests y documentación discrepen.
