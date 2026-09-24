# Plan técnico — Spec 010 (kit + hook, sin código de negocio)

Todo el contenido nuevo vive en `../sdd-kit/` (commits ahí). En
`entrenamiento`: spec 010 + hook-hint + dogfooding.

## Comando `sdd-kit/commands/skills.md` (RF-1)

Re-escanea manifiestos conocidos, compara contra `.opencode/skills/` +
`skills/` de terceros si existen, reporta tabla (librería → skill kit /
terceros / ninguna), instala kit faltantes tras "sí" explícito, sugiere
`npx autoskills --dry-run` para terceros sin ejecutarlo.

## `install.sh --sync` (RF-2)

Compara archivos del kit contra destino (por SHA de `sdd-lock.json` del kit):
copia solo faltantes (respeta flags `--con-skills/--con-agentes` ya instalados
o los pide), reescribe `sdd-lock.json` del destino. `--dry-run` lo muestra.

## Hook-hint (RF-3)

En `.githooks/pre-commit` de `entrenamiento`: si `git diff --cached --name-only`
incluye manifiesto (`pyproject.toml`, `package*.json`, `requirements*.txt`,
`android/**/build.gradle*`, `*.gradle.kts`), imprime aviso a stderr, salida 0.

## Regla (RF-4)

Una línea en `SDD_BOOTSTRAP.md` §7 (tareas) + ejemplo en `templates/tasks.md`:
toda spec que añada dependencia trae tarea de revisión de skills.

## Decisiones

- Sin instalación silenciosa (proponer → confirmar → instalar).
- Terceros = `autoskills` del dueño; el kit nunca descarga externo.
