"""v019 — 12 micronutrientes nuevos en alimentación.

Esquema: `magnesio, zinc, potasio, sodio, vitamina_d, vitamina_e,
vitamina_k, folato, vitamina_b12, vitamina_b6, yodo, selenio`
(REAL NOT NULL DEFAULT 0) en `alimentos`, `diario_alimentacion` y
`parametros_diarios` (`*_objetivo`).

Datos:
1. Objetivos nuevos en 0 (ausencia) -> DRI hombre adulto (NIH ODS).
   Los no-cero se conservan.
2. Curaduría inicial (USDA SR Legacy, por 100 g) de 7 básicos con valores
   bien establecidos; pasan a `origen='manual'`. El resto queda en 0
   (pendiente de curaduría vía hoja o alta manual), nunca inventado.

Idempotente: ADD COLUMN con guarda PRAGMA, UPDATEs con guarda, sin tocar
snapshots históricos de `diario_alimentacion`.
"""

VERSION = 19
NAME = "extra_micros"

NEW_FIELDS: tuple[str, ...] = (
    "magnesio",
    "zinc",
    "potasio",
    "sodio",
    "vitamina_d",
    "vitamina_e",
    "vitamina_k",
    "folato",
    "vitamina_b12",
    "vitamina_b6",
    "yodo",
    "selenio",
)

# DRI hombre adulto (NIH ODS): Mg 420, Zn 11, K 3400 AI, Na 1500 AI,
# vitD 15 mcg, vitE 15 mg, vitK 120 mcg AI, folato 400 mcg DFE,
# B12 2.4 mcg, B6 1.3 mg, yodo 150 mcg, selenio 55 mcg.
_NEW_DRI_DEFAULTS: tuple[tuple[str, float], ...] = (
    ("magnesio_objetivo", 420.0),
    ("zinc_objetivo", 11.0),
    ("potasio_objetivo", 3400.0),
    ("sodio_objetivo", 1500.0),
    ("vitamina_d_objetivo", 15.0),
    ("vitamina_e_objetivo", 15.0),
    ("vitamina_k_objetivo", 120.0),
    ("folato_objetivo", 400.0),
    ("vitamina_b12_objetivo", 2.4),
    ("vitamina_b6_objetivo", 1.3),
    ("yodo_objetivo", 150.0),
    ("selenio_objetivo", 55.0),
)

# (nombre, Mg, Zn, K, Na, vitD, vitE, vitK, folato, B12, B6, yodo, selenio)
_CURADURIA: tuple[tuple, ...] = (
    ("Avena", 177.0, 4.0, 429.0, 2.0, 0.0, 1.0, 2.0, 56.0, 0.0, 0.12, 0.0, 34.0),
    ("Arroz Blanco", 12.0, 0.4, 35.0, 1.0, 0.0, 0.1, 0.1, 3.0, 0.0, 0.09, 0.0, 7.5),
    ("Banano", 27.0, 0.15, 358.0, 1.0, 0.0, 0.1, 0.5, 20.0, 0.0, 0.37, 0.0, 1.0),
    ("Almendras", 270.0, 3.1, 733.0, 1.0, 0.0, 25.6, 0.0, 44.0, 0.0, 0.14, 0.0, 4.1),
    ("Huevo", 12.0, 1.3, 138.0, 142.0, 2.0, 1.05, 0.3, 47.0, 0.89, 0.17, 25.0, 30.7),
    ("Papa", 23.0, 0.3, 421.0, 6.0, 0.0, 0.01, 1.9, 16.0, 0.0, 0.30, 0.0, 0.3),
    ("Zanahoria", 12.0, 0.24, 320.0, 69.0, 0.0, 0.66, 13.2, 19.0, 0.0, 0.14, 0.0, 0.1),
)

_TABLES = ("alimentos", "diario_alimentacion", "parametros_diarios")


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(conn) -> None:
    for table in _TABLES:
        cols = _columns(conn, table)
        for field in NEW_FIELDS:
            col = f"{field}_objetivo" if table == "parametros_diarios" else field
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL NOT NULL DEFAULT 0")
    for column, value in _NEW_DRI_DEFAULTS:
        conn.execute(
            f"UPDATE parametros_diarios SET {column} = ? WHERE {column} = 0",
            (value,),
        )
    for row in _CURADURIA:
        nombre, *vals = row
        sets = ", ".join(f"{f} = ?" for f in NEW_FIELDS)
        conn.execute(
            f"UPDATE alimentos SET {sets}, origen = 'manual' "
            f"WHERE nombre = ? AND magnesio = 0 AND zinc = 0 AND selenio = 0",
            (*vals, nombre),
        )
