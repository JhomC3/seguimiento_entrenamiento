package com.jhomc.healthsync

import java.time.Instant
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NutritionPublishMapperTest {

    private val zone = ZoneId.of("Europe/Madrid")

    /** "Ahora" fijo posterior a las fechas de prueba: slots siempre en pasado. */
    private val NOW = Instant.parse("2026-09-20T12:00:00Z")

    private fun entry(
        orden: Int = 1,
        alimento: String = "Avena",
        cantidadG: Double? = 50.0,
        kcal: Double? = 195.0,
        carbos: Double? = 33.0,
        fibra: Double? = 5.0,
        proteina: Double? = 6.5,
        grasa: Double? = 3.5,
        hierro: Double? = 2.1,
        calcio: Double? = 27.0,
        vitC: Double? = 0.0,
        vitA: Double? = 0.0,
    ) = FoodEntry(
        orden = orden,
        alimento = alimento,
        cantidadG = cantidadG,
        nutrients = mapOf(
            "kcal" to kcal,
            "carbohidratos" to carbos,
            "fibra" to fibra,
            "proteina" to proteina,
            "grasa" to grasa,
            "hierro" to hierro,
            "calcio" to calcio,
            "vitamina_c" to vitC,
            "vitamina_a" to vitA,
        ),
    )

    private fun day(vararg entries: FoodEntry) = NutritionDay(
        fecha = "2026-09-15",
        hasData = true,
        prefilled = false,
        prefillSource = null,
        entradas = entries.toList(),
        consumido = emptyMap(),
        objetivo = emptyMap(),
        parametros = NutritionParams(70.0, 1.5, 1.1, 2300.0),
    )

    @Test
    fun `mapea energia y macros en gramos`() {
        val mapped = NutritionPublishMapper.mapDay(day(entry()), zone, NOW)
        assertEquals(1, mapped.size)
        val r = mapped[0].record
        assertEquals("Avena (50 g)", r.name)
        assertNotNull(r.energy)
        assertEquals(195.0, r.energy!!.inKilocalories, 0.001)
        assertEquals(6.5, r.protein!!.inGrams, 0.001)
        assertEquals(33.0, r.totalCarbohydrate!!.inGrams, 0.001)
        assertEquals(3.5, r.totalFat!!.inGrams, 0.001)
        assertEquals(5.0, r.dietaryFiber!!.inGrams, 0.001)
    }

    @Test
    fun `convierte mg y microgramos a gramos`() {
        val mapped = NutritionPublishMapper.mapDay(day(entry(hierro = 2.1, calcio = 27.0, vitC = 1.5, vitA = 900.0)), zone, NOW)
        val r = mapped[0].record
        assertEquals(0.0021, r.iron!!.inGrams, 1e-6)
        assertEquals(0.027, r.calcium!!.inGrams, 1e-6)
        assertEquals(0.0015, r.vitaminC!!.inGrams, 1e-6)
        // 900 µg = 0.0009 g
        assertEquals(0.0009, r.vitaminA!!.inGrams, 1e-7)
    }

    @Test
    fun `omite ceros y nulos sin tumbar la fila`() {
        val mapped = NutritionPublishMapper.mapDay(day(entry(fibra = 0.0, vitC = null, vitA = null)), zone, NOW)
        val r = mapped[0].record
        assertNull(r.vitaminC)
        assertNull(r.vitaminA)
        // fibra 0 se omite pero la fila sobrevive por la energía
        assertNull(r.dietaryFiber)
        assertNotNull(r.energy)
    }

    @Test
    fun `omite fila sin nutrientes validos`() {
        val mapped = NutritionPublishMapper.mapDay(
            day(entry(kcal = 0.0, carbos = 0.0, fibra = 0.0, proteina = 0.0, grasa = 0.0, hierro = 0.0, calcio = 0.0)),
            zone, NOW,
        )
        assertTrue(mapped.isEmpty())
    }

    @Test
    fun `clientRecordId estable y version por contenido`() {
        val e = entry()
        val id1 = NutritionPublishMapper.clientRecordId("2026-09-15", 1)
        val id2 = NutritionPublishMapper.clientRecordId("2026-09-15", 1)
        assertEquals(id1, id2)
        assertEquals("gym-diario-2026-09-15-1", id1)
        val v1 = NutritionPublishMapper.contentVersion(e)
        val v2 = NutritionPublishMapper.contentVersion(e.copy(cantidadG = 60.0))
        assertTrue(v1 >= 1)
        assertTrue(v1 != v2)
    }

    @Test
    fun `conserva la fecha del diario y tipo desconocido`() {
        val four = NutritionPublishMapper.mapDay(
            day(entry(orden = 1), entry(orden = 2), entry(orden = 3), entry(orden = 4)),
            zone, NOW,
        )
        assertEquals(4, four.size)
        // Todas las filas comparten la fecha del diario, no la fecha del sync.
        val expectedEnd = java.time.LocalDate.of(2026, 9, 15)
            .atTime(12, 0)
            .atZone(zone)
            .toInstant()
        for (m in four) {
            assertEquals(expectedEnd, m.record.endTime)
            assertEquals(expectedEnd.minusSeconds(60), m.record.startTime)
            assertEquals(
                androidx.health.connect.client.records.MealType.MEAL_TYPE_UNKNOWN,
                m.record.mealType,
            )
        }
        // IDs estables por posición.
        assertEquals(
            listOf("gym-diario-2026-09-15-1", "gym-diario-2026-09-15-2"),
            four.take(2).map { it.clientRecordId },
        )
    }

    @Test
    fun `version temporal nueva fuerza corregir registros antiguos`() {
        assertTrue(NutritionPublishMapper.contentVersion(entry()) > 2_147_483_647L)
        assertTrue(NutritionPublishMapper.dayHash(day(entry())).startsWith("v2-"))
    }

    @Test
    fun `nunca publica en futuro aunque el dia sea hoy`() {
        val now = Instant.now()
        val today = java.time.LocalDate.now(zone).toString()
        val d = day(entry()).copy(fecha = today)
        val mapped = NutritionPublishMapper.mapDay(d, zone, now)
        assertEquals(1, mapped.size)
        assertTrue(!mapped[0].record.startTime.isAfter(now))
    }

    @Test
    fun `fecha invalida no publica nada`() {
        val bad = day(entry()).copy(fecha = "no-fecha")
        assertTrue(NutritionPublishMapper.mapDay(bad, zone, NOW).isEmpty())
    }
}
