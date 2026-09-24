# Spec 003 — Comandos SDD + mudanza del kit a Proyectos/

Constitución: `docs/constitution.md` (principio 1: todo cambio empieza en la spec).

## Contexto y objetivo

El kit SDD vive dentro de `entrenamiento/docs/sdd/` y sus fases solo existen
como prompts pegados (`prompts.md`). Para que cualquier proyecto lo use hacen
falta: fuente única en `Proyectos/sdd-kit/`, 8 comandos OpenCode invocables y
la norma de la casa en `Proyectos/AGENTS.md`.

## Usuarios

El dueño (no técnico) y cualquier agente en cualquier proyecto bajo `Proyectos/`.

## Historias de usuario

- H1: Como dueño quiero invocar cada fase SDD con un comando (`/specify`, `/plan`...) en vez de pegar prompts.
- H2: Como agente en carpeta vacía quiero una norma que me ordene entrevistar antes de programar.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: EL SISTEMA proveerá 8 comandos OpenCode (`constitution, specify, clarify, plan, tasks, analyze, implement, cambio`) con frontmatter válido (`description`; sin `model` pineado para heredar el de la sesión) bajo `sdd-kit/commands/`.
- RF-2: EL SISTEMA mudará el kit intacto en contenido a `/Users/jhomc/Proyectos/sdd-kit/` con `VERSION 0.2.0` + `sdd-lock.json` (versión + SHA por archivo, manifiesto único).
- RF-3: EL SISTEMA convertirá `prompts.md` en índice hacia `commands/` (una sola fuente).
- RF-4: EL SISTEMA creará `/Users/jhomc/Proyectos/AGENTS.md` (~15 líneas: orden de arranque, deferencia al repo, puntero al kit, permiso de lectura `../sdd-kit/`).
- RF-5: EL SISTEMA dejará en `entrenamiento` solo el stub `docs/sdd/README.md` → `../../sdd-kit` y actualizará el puntero de `AGENTS.md` §9; specs 000–002 intactas.
- RF-6: EL SISTEMA añadirá `/analyze` (chequeo cruzado spec↔plan↔tasks, de Spec Kit) con checklist de consistencia.
- RF-7: Gates en verde (`pytest --ignore=tests/e2e`, `ruff format --check`, `ruff check`, `mypy`).

## Requisitos no funcionales

- Cero red en runtime; cero toques a `skills-lock.json` (autoskills); una sola excepción sandbox documentada (creación en `Proyectos/`).
- Rutas OpenCode oficiales (docs 2026-09-24): `.opencode/commands/`, `.opencode/agents/`, `.opencode/skills/`; frontmatter `description` requerido en agentes, `name`+`description` en skills.

## Casos límite

- Comando invocado en proyecto sin constitución → el comando lo detecta y redirige a `/constitution` primero.
- `Proyectos/AGENTS.md` vs `AGENTS.md` del repo en conflicto → manda el del repo (deferencia explícita).

## Fuera de alcance

Subagentes, skills de rol e instalador (spec 004). Nada global salvo la norma (decidido en plan).

## Criterios de finalización

- Kit en `Proyectos/sdd-kit/` + norma creada + `entrenamiento` sin duplicado + gates verdes + lectura en frío superada (registrada abajo).
- Lectura en frío: superada 2026-09-24 en el worktree (kit sin referencias a ningún proyecto/stack; norma + bootstrap bastan para arrancar en carpeta vacía).

## Dudas abiertas

- Ninguna.

## T1 — Hallazgos de verificación de rutas (2026-09-24, evidencia local + docs oficiales)

- Transcript impreciso: rutas reales en plural (`.opencode/agents/`, `.opencode/commands/`); midudev usa `.opencode/command` (singular, convención propia, NO seguir).
- Agentes: frontmatter `description` requerido; `mode: subagent`; NO fijar `model` (hereda el de la sesión); `tools:` deprecated → usar `permission:`.
- Skills: `.opencode/skills/<nombre>/SKILL.md`, frontmatter `name`+`description` obligatorios, nombre `^[a-z0-9]+(-[a-z0-9]+)*$`, description ≤1024.
- En esta máquina NO existen `~/.config/opencode/commands/`, `agents/` ni dirs de skills: nada global instalado; correcto según no-objetivo.
