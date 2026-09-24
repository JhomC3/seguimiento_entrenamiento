---
description: Rescan the stack, report missing skills, install kit ones after approval
---

Re-escanea el stack del proyecto y sincroniza sus skills. $ARGUMENTS puede
traer una pista ("tras añadir tailwind", "revisa").

1. Detecta manifiestos: `pyproject.toml`, `package.json`, `requirements*.txt`,
   `build.gradle*`, `*.gradle.kts`, `go.mod`, `Cargo.toml`. Lista librerías/frameworks.
2. Compara contra skills instaladas (`.opencode/skills/`, `.agents/skills/`,
   `.claude/skills/`): tabla librería → skill del kit / de terceros / ninguna.
3. Las del kit faltantes: pídeme "sí" explícito y luego instálalas con
   `sdd-kit/install.sh --sync` (o copia equivalente). Prohibido instalar sin mi sí.
4. Para librerías de terceros sin skill: sugiere `npx autoskills --dry-run`
   pero NO lo ejecutes por mí; la decisión de terceros es mía.
5. Reporta el resultado y actualiza `sdd-lock.json` si cambió algo.
Deber de criterio: si una skill sugerida contradice la constitución del repo
(p. ej. stack prohibido), adviértelo antes de instalar.
