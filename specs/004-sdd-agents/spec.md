# Spec 004 — Subagentes + skills de rol + instalador

Constitución: `docs/constitution.md` (principio 1: todo cambio empieza en la spec).

## Contexto y objetivo

El kit (`../sdd-kit/`) ya tiene protocolo, plantillas y comandos. Faltan las
otras dos capas OpenCode (subagentes con permisos propios, skills de disparo
automático) y el instalador que vendor SESSIONIZE el pack en cada proyecto.

## Usuarios

El dueño y cualquier agente bajo `Proyectos/`.

## Historias de usuario

- H1: Como dueño quiero invocar `@reviewer`/`@security`/`@explorer` para revisiones aisladas sin contaminar mi sesión.
- H2: Como dueño quiero que al pedir "evalúa este plan" se active sola la checklist experta.
- H3: Como dueño quiero instalar el pack en un proyecto con un comando y ver antes qué haría (`--dry-run`).

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá 3 subagentes (`explorer`, `reviewer`, `security`) en formato OpenCode válido (frontmatter `description` requerido, `mode: subagent`, SIN `model` pineado, permisos por `permission:`) bajo `sdd-kit/agents/`.
- RF-2: EL SISTEMA proveerá 5 skills (`plan-evaluator`, `architecture-reviewer`, `security-audit`, `debug-detective`, `researcher`) en formato válido (`SKILL.md` con `name`+`description`, nombre `^[a-z0-9]+(-[a-z0-9]+)*$`, description ≤1024) bajo `sdd-kit/skills/`; la checklist de seguridad vive SOLO en la skill y el subagente la referencia (fuente única, decidido en plan).
- RF-3: EL SISTEMA proveerá `sdd-kit/install.sh` (bash defensivo) con `--dry-run`, detección (vacío / con SDD / con autoskills), copia selectiva (`--con-skills`, `--con-agentes`), escritura de `sdd-lock.json` en destino, y prohibiciones: nunca toca `skills-lock.json`, nunca red, nunca global.
- RF-4: EL SISTEMA instalará el pack en `entrenamiento` con el propio instalador (dogfooding: `.opencode/commands/` + `.opencode/skills/` + `.opencode/agents/` + `sdd-lock.json`) sin romper gates.
- RF-5: EL SISTEMA añadirá al kit la skill `spec-generator` con frontmatter válido (hoy no lo tiene).
- RF-6: Gates en verde (`pytest --ignore=tests/e2e`, `ruff format --check`, `ruff check`, `mypy`).

## Requisitos no funcionales

- Instalación por proyecto (nada global salvo la norma, decidido en plan).
- Veredictos de skills/roles: APROBADO / CON RESERVAS / BLOQUEADO + motivo.

## Casos límite

- Proyecto con autoskills → el instalador detecta `.agents/` y `skills-lock.json` y no los pisa.
- `sdd-lock.json` existente con versión distinta → el instalador lo declara y pide confirmación (no hay `-y` silencioso por defecto salvo flag explícito).

## Decisión registrada (2026-09-24, dogfooding)

`.gitignore` ignoraba `.opencode/skills/` (herencia autoskills: tooling de terceros).
Las skills SDD son config propia versionada, no tooling local: se añade
excepción estrecha solo para las 6 propias; terceros siguen ignorados.
`sdd-lock.json` nunca estuvo ignorado (solo `skills-lock.json`).

## Fuera de alcance

Comandos globales; skills externas de terceros; cambios de conducta en `entrenamiento`.

## Criterios de finalización

- 3 agentes + 6 skills con frontmatter validado por script + instalador probado (`--dry-run` + instalación real en scratch + dogfooding) + gates verdes + merge.

## Dudas abiertas

- Ninguna.
