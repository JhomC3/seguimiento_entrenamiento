"""v014 — índice para lectura/escritura de sesión por fecha.

El plan frontend ocupa v013 (journal de undo); este índice es la migración 14.
"""

VERSION = 14
NAME = "training_fecha_index"


def migrate(conn) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_fecha_set_orden ON training_sets(fecha, set_orden)"
    )
