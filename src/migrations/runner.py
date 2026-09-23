"""Migration runner: applies pending versioned migrations transactionally."""

import os
from datetime import datetime

from src.db_connection import connect_db
from src.migrations import (
    v001_initial_schema,
    v002_add_origins_and_categories,
    v003_add_template_order,
    v005_recompute_semana,
    v006_iso_dates,
    v007_nutrition,
    v008_nutrition_daily_params,
    v009_nutrition_meal_templates,
    v010_health_connect,
    v011_descanso_seg,
    v012_cardio_annotations,
    v013_persistent_undo,
    v014_training_fecha_index,
    v015_splits,
    v016_split_activo,
    v017_hiit_velocidad_dificultad,
    v018_nutrition_micro_targets,
    v019_extra_micros,
    v020_dri_ceros,
    v021_breathing,
)

MIGRATIONS = [
    v001_initial_schema,
    v002_add_origins_and_categories,
    v003_add_template_order,
    v005_recompute_semana,
    v006_iso_dates,
    v007_nutrition,
    v008_nutrition_daily_params,
    v009_nutrition_meal_templates,
    v010_health_connect,
    v011_descanso_seg,
    v012_cardio_annotations,
    v013_persistent_undo,
    v014_training_fecha_index,
    v015_splits,
    v016_split_activo,
    v017_hiit_velocidad_dificultad,
    v018_nutrition_micro_targets,
    v019_extra_micros,
    v020_dri_ceros,
    v021_breathing,
]

_CURRENT_VERSION = max(m.VERSION for m in MIGRATIONS)


_DOMAIN_TABLES = {
    "ejercicios",
    "training_sets",
    "plantillas",
    "plantilla_sets",
    "alimentos",
    "diario_alimentacion",
    "parametros_diarios",
    "plantillas_alimentacion",
    "plantilla_alimentos",
    "health_records",
    "cardio_annotations",
    "training_splits",
    "training_split_items",
    "breathing_sessions",
}


def _existing_tables(conn) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def _backup_before_upgrade(db_path: str, conn) -> None:
    from src.backup_utils import copy_db, prune_backups

    if not (_existing_tables(conn) & _DOMAIN_TABLES):
        return
    backups_dir = os.path.join(os.path.dirname(db_path) or ".", "backups")
    os.makedirs(backups_dir, exist_ok=True)
    dest = os.path.join(backups_dir, f"lifestyle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
    copy_db(db_path, dest)
    prune_backups(backups_dir, 30)


def _applied_versions(conn) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def pending_migrations(db_path: str) -> list:
    """List of migration modules not yet applied. Opens its own connection."""
    conn = connect_db(db_path)
    try:
        return _pending_for(conn)
    finally:
        conn.close()


def _pending_for(conn) -> list:
    applied = _applied_versions(conn)
    return [m for m in MIGRATIONS if m.VERSION not in applied]


def run_migrations(db_path: str) -> list[str]:
    """Apply all pending migrations atomically. Returns applied migration names."""
    conn = connect_db(db_path)
    try:
        with conn:
            pending = _pending_for(conn)
            if pending:
                _backup_before_upgrade(db_path, conn)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for m in pending:
                m.migrate(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (m.VERSION, now),
                )
        return [m.NAME for m in pending]
    finally:
        conn.close()


def current_version(db_path: str) -> int:
    conn = connect_db(db_path)
    try:
        applied = _applied_versions(conn)
        return max(applied) if applied else 0
    finally:
        conn.close()
