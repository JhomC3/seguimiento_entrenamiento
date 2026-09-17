"""v020 — rellena objetivos DRI en 0 dejados por guardados sin micros.

Contexto: el formulario y la API solo envían macros (peso/factores/kcal);
hasta este lote, `save_parametros_diarios` persistía los 17 `*_objetivo`
ausentes como 0.0 y la fila Objetivo quedaba vacía en esos días (los
guardados vía `import_nutrition.py` ya rellenaban con DRI). Desde este lote,
`mutation_service` normaliza a DRI al guardar; esta migración repara las
filas históricas en 0. Los no-cero (p. ej. importados de la hoja) se
conservan. Idempotente.
"""

VERSION = 20
NAME = "dri_ceros"

# Espejo de `src/nutrition_service.py::MICRO_DRI_TARGETS` (DRI hombre 31-50,
# NIH ODS; K/Na AI NASEM 2019). Fijo aquí: las migraciones no siguen al código.
_DRI_DEFAULTS: tuple[tuple[str, float], ...] = (
    ("fibra_objetivo", 38.0),
    ("hierro_objetivo", 8.0),
    ("calcio_objetivo", 1000.0),
    ("vitamina_c_objetivo", 90.0),
    ("vitamina_a_objetivo", 900.0),
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


def migrate(conn) -> None:
    for column, value in _DRI_DEFAULTS:
        conn.execute(
            f"UPDATE parametros_diarios SET {column} = ? WHERE {column} = 0",
            (value,),
        )
