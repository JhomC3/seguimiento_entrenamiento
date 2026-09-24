# Plan técnico — Spec 004 (kit + instalador + dogfooding)

Todo el contenido nuevo vive en `../sdd-kit/` (repo propio, commits ahí).
En `entrenamiento` solo: spec 004 + resultado del dogfooding + gates.

## Subagentes (`sdd-kit/agents/*.md`, RF-1)

- `explorer.md`: `mode: subagent`, `permission: {edit: deny}`, auto-invocable para mapear código/arquitectura.
- `reviewer.md`: `edit: deny`, `bash: {git status/diff/log: allow, resto: ask}`; pragmático, sin gustos de estilo.
- `security.md`: `edit: deny`; referencia la checklist de `skills/security-audit/` (no la duplica).

## Skills (`sdd-kit/skills/*/SKILL.md`, RF-2, RF-5)

- `plan-evaluator`, `architecture-reviewer`, `security-audit` (checklist OWASP adaptada: secretos, auth/token, validación, SSRF, CSRF), `debug-detective`, `researcher` + `spec-generator` (añadir frontmatter).
- Cada una: qué hace, cuándo usarla, checklist, formato de veredicto.

## Instalador (`sdd-kit/install.sh`, RF-3)

Bash defensivo (`set -euo pipefail`): `--dry-run`, `--con-skills`, `--con-agentes`, `--yes`; detecta destino; copia `commands/` siempre, skills/agentes según flags; escribe `sdd-lock.json`; actualiza `sdd-lock.json` del kit con los archivos nuevos (commit en repo del kit).

## Dogfooding (`entrenamiento`, RF-4)

Ejecutar el instalador contra el worktree: `.opencode/{commands,skills,agents}/` + `sdd-lock.json`; verificar gates RF-6 y que `.opencode/` no interfiere (ruff/pytest/mypy ignoran `.md`; confirmar por evidencia).

## Decisiones

- Formatos según docs oficiales OpenCode 2026-09-24 (spec 003 T1); sin `model` pineado.
- Checklist de seguridad en un solo sitio (skill); subagente la referencia.
