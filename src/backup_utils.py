"""Backup retention helpers shared by app backups and migration pre-upgrade backups."""

from pathlib import Path


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
