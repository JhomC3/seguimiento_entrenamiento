# Plan técnico — Spec 001 (kit + criterio, solo docs)

Sin cambios de conducta del dashboard. Solo añade documentación y reglas.

## Estructura (nuevo bajo `docs/sdd/`, RF-5)

- `docs/sdd/SDD_BOOTSTRAP.md` → protocolo paso a paso (nuevo vs iniciado) + deber de criterio + niveles + disenso (RF-1..RF-4)
- `docs/sdd/prompts.md` → 8 prompts de fase adaptados (RF-1)
- `docs/sdd/templates/constitution.md` → plantilla 7 principios (RF-5, RF-6)
- `docs/sdd/templates/AGENTS.md` → plantilla de contexto con bloque SDD (RF-5)
- `docs/sdd/templates/spec.md` → plantilla EARS con sección de disenso (RF-4, RF-5)
- `docs/sdd/templates/plan.md` + `tasks.md` → plantillas (RF-5)
- `docs/sdd/skills/spec-generator/SKILL.md` → guía de entrevista 1×1 máx. 6 (RF-1)

## Modificaciones (existente, aditivas, RF-6)

- `docs/constitution.md`: añadir principio 7 (criterio propio). La spec 000 no enumera principios: sin conflicto.
- `AGENTS.md` §9: extender con deber, parada, niveles (bloqueante/advertencia/sugerencia), reparto dueño-problema/agente-técnica y formato de disenso. Solo añade líneas.

## Decisiones

- Vendorizado por copia dentro del repo (no lectura externa en runtime): se descarta dependencia externa por la máxima sandbox §0.
- 7 principios en vez de 6: se descarta forzar el molde de 6 porque el deber de criterio no cabe en los existentes.
- El agente obedece tras advertencia registrada: se descarta el bloqueo permanente porque la última palabra es del dueño.

## Estrategia de tests

Sin código: verificación = gates RF-7 + revisión del diff (solo aditivo) + lectura en frío del kit.
