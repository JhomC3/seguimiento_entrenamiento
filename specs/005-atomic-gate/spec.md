# Spec 005 — Gate de atomicidad + reglas

Constitución: `docs/constitution.md` (principio 2 enmendado por esta spec).

## Contexto y objetivo

4 archivos >1000 líneas existen pese a la regla escrita. La regla sin
enforcement no se cumple: hace falta gate mecánico (hook local + CI) y
allowlist temporal con holgura.

## Usuarios

Todo agente que commitee en el repo + CI.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO un archivo en el diff (base: merge-base con `dev`; local `HEAD`, flag `--base`) supere 800 líneas de código, EL SISTEMA fallará (salida 1).
- RF-2: MIENTRAS un archivo supere 500 líneas de código, EL SISTEMA avisará a stderr sin fallar.
- RF-3: EL SISTEMA aplicará allowlist con holgura +5% sobre el pineado (crecer más falla).
- RF-4: EL SISTEMA correrá también como hook `.githooks/pre-commit` sobre staged (setup documentado; `--no-verify` posible → el CI es el gate real).
- RF-5: EL SISTEMA medirá líneas de código (sin blancos ni comentarios).
- RF-6: Gates existentes en verde + `tests/test_check_file_size.py` en verde.

## Requisitos no funcionales

- Topes 500/800 ratificados por el dueño 2026-09-24 (propuestos 2× sin objeción).
- Ámbito: `app.py`, `src/`, `scripts/`, `tests/` excepto `tests/e2e/` (flujos e2e inherentemente largos; partirlos aporta poco y churnea mucho).
- Cero dependencias nuevas (stdlib + `argparse`).

## Línea base medida T1 (código, 2026-09-24)

Allowlist inicial: `app.py` 2748, `tests/test_app.py` 2656,
`tests/test_database.py` 1294, `tests/test_charts.py` 1235,
`tests/test_training_api.py` 1185, `src/charts.py` 1154,
`src/database.py` 976, `src/summary_service.py` 916.
Aviso: `tests/test_security.py` 628, `tests/test_parser.py` 513, `scripts/audit_ui.py` 544.

## Casos límite

- Gigante allowlistado que crece ≤5% → pasa; >5% → falla.
- Archivo nuevo >800 → falla aunque el repo tenga gigantes.
- `tests/e2e/` excluido del gate (documentado arriba).

## Fuera de alcance

Refactors (specs 006–009 src; los gigantes de `tests/` irán en specs 010+).

## Criterios de finalización

- Fixture de 801 líneas falla en CI; de 799 pasa con aviso; gigantes pineados no bloquean.
- Hook activo y documentado; CI con el paso; constitución enmendada (principio 2); `AGENTS.md` §6+§8.

## Dudas abiertas

- Ninguna.
