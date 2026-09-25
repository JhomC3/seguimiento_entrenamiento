# Plan técnico — Spec 006 (fachada + 4 módulos)

## Estrategia

Fachada de re-exportación: `src/database.py` pasa a importar y re-exportar
(`from src.db_training import ...`, `__all__`) para que los 10 consumidores
(`app.py` vía servicios, 9 servicios, tests) no cambien ni una línea.
Sin riesgo de imports circulares: los submódulos solo dependen de `config`,
`src.db_connection`, `src.migrations.runner`, `src.models` (igual que hoy).

## Cortes (verificados contra inventario de funciones, RF-3)

| Módulo | Contenido | Code lines est. |
|---|---|---|
| `src/db_training.py` | init/backup/load, catálogo, sets, plantillas entreno, snapshot/restore, `get_last_exercise_series` | ~370 |
| `src/db_nutrition.py` | `_DIARIO_*`, `_PARAMETROS_COLUMNS`, alimentos, diario, parámetros, plantillas alimentación | ~240 |
| `src/db_splits.py` | splits, catálogos dashboard, snapshot/restore | ~260 |
| `src/db_wellness.py` | `_BREATHING_COLUMNS` + breathing_sessions | ~60 |
| `src/database.py` | solo re-exports + `__all__` | ~60 |

`_resync_sequence` va con training (solo lo usa `restore_entrenos`).
Cada constante viaja con su dominio.

## Orden de tareas

T1 spec+plan+tasks y línea base (hecho). T2 caracterización:
`tests/test_database.py` en verde antes de tocar nada. T3–T6 un módulo
por tarea (extraer + fachada parcial + test). T7 gates + allowlist + commit.
