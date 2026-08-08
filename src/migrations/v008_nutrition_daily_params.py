"""v008 — nutrition daily params and nullable quantity.

- New table `parametros_diarios` (per-date weight, protein/fat factors and
  calorie target; the remaining target nutrients are imported from the sheet).
- `diario_alimentacion.cantidad_g` becomes nullable so placeholder rows (food
  logged without a quantity, shown as "—") can be stored.
"""

VERSION = 8
NAME = "nutrition_daily_params"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS parametros_diarios (
    fecha TEXT PRIMARY KEY,
    peso_kg REAL NOT NULL DEFAULT 70,
    factor_proteina REAL NOT NULL DEFAULT 1.5,
    factor_grasa REAL NOT NULL DEFAULT 1.1,
    kcal_objetivo REAL NOT NULL DEFAULT 2300,
    fibra_objetivo REAL NOT NULL DEFAULT 0,
    hierro_objetivo REAL NOT NULL DEFAULT 0,
    calcio_objetivo REAL NOT NULL DEFAULT 0,
    vitamina_c_objetivo REAL NOT NULL DEFAULT 0,
    vitamina_a_objetivo REAL NOT NULL DEFAULT 0
);
"""


def migrate(conn) -> None:
    conn.execute(_SCHEMA_SQL)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(diario_alimentacion)").fetchall()}
    if "cantidad_g" not in cols:
        return
    not_null = {
        r[1] for r in conn.execute("PRAGMA table_info(diario_alimentacion)").fetchall() if r[3] == 1
    }
    if "cantidad_g" in not_null:
        # Rebuild the table with cantidad_g nullable, preserving rows and index.
        conn.execute(
            "CREATE TABLE diario_alimentacion_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "fecha TEXT NOT NULL, "
            "orden INTEGER NOT NULL, "
            "alimento TEXT NOT NULL, "
            "cantidad_g REAL, "
            "kcal REAL NOT NULL, "
            "carbohidratos REAL NOT NULL, "
            "fibra REAL NOT NULL, "
            "proteina REAL NOT NULL, "
            "grasa REAL NOT NULL, "
            "hierro REAL NOT NULL, "
            "calcio REAL NOT NULL, "
            "vitamina_c REAL NOT NULL, "
            "vitamina_a REAL NOT NULL, "
            "origen TEXT NOT NULL DEFAULT 'google'"
            ")"
        )
        conn.execute(
            "INSERT INTO diario_alimentacion_new (id, fecha, orden, alimento, cantidad_g, "
            "kcal, carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, "
            "vitamina_a, origen) "
            "SELECT id, fecha, orden, alimento, cantidad_g, kcal, carbohidratos, fibra, "
            "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, origen "
            "FROM diario_alimentacion"
        )
        conn.execute("DROP TABLE diario_alimentacion")
        conn.execute("ALTER TABLE diario_alimentacion_new RENAME TO diario_alimentacion")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_diario_alimentacion_fecha_orden "
            "ON diario_alimentacion(fecha, orden)"
        )
