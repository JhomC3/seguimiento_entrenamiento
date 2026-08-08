"""Backup retention helpers shared by app backups and migration pre-upgrade backups."""

from pathlib import Path


def prune_backups(backups_dir: str, keep: int) -> None:
    files = sorted(Path(backups_dir).glob("gym-*.db"))
    if len(files) <= keep:
        return
    for stale in files[:-keep]:
        stale.unlink(missing_ok=True)
