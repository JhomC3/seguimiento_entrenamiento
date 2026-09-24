# Plan técnico — Spec 005 (script + hook + CI + reglas)

## `scripts/check_file_size.py` (RF-1..RF-3, RF-5)

- `argparse`: `--warn` (500), `--max` (800), `--base` (default `HEAD`), `--allowlist` (default embebido = baseline spec), scopes fijos `app.py src scripts tests` menos `tests/e2e`.
- Archivos = intersección del diff (`git diff --name-only <base>`) con scopes + todo archivo >800 en el árbol (caza gigantes nuevos fuera del diff).
- Conteo: líneas no blancas cuyo `lstrip()` no empieza por `#`.
- Salida 1 + lista ante bloqueo; avisos a stderr, salida 0 si solo avisos.

## `.githooks/pre-commit` (RF-4)

- Bash: `uv run python scripts/check_file_size.py --base HEAD` (staged ≈ HEAD en hook; documentado).
- Setup: `git config core.hooksPath .githooks` en `docs/operations/local-development.md`.

## Cableado

- `tests/test_check_file_size.py`: sano / aviso / bloqueo / allowlist ±holgura / fuera de allowlist / exclusión e2e.
- CI `quality` tras Lint; `AGENTS.md` §8 + §6; constitución principio 2 enmendado ("...módulos atómicos ≤500 líneas de código; el gate lo exige").

## Decisiones

- Métrica código (no bruto): no castigar documentación.
- Holgura +5% (no freeze ni vía libre).
- e2e fuera del gate con justificación en spec.
