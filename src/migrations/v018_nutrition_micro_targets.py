"""v018 — objetivos DRI de micros + curaduría del catálogo de alimentos.

1. Rellena los objetivos de micronutrientes en `parametros_diarios` que valen
   0 (ausencia: el parser mapea blanco a 0.0) con los DRI de hombre adulto
   (espejo de `src/nutrition_service.py::MICRO_DRI_TARGETS`, NIH ODS):
   fibra 38 g, hierro 8 mg, calcio 1000 mg, vitamina C 90 mg,
   vitamina A 900 mcg RAE. Los valores no-cero de la hoja se conservan.
2. Corrige `Arepa`: la hoja trae valores x100 (6900 kcal) porque el diario la
   consume por unidad (69 kcal/unidad). Se reescala a por-unidad y pasa a
   `origen='manual'` para que futuras importaciones no la pisen.
3. Corrige `Huevo.vitamina_a` 0 -> 160 mcg (USDA, huevo crudo) y lo protege
   como `manual`.
4. Crea los dos alimentos huérfanos del diario (`Bocadillo de guayaba (ICBF)`
   ~= `Bocadillo`; `Yuca cocinada` ~= yuca hervida USDA) como `manual`.

Todo es idempotente (UPDATE con guarda, INSERT OR IGNORE) y no toca
`diario_alimentacion`: los snapshots históricos se conservan.
"""

VERSION = 18
NAME = "nutrition_micro_targets"

_MICRO_DEFAULTS = (
    ("fibra_objetivo", 38.0),
    ("hierro_objetivo", 8.0),
    ("calcio_objetivo", 1000.0),
    ("vitamina_c_objetivo", 90.0),
    ("vitamina_a_objetivo", 900.0),
)


def migrate(conn) -> None:
    for column, value in _MICRO_DEFAULTS:
        conn.execute(
            f"UPDATE parametros_diarios SET {column} = ? WHERE {column} = 0",
            (value,),
        )
    # Arepa por unidad (69 kcal/unidad, como la consume el diario).
    conn.execute(
        """UPDATE alimentos SET
               kcal = 69.0, carbohidratos = 14.4, fibra = 1.5, proteina = 2.8,
               grasa = 0.5, hierro = 0.09, calcio = 15.3, vitamina_c = 0.0,
               vitamina_a = 17.1, origen = 'manual'
           WHERE nombre = 'Arepa' AND kcal > 900"""
    )
    # Huevo: vitamina A USDA (~160 mcg/100 g, huevo crudo).
    conn.execute(
        """UPDATE alimentos SET vitamina_a = 160.0, origen = 'manual'
           WHERE nombre = 'Huevo' AND vitamina_a = 0"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO alimentos
               (nombre, categoria, kcal, carbohidratos, fibra, proteina, grasa,
                hierro, calcio, vitamina_c, vitamina_a, origen)
           SELECT 'Bocadillo de guayaba (ICBF)', 'Procesado', 332.0, 79.6, 3.7,
                0.4, 0.5, 1.2, 25.0, 80.0, 0.0, 'manual'
           WHERE EXISTS (SELECT 1 FROM diario_alimentacion
                         WHERE alimento = 'Bocadillo de guayaba (ICBF)')"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO alimentos
               (nombre, categoria, kcal, carbohidratos, fibra, proteina, grasa,
                hierro, calcio, vitamina_c, vitamina_a, origen)
           SELECT 'Yuca cocinada', 'Vegetal', 120.0, 27.0, 2.0, 1.0, 0.3,
                0.3, 15.0, 15.0, 1.0, 'manual'
           WHERE EXISTS (SELECT 1 FROM diario_alimentacion
                         WHERE alimento = 'Yuca cocinada')"""
    )
