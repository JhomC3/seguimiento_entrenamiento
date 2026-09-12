package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.PendingWriteEntity
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * B4: drenado de la cola (en orden; 400 descarta; fallo de red conserva).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class OfflineDrainTest {

    private lateinit var db: HealthDatabase
    private lateinit var repo: TrainingRepository
    private lateinit var server: MockWebServer
    private lateinit var base: String

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        repo = TrainingRepository(db.trainingCacheDao(), db.offlineDao())
        server = MockWebServer()
        server.start()
        base = "http://${server.hostName}:${server.port}"
    }

    @After
    fun tearDown() {
        server.shutdown()
        db.close()
    }

    private fun savePayload(fecha: String) = JSONObject()
        .put("fecha", fecha)
        .put("sets", org.json.JSONArray().put(
            JSONObject().put("ejercicio", "Press").put("kg", 80).put("reps", 8).put("rir", 1),
        )).toString()

    @Test
    fun `drain envia y confirma`() = runBlocking {
        db.offlineDao().enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", savePayload("2026-09-07"), 1L))
        // El POST drenado + el GET de refresco tras entregar.
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"fecha":"2026-09-07","semana":19,"dia":"LUNES","has_data":true,"sets":[{"set_orden":1,"ejercicio":"Press","kg":80.0,"reps":8.0,"rir":1.0,"descanso_seg":null,"rm":103.9}]}""",
        ))
        server.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"fecha":"2026-09-07","semana":19,"dia":"LUNES","has_data":true,"sets":[{"set_orden":1,"ejercicio":"Press","kg":80.0,"reps":8.0,"rir":1.0,"descanso_seg":null,"rm":103.9}]}""",
        ))
        assertEquals(1, repo.drainOutbox(base, "secret"))
        assertEquals(0, repo.pendingCount())
        assertEquals("/api/v1/sesion", server.takeRequest().path)
        // La caché refleja el servidor tras drenar.
        assertEquals(1, db.trainingCacheDao().rowsFor("2026-09-07").size)
    }

    @Test
    fun `drain descarta el 400 sin contarlo y para en fallo de red`() = runBlocking {
        db.offlineDao().enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", savePayload("2026-09-07"), 1L))
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"Debes registrar al menos una serie."}"""))
        var acked = 0
        assertEquals(0, repo.drainOutbox(base, "secret") { acked++ })
        assertEquals(1, acked)
        assertEquals(0, repo.pendingCount())

        db.offlineDao().enqueue(PendingWriteEntity("diario", "2026-09-07", "SAVE", """{"fecha":"2026-09-07"}""", 2L))
        server.shutdown()
        val deadBase = "http://127.0.0.1:9"
        assertEquals(0, repo.drainOutbox(deadBase, "secret"))
        assertEquals(1, repo.pendingCount())
    }

    @Test
    fun `drain conserva la cola ante 401 y marca bloqueo`() = runBlocking {
        db.offlineDao().enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", savePayload("2026-09-07"), 1L))
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Token inválido."}"""))
        var acked = 0
        assertEquals(0, repo.drainOutbox(base, "secret") { acked++ })
        assertEquals(0, acked)
        assertEquals(1, repo.pendingCount())
        assertTrue(repo.drainAuthBlocked)
    }

    @Test
    fun `drain conserva la cola ante 429`() = runBlocking {
        db.offlineDao().enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", savePayload("2026-09-07"), 1L))
        server.enqueue(MockResponse().setResponseCode(429).setBody("límite"))
        assertEquals(0, repo.drainOutbox(base, "secret"))
        assertEquals(1, repo.pendingCount())
    }

    @Test
    fun `getFechas parsea el conjunto`() = runBlocking {
        val server2 = MockWebServer()
        server2.enqueue(MockResponse().setResponseCode(200).setBody(
            """{"schema_version":1,"vista":"entrenamiento","fechas":["2026-09-07","2026-09-06"]}""",
        ))
        server2.start()
        try {
            val client = TrainingApiClient()
            val base2 = "http://${server2.hostName}:${server2.port}"
            val res = client.getFechas(base2, "secret", "entrenamiento")
            assertTrue(res is TrainingResult.Ok)
            assertEquals(setOf("2026-09-07", "2026-09-06"), (res as TrainingResult.Ok).value)
        } finally {
            server2.shutdown()
        }
    }
}
