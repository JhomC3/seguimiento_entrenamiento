# Plan técnico — Spec 002 (solo docs)

## Cambios (un archivo + esta spec)

- Reescribir `AGENTS.md` (~291 → ~150-170 líneas) según el mapa de la spec.
- `specs/002-agents-slim/spec|plan|tasks.md` (esta spec, sin código).

## Decisiones

- Criterio de poda (en orden): comando exacto → trampa no inferible → puntero; el resto se elimina porque ya vive en `docs/`/`src/`.
- Specs cerradas intactas: se descarta reescribir historia; el mapa de equivalencia da trazabilidad.
- `docs/constitution.md` intacta: ningún principio cambia, solo se reubica su resumen.

## Estrategia de tests

Sin código: gates RF-6 + diff revisado + verificación de que cada puntero existe (archivos referenciados presentes).
