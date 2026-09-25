"""Ayudantes compartidos de persistencia (spec 006)."""


def _resync_sequence(conn, table: str) -> None:
    """Re-sincroniza sqlite_sequence tras restaurar ids explícitos.

    `table` proviene únicamente de constantes del módulo (nunca de input).
    """
    row = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
    conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (row[0], table))
