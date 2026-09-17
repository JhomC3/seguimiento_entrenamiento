package com.jhomc.healthsync

import com.jhomc.healthsync.data.NutritionPublishDao
import com.jhomc.healthsync.data.NutritionPublishEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakePublishDao : NutritionPublishDao {
    val store = mutableMapOf<String, NutritionPublishEntity>()
    override suspend fun forFecha(fecha: String): NutritionPublishEntity? = store[fecha]
    override suspend fun put(state: NutritionPublishEntity) {
        store[state.fecha] = state
    }
    override suspend fun clear(fecha: String) {
        store.remove(fecha)
    }
}

class NutritionPublisherTest {

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

    private fun avena(orden: Int = 1, cantidad: Double? = 50.0) = FoodEntry(
        orden = orden,
        alimento = "Avena",
        cantidadG = cantidad,
        nutrients = mapOf(
            "kcal" to 195.0, "carbohidratos" to 33.0, "fibra" to 5.0,
            "proteina" to 6.5, "grasa" to 3.5, "hierro" to 2.1,
            "calcio" to 27.0, "vitamina_c" to 0.0, "vitamina_a" to 0.0,
        ),
    )

    @Test
    fun `publica y no repite si hash igual`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply {
            granted = setOf("android.permission.health.WRITE_NUTRITION")
        }
        val dao = FakePublishDao()
        val publisher = NutritionPublisher(gateway, dao, manager = null)
        val d = day(avena())

        val first = publisher.publishDay(d)
        assertTrue(first is NutritionPublisher.Outcome.Published)
        assertEquals(1, gateway.insertedNutrition.size)

        val second = publisher.publishDay(d)
        assertTrue(second is NutritionPublisher.Outcome.Skipped)
        assertEquals(1, gateway.insertedNutrition.size)
    }

    @Test
    fun `edicion borra huerfanos y re-publica`() = runBlocking {
        val gateway = FakeHealthConnectGateway()
        val dao = FakePublishDao()
        val publisher = NutritionPublisher(gateway, dao, manager = null)

        publisher.publishDay(day(avena(orden = 1), avena(orden = 2)))
        assertEquals(2, gateway.insertedNutrition.size)

        // Se quita la fila 2: debe borrar su clientId y publicar la 1 (upsert).
        gateway.insertedNutrition.clear()
        val res = publisher.publishDay(day(avena(orden = 1)))
        assertTrue(res is NutritionPublisher.Outcome.Published)
        assertEquals(listOf("gym-diario-2026-09-15-2"), gateway.deletedClientIds)
        assertEquals(1, gateway.insertedNutrition.size)
    }

    @Test
    fun `borrado limpia HC y estado`() = runBlocking {
        val gateway = FakeHealthConnectGateway()
        val dao = FakePublishDao()
        val publisher = NutritionPublisher(gateway, dao, manager = null)

        publisher.publishDay(day(avena()))
        val res = publisher.deleteDay("2026-09-15")
        assertTrue(res is NutritionPublisher.Outcome.Published)
        assertEquals(listOf("gym-diario-2026-09-15-1"), gateway.deletedClientIds)
        assertEquals(null, dao.forFecha("2026-09-15"))
    }

    @Test
    fun `sin permiso no toca HC y queda PENDING`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply { granted = emptySet() }
        val dao = FakePublishDao()
        // Manager real para exigir WRITE_NUTRITION (fake sin permiso).
        val manager = HealthConnectManager(gateway)
        val publisher = NutritionPublisher(gateway, dao, manager)

        val res = publisher.publishDay(day(avena()))
        assertTrue(res is NutritionPublisher.Outcome.Failed)
        assertTrue(gateway.insertedNutrition.isEmpty())
        assertEquals("PENDING", dao.forFecha("2026-09-15")?.status)
    }
}
