"""v013 — journal de undo persistente en SQLite.

Sustituye la pila de undo en memoria por una tabla versionada: el historial
sobrevive reinicios y la operación es transaccional (pop solo tras un restore
exitoso). Se conservan las 10 entradas más recientes (trim en la misma
transacción que el insert).
"""

VERSION = 13
NAME = "persistent_undo"


def migrate(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS undo_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_undo_entries_newest ON undo_entries(id DESC)")
