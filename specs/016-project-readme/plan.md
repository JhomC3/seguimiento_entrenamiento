# Plan técnico — Spec 016 (README + 3 enmiendas)

## `README.md` raíz (RF-1)

Qué es (2 líneas), arranque (sync + start + tests con punteros), mapa
(tabla área→doc, reutiliza `AGENTS.md` §3), estado (punteros a `specs/`,
cómo ver lo abierto) + fecha de verificación. Nada que requiera sincronía.

## Kit (RF-2, RF-3)

- Protocolo §4: proyecto nuevo exige README con esta estructura.
- Protocolo §10: spec que cambie arranque/stack/mapa lo actualiza en su diff.
- Kit `README.md`: checklist mensual incluye revisar README del proyecto.

## Versión (RF-4)

v0.8.0 + `sdd-lock.json` + commit kit; spec + commit entrenamiento; merge.
