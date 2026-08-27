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

## UX-3 — Comparación sin etiquetas redundantes

**Prioridad:** P1.

- Un punto no muestra `Base`.
- Varios puntos no muestran `Comparado 2`, `Comparado 3`, etc.
- La presentación se ordena siempre de forma descendente por periodo, sin importar el orden de clic.
- `Escape` limpia; no añadir botón visible de limpieza.
- Mantener Series en la comparación.
- Usar `VAR`, `RM`, `RIR`, `S1` y `S14` cuando sean inequívocos.

La prueba debe demostrar que seleccionar 14 y luego 1, o 1 y luego 14, produce siempre 14 antes
que 1.

## UX-4 — Detalle diario contextual en acordeón

**Prioridad:** P2; depende de UX-2 y UX-3.

Con granularidad Día y un punto seleccionado, el resumen derecho muestra únicamente el día elegido:

```text
25 jul
  Pectoral                         3 series
    Press Convergente              2 series
      Serie 1 · 8 reps · 80 kg · RIR 1
      Serie 2 · 6 reps · 85 kg · RIR 0
    Contractor                     1 serie
```

Niveles: músculo → ejercicio → series. Los grupos comienzan cerrados. Cada nivel es nativo o
accesible, con `aria-expanded` y `aria-controls`. No se crea scroll anidado por acordeón.

Con varios músculos seleccionados, todos se conservan y el usuario puede cambiar entre ellos sin
perder la selección. No se mezclan datos de días distintos.

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
