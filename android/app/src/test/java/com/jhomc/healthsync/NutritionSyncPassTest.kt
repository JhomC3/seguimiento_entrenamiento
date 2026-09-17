package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.NutritionPublishEntity
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * El pase del sync publica lo guardado en la web aunque el diario móvil
 * nunca haya abierto esa fecha (la Activity no expone la vista de
 * alimentación).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class NutritionSyncPassTest {

    private lateinit var db: HealthDatabase
    private lateinit var server: MockWebServer
    private lateinit var base: String

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        server = MockWebServer()
        server.start()
        base = "http://${server.hostName}:${server.port}"
    }

    @After
    fun tearDown() {
        server.shutdown()
        db.close()
    }

    private fun diarioJson(fecha: String, hasData: Boolean, prefilled: Boolean = false): String {
        val nuts = """"kcal":195.0,"carbohidratos":33.0,"fibra":5.0,"proteina":6.5,"grasa":3.5,"hierro":2.1,"calcio":27.0,"vitamina_c":0.0,"vitamina_a":0.0"""
        val entrada = """{"orden":1,"alimento":"Avena","cantidad_g":50.0,$nuts}"""
        val entradas = if (hasData || prefilled) "[$entrada]" else "[]"
        return """{"schema_version":1,"fecha":"$fecha","has_data":$hasData,"prefilled":$prefilled,"prefill_source":null,"entradas":$entradas,"consumido":{$nuts,"cantidad_g":50.0},"objetivo":{$nuts},"parametros":{"peso_kg":70.0,"factor_proteina":1.5,"factor_grasa":1.1,"kcal_objetivo":2300.0}}"""
    }

    private fun gatewayWithWrite(): FakeHealthConnectGateway =
        FakeHealthConnectGateway().apply { granted = setOf("android.permission.health.WRITE_NUTRITION") }

    @Test
    fun `publica el dia guardado en la web`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"vista":"alimentacion","fechas":["2026-09-14"]}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(diarioJson("2026-09-14", hasData = true)))

        val gateway = gatewayWithWrite()
        val report = NutritionSyncPass.run(
            apiBase = base,
            token = "secret",
            gateway = gateway,
            publishDao = db.nutritionPublishDao(),
            manager = HealthConnectManager(gateway),
        )

        assertEquals(1, report.published)
        assertEquals(0, report.failed)
        assertEquals(1, gateway.insertedNutrition.size)
        assertEquals("Avena (50 g)", gateway.insertedNutrition[0].name)
    }

    @Test
    fun `segunda pasada no duplica`() = runBlocking {
        repeat(2) {
            server.enqueue(MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"vista":"alimentacion","fechas":["2026-09-14"]}""",
            ))
            server.enqueue(MockResponse().setResponseCode(200).setBody(diarioJson("2026-09-14", hasData = true)))
        }

        val gateway = gatewayWithWrite()
        val manager = HealthConnectManager(gateway)
        NutritionSyncPass.run(base, "secret", gateway = gateway, publishDao = db.nutritionPublishDao(), manager = manager)
        val second = NutritionSyncPass.run(base, "secret", gateway = gateway, publishDao = db.nutritionPublishDao(), manager = manager)

        assertEquals(0, second.published)
        assertEquals(1, gateway.insertedNutrition.size)
    }

    @Test
    fun `dia vacio no publica el prefill y limpia huerfanos`() = runBlocking {
        db.nutritionPublishDao().put(
            NutritionPublishEntity("2026-09-14", "viejo", "gym-diario-2026-09-14-1", "OK", null, 1L),
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"vista":"alimentacion","fechas":["2026-09-14"]}""",
        ))
        // Día sin datos propios pero con prefill del día anterior: no publicar.
        server.enqueue(MockResponse().setResponseCode(200).setBody(diarioJson("2026-09-14", hasData = false, prefilled = true)))

        val gateway = gatewayWithWrite()
        val report = NutritionSyncPass.run(
            apiBase = base,
            token = "secret",
            gateway = gateway,
            publishDao = db.nutritionPublishDao(),
            manager = HealthConnectManager(gateway),
        )

        assertEquals(0, report.published)
        assertTrue(gateway.insertedNutrition.isEmpty())
        assertEquals(listOf("gym-diario-2026-09-14-1"), gateway.deletedClientIds)
    }

    @Test
    fun `salta dias con escritura movil pendiente`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"vista":"alimentacion","fechas":["2026-09-14"]}""",
        ))

        val gateway = gatewayWithWrite()
        val report = NutritionSyncPass.run(
            apiBase = base,
            token = "secret",
            gateway = gateway,
            publishDao = db.nutritionPublishDao(),
            manager = HealthConnectManager(gateway),
            pendingFechas = setOf("2026-09-14"),
        )

        // Solo llamó a fechas; el día pendiente no se leyó ni publicó: el
        // drenado pisa después y el próximo sync publica ya reconciliado.
        assertEquals(0, report.published)
        assertTrue(gateway.insertedNutrition.isEmpty())
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `sin permiso de escritura no toca HC`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply { granted = emptySet() }
        val report = NutritionSyncPass.run(
            apiBase = base,
            token = "secret",
            gateway = gateway,
            publishDao = db.nutritionPublishDao(),
            manager = HealthConnectManager(gateway),
        )

        assertEquals("sin_permiso", report.skippedReason)
        assertTrue(gateway.insertedNutrition.isEmpty())
        // Ni siquiera llamó al servidor.
        assertEquals(0, server.requestCount)
    }
}
