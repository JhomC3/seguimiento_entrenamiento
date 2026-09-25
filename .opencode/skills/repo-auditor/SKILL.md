---
name: repo-auditor
description: Audit a repo for duplication, bloat and SDD readiness with a verdict
---

## Qué hago
Audito repos existentes para estandarizarlos. Solo detecto y califico
(como `/clarify`): nunca migro nada yo mismo; cada migración es su spec.

## Cuándo usarme
Úsame cuando pidan: audita este repo, ¿qué sobra aquí?, instalar SDD aquí,
¿está listo para SDD?

## Checklist
- `AGENTS.md` >150 líneas o con inventarios archivo por archivo → poda (criterio comando/trampa/puntero). Grave si >250.
- Dirs duplicados por tema (dos `investigacion/`, dos `planes/`) → fusionar.
- Planes narrativos sin estado ni enlace a código → marcar `CONGELADO` en cabecera *en su sitio*. Prohibido crear `planes/` o `archivo/` nuevos: todo plan vive en una spec o en `.opencode/plan/`.
- Decisiones fuera de ADRs (reportes, chats, backlogs) → migrar o enlazar.
- ADRs triviales (caben en dos líneas → a su spec) o muertos sin marca → `REVOCADO: ver ADR-00NN` en sitio.
- Plantillas rivales (local vs kit) → sustituir por kit.
- Backlogs paralelos (`IDEAS_*`, TODOs huérfanos) → pipeline idea→spec o archivo.
- Sin constitución/specs → instalación SDD.
- `CLAUDE.md` que no sea symlink a `AGENTS.md` → unificar (symlink manda).

## Veredicto
Tabla hallazgo/gravedad (bloqueante/advertencia/nota)/acción + plan de
migración por fases (una spec por fase). Lo sano se declara explícitamente
para no "arreglarlo".
