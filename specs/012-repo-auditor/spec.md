# Spec 012 — Skill repo-auditor

Constitución: `docs/constitution.md` (principio 1).

## Contexto y objetivo

El kit sabe instalar SDD pero no auditar repos existentes. Crear la skill
`repo-auditor` y validarla contra `entrenamiento`.

## Usuarios

El dueño y cualquier agente que instale SDD en un repo existente.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá `sdd-kit/skills/repo-auditor/SKILL.md` con frontmatter válido (nombre `^[a-z0-9]+(-[a-z0-9]+)*$`, description ≤1024, disparo: "audita este repo", "¿qué sobra aquí?", "instalar SDD aquí").
- RF-2: EL SISTEMA incluirá checklist (solo detecta y califica): AGENTS >150 líneas o inventarios; dirs duplicados; planes narrativos (marcar CONGELADO en sitio, nunca crear `planes/`/`archivo/`); decisiones fuera de ADRs; ADRs triviales o muertos (a su spec o `REVOCADO` en sitio); plantillas rivales; backlogs paralelos; sin constitución/specs.
- RF-3: EL SISTEMA definirá veredicto: tabla hallazgo/gravedad/acción + plan de migración por fases.
- RF-4: EL SISTEMA validará corriéndola contra `entrenamiento`: éxito = veredicto accionable + deuda registrada (se esperan hallazgos, p. ej. `docs/plans/` heredado).
- RF-5: Kit v0.6.0 con commit.

## Fuera de alcance

Ejecutar las migraciones que la auditoría proponga (cada una su spec).

## Criterios de finalización

- Skill + veredicto registrado + commit v0.6.0.

## Dudas abiertas

- Ninguna.
