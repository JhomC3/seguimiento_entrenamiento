# Spec 006 — Partir `src/database.py` sin cambio de conducta

Constitución: `docs/constitution.md` (principios 1, 2, 6).
Plan de etapa: `/Users/jhomc/.opencode/plan/refactors-006-009.md`.

## Contexto y objetivo

`src/database.py` tiene 976 líneas de código (tope: 500 aviso / 800 bloqueo).
Partirlo por dominios en módulos ≤500, manteniendo `src/database.py` como
fachada delgada de re-exportación para no tocar a los 10 consumidores.
Cero cambios de conducta.

Línea base remedida (2026-09-25, `check_file_size.py`): database 976,
charts 1154, summary 916, app 2748. El gate pasa (avisos, ningún bloqueo).

## Usuarios

Cualquier agente que toque persistencia; ningún cambio visible para el dueño.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO cualquier consumidor importe desde `src.database`, EL SISTEMA seguirá resolviendo los 59 nombres públicos actuales (fachada re-exporta; cero cambios en `app.py`, `src/*_service.py`). Excepción registrada: 2 tests de `tests/test_database.py` pinchan `read_connection` en el namespace del módulo (detalle de layout, no conducta); se retargetean al submódulo (`src.db_training` / `src.db_nutrition`) sin tocar lo afirmado (≤2 queries).
- RF-2: EL SISTEMA ubicará cada función en su módulo de dominio:
  - `src/db_training.py`: init/backup/load, catálogo, sets, plantillas de entreno, snapshots (~360 líneas).
  - `src/db_nutrition.py`: alimentos, diario, parámetros, plantillas de alimentación (~230 líneas).
  - `src/db_splits.py`: splits y catálogos (~250 líneas).
  - `src/db_wellness.py`: breathing_sessions (~60 líneas).
- RF-3: SI un módulo nuevo supera 500 líneas de código, ENTONCES el refactor se rechaza (se subdivide más).
- RF-4: MIENTRAS se ejecuta el refactor, la suite de caracterización (`tests/test_database.py`) permanecerá en verde en todo momento; al cierre, los gates §8 completos pasan.
- RF-5: Al cerrar, la allowlist del gate pierde la entrada `src/database.py` (queda bajo 800; fachada ~60 líneas).

## Fuera de alcance

Ningún cambio de conducta, SQL, esquema o API. Otros gigantes (007–009).

## Criterios de finalización

- `tests/test_database.py` verde antes (caracterización) y después.
- Gates §8 en orden + `check_file_size.py` sin `src/database.py` en allowlist.
- Recorrido RF×test registrado como veredicto.

## Dudas abiertas

- Ninguna.

## Veredicto (recorrido RF×test, 2026-09-25)

- RF-1: OK — 59/59 nombres importables desde `src.database`; 0 cambios en `app.py`/`src/`. Excepción aplicada: 2 tests retargetean `read_connection` al submódulo.
- RF-2: OK — training 407, nutrition 265, splits 251, wellness 64, common 7 (+ fachada 129).
- RF-3: OK — ningún módulo nuevo >500 (máx 407).
- RF-4: OK — caracterización 60/60 antes y después; unitaria 893 passed (cob. 90.92%); ruff/mypy/module-coverage/file-size verdes. e2e: 14 fallos en `test_dashboard_flow.py` idénticos en `dev` limpio (preexistentes, chart sin datos en fixture).
- RF-5: OK — `src/database.py` fuera de la allowlist; gate `tamaño OK`.
