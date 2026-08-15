"""Backup retention helpers shared by app backups and migration pre-upgrade backups."""

import sqlite3
from pathlib import Path


def copy_db(source_path: str, dest_path: str) -> None:
    """Copia consistente de una base SQLite usando la API de backup online del
    motor (incluye frames WAL sin checkpointear: un shutil.copy2 del .db podría
    producir un backup inconsistente con WAL activo)."""
    source = sqlite3.connect(source_path)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


def prune_backups(backups_dir: str, keep: int) -> None:
    # lifestyle-*.db (nuevos) + gym-*.db (legado pre-renombrado, se limpia solo).
    files = sorted(
        p
        for p in Path(backups_dir).iterdir()
        if p.name.startswith(("lifestyle-", "gym-")) and p.name.endswith(".db")
    )
    if len(files) <= keep:
        return
    for stale in files[:-keep]:
        stale.unlink(missing_ok=True)
