package com.jhomc.healthsync

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Contrato cliente B5.0 (training-api-contract.md §B5) + drenado del repo.
 * El servidor Python cubre el otro lado en tests/test_breathing_api.py.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class BreathingApiTest {

    private val client = TrainingApiClient()
    private lateinit var server: MockWebServer
    private lateinit var base: String
    private lateinit var db: HealthDatabase

    private val defaultTz: java.util.TimeZone = java.util.TimeZone.getDefault()

    @Before
    fun setUp() {
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("UTC"))
        server = MockWebServer()
        server.start()
        base = "http://${server.hostName}:${server.port}"
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext<Context>(),
            HealthDatabase::class.java,
        ).build()
    }

    @After
    fun tearDown() {
        server.shutdown()
        db.close()
        java.util.TimeZone.setDefault(defaultTz)
    }

    private fun saveBody(): String =
        """{"schema_version":1,"client_session_id":"u1","fecha":"2026-09-13","ciclos_completados":12,"bpm_medio":6.0,"duracion_real_sec":120,"saved":true}"""

    @Test
    fun `save parsea metricas del servidor`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(saveBody()))
        val body = BreathingRepository.savePayload(
            "u1", 1000L, 121_000L, 0, 120,
            BreathingPattern(4.0, 0.0, 6.0, 0.0), true,
        )
        val res = client.saveBreathingSession(base, "secret", body)
        assertTrue(res is TrainingResult.Ok)
        val saved = (res as TrainingResult.Ok).value
        assertEquals(12, saved.ciclos)
        assertEquals(6.0, saved.bpm, 0.0)
        assertTrue(saved.saved)
        val sent = server.takeRequest()
        assertEquals("/api/v1/respiracion/sesion", sent.path)
        assertEquals("secret", sent.getHeader("X-Sync-Token"))
    }

    @Test
    fun `delete devuelve flag y 400 es permanente`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"schema_version":1,"deleted":true}"""))
        assertEquals(true, (client.deleteBreathingSession(base, "secret", "u1") as TrainingResult.Ok).value)
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"UUID malo"}"""))
        val bad = client.deleteBreathingSession(base, "secret", "x")
        assertTrue(bad is TrainingResult.ApiError)
        assertEquals(400, (bad as TrainingResult.ApiError).status)
    }

    @Test
    fun `drain entrega SAVE y descarta 400`() = runBlocking {
        val repo = BreathingRepository(db.breathingDao())
        val finished = FinishedBreathing(
            clientSessionId = "u1", startMs = 1789282800000L,
            endMs = 1789282800000L + 120_000L, tzOffsetMin = 0,
            plannedS = 120, pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0), completed = true,
        )
        repo.finishSession(finished)
        assertEquals(1, repo.pendingCount())
        server.enqueue(MockResponse().setResponseCode(200).setBody(saveBody()))
        val delivered = repo.drain(base, "secret")
        assertEquals(1, delivered.done)
        assertEquals(0, delivered.rest)
        assertNull(delivered.fault)
        assertEquals(0, delivered.rejected)
        // Reintento sin red conserva la cola.
        repo.finishSession(finished.copy(clientSessionId = "u2"))
        server.shutdown()
        val down = repo.drain(base, "secret")
        assertEquals(0, down.done)
        assertEquals(1, down.rest)
        assertTrue((down.fault ?: "").isNotEmpty())
        assertEquals(0, down.rejected)
    }

    @Test
    fun `drain conserva la op ante 403 del gate LAN`() = runBlocking {
        // El servidor sin la función responde 403 (no 404): es transitorio,
        // la sesión espera en el móvil y el mensaje lo dice.
        val repo = BreathingRepository(db.breathingDao())
        val finished = FinishedBreathing(
            clientSessionId = "u3", startMs = 1789282800000L,
            endMs = 1789282800000L + 120_000L, tzOffsetMin = 0,
            plannedS = 120, pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0), completed = true,
        )
        repo.finishSession(finished)
        server.enqueue(MockResponse().setResponseCode(403))
        val kept = repo.drain(base, "secret")
        assertEquals(0, kept.done)
        assertEquals(1, kept.rest)
        assertEquals("HTTP 403", kept.fault)
        assertEquals(0, kept.rejected)
        assertEquals("En cola (HTTP 403).", BreathingActivity.drainMessage(kept))
    }

    @Test
    fun `drain cuenta el rechazo 400 sin perderlo en silencio`() = runBlocking {
        val repo = BreathingRepository(db.breathingDao())
        val finished = FinishedBreathing(
            clientSessionId = "u4", startMs = 1789282800000L,
            endMs = 1789282800000L + 120_000L, tzOffsetMin = 0,
            plannedS = 120, pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0), completed = true,
        )
        repo.finishSession(finished)
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"mal"}"""))
        val rejected = repo.drain(base, "secret")
        assertEquals(0, rejected.done)
        assertEquals(0, rejected.rest)
        assertNull(rejected.fault)
        assertEquals(1, rejected.rejected)
        assertEquals(400, rejected.rejectedStatus)
        assertEquals("Rechazada (HTTP 400).", BreathingActivity.drainMessage(rejected))
    }

    @Test
    fun `finishSession guarda historial local con fecha de inicio`() = runBlocking {
        val repo = BreathingRepository(db.breathingDao())
        val finished = FinishedBreathing(
            clientSessionId = "u9", startMs = 1789282800000L,
            endMs = 1789282800000L + 120_000L, tzOffsetMin = 0,
            plannedS = 120, pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0), completed = true,
        )
        repo.finishSession(finished)
        val rows = repo.history("2026-09-13")
        assertEquals(1, rows.size)
        assertEquals(12, rows.single().ciclos)
        assertEquals(false, rows.single().delivered)
        assertTrue(JSONObject(rows.single().patternJson).getDouble("inhale_s") == 4.0)
    }
}
