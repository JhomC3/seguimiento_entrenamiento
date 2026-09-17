package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.HealthOutboxEntity
import com.jhomc.healthsync.data.HealthRecordEntity
import com.jhomc.healthsync.data.SyncTargetEntity
import java.time.Instant
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import org.json.JSONArray
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
 * Entrega por lotes: el cliente debe respetar el límite de BYTES del servidor
 * (1 MiB) además del de operaciones, y autocurarse ante un 413 partiendo el
 * lote a la mitad. Verificado en dispositivo: HEART_RATE con series grandes
 * producía lotes de 500 ops de varios MiB → 413 permanente → outbox atascado.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositoryUploadTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private lateinit var repo: HealthRepository

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        gateway = FakeHealthConnectGateway()
        repo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { Instant.parse("2026-08-08T12:00:00Z") },
            pacer = {},
        )
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun bigRecord(hcId: String, kb: Int) = HealthRecordEntity(
        hcId = hcId,
        recordType = "HEART_RATE",
        startEpochMs = 1_000_000,
        endEpochMs = 1_000_100,
        lastModifiedEpochMs = 100L,
        dataOriginPackage = "com.samsung.health",
        timeZoneOffsetMinutes = null,
        payloadSchemaVersion = 1,
        valueJson = """{"samples":["${"x".repeat(kb * 1024)}"]}""",
        sourceUpdatedAtEpochMs = 1L,
    )

    /** Siembra target + N registros grandes + N ops de outbox. */
    private suspend fun seed(records: List<Pair<String, HealthRecordEntity>>) {
        val targetId = db.healthDao().upsertTarget(SyncTargetEntity(0, "http://x/", "test", true, 1L))
        for ((hcId, record) in records) {
            db.healthDao().upsertRecord(record)
            db.healthDao().upsertOutbox(HealthOutboxEntity(targetId, hcId, "UPSERT", 100L, 0, 1L))
        }
    }

    /**
     * Cliente HTTP en proceso (Robolectric bloquea sockets reales): un
     * Interceptor captura cada request, registra el cuerpo, y devuelve el
     * status/cuerpo según la política dada. Sin red ni archivos temporales.
     */
    private fun fakeClient(
        bodies: MutableList<String>,
        status: (Int) -> Int,
    ): HealthSyncClient {
        val http = OkHttpClient.Builder()
            .addInterceptor { chain ->
                val bodyText = chain.request().body?.let { body ->
                    val buffer = Buffer()
                    body.writeTo(buffer)
                    buffer.readUtf8()
                } ?: ""
                bodies.add(bodyText)
                val code = status(bodyText.length)
                val responseBody = if (code == 200) {
                    ackBodyFor(bodyText)
                } else {
                    ResponseBody.create(null, """{"detail":"Lote excesivo"}""")
                }
                Response.Builder()
                    .request(chain.request())
                    .protocol(Protocol.HTTP_1_1)
                    .code(code)
                    .message("")
                    .body(responseBody)
                    .build()
            }
            .build()
        return HealthSyncClient(http = http)
    }

    /** Acuse por operación: eco de hc_id + revision del propio lote. */
    private fun ackBodyFor(bodyText: String): ResponseBody {
        return ResponseBody.create(null, ackJsonFor(bodyText))
    }

    private fun ackJsonFor(bodyText: String): String {
        val ops = JSONObject(bodyText).getJSONArray("operations")
        val accepted = JSONArray()
        for (i in 0 until ops.length()) {
            val op = ops.getJSONObject(i)
            accepted.put(
                JSONObject()
                    .put("hc_id", op.getString("hc_id"))
                    .put("revision", op.getLong("revision")),
            )
        }
        return """{"schema_version":1,"received":${ops.length()},"accepted_count":${ops.length()},
               "accepted":$accepted,"rejected":[]}""".trimIndent()
    }

    /**
     * Política por CONTENIDO del lote (para simular 400 por op envenenada):
     * decide (status, cuerpo) inspeccionando el JSON enviado.
     */
    private fun fakeClientByBody(
        bodies: MutableList<String>,
        policy: (String) -> Pair<Int, String>,
    ): HealthSyncClient {
        val http = OkHttpClient.Builder()
            .addInterceptor { chain ->
                val bodyText = chain.request().body?.let { body ->
                    val buffer = Buffer()
                    body.writeTo(buffer)
                    buffer.readUtf8()
                } ?: ""
                bodies.add(bodyText)
                val (code, responseText) = policy(bodyText)
                Response.Builder()
                    .request(chain.request())
                    .protocol(Protocol.HTTP_1_1)
                    .code(code)
                    .message("")
                    .body(ResponseBody.create(null, responseText))
                    .build()
            }
            .build()
        return HealthSyncClient(http = http)
    }

    private fun stepsRecord(hcId: String) = HealthRecordEntity(
        hcId = hcId,
        recordType = "STEPS_H1",
        startEpochMs = 1_000_000,
        endEpochMs = 4_600_000,
        lastModifiedEpochMs = 100L,
        dataOriginPackage = null,
        timeZoneOffsetMinutes = null,
        payloadSchemaVersion = 1,
        valueJson = """{"count":10}""",
        sourceUpdatedAtEpochMs = 1L,
    )

    private fun legacyStepsRecord(hcId: String) = HealthRecordEntity(
        hcId = hcId,
        recordType = "STEPS",
        startEpochMs = 1_000_000,
        endEpochMs = 1_001_000,
        lastModifiedEpochMs = 100L,
        dataOriginPackage = "com.samsung.health",
        timeZoneOffsetMinutes = null,
        payloadSchemaVersion = 1,
        valueJson = """{"count":10}""",
        sourceUpdatedAtEpochMs = 1L,
    )

    /** Siembra target + ops con created_at creciente (orden FIFO determinista). */
    private suspend fun seedOrdered(hcIds: List<String>) {
        val targetId = db.healthDao().upsertTarget(SyncTargetEntity(0, "http://x/", "test", true, 1L))
        hcIds.forEachIndexed { i, hcId ->
            db.healthDao().upsertRecord(stepsRecord(hcId))
            db.healthDao().upsertOutbox(
                HealthOutboxEntity(targetId, hcId, "UPSERT", 100L, 0, createdAtEpochMs = (i + 1).toLong()),
            )
        }
    }

    @Test
    fun `oversized batches are split by bytes and everything is delivered`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClient(bodies) { 200 }
        val records = (1..120).associate { "hc-$it" to bigRecord("hc-$it", kb = 15) } // ~1,8 MB total
        seed(records.toList())
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals(120, result.delivered)
        assertEquals(0, result.failed)
        assertTrue("debe partirse en varios POSTs, hubo ${bodies.size}", bodies.size >= 2)
        for (body in bodies) {
            assertTrue(
                "ningún lote puede superar el límite del servidor (1 MiB), fue ${body.length}",
                body.length <= 1_000_000,
            )
        }
        assertTrue(db.healthDao().pendingOps(target.targetId, 10).isEmpty())
    }

    @Test
    fun `413 responses self-heal by halving the batch`() = runBlocking {
        val bodies = mutableListOf<String>()
        var rejected = 0
        val client = fakeClient(bodies) { size ->
            if (size > 150_000) {
                rejected++
                413
            } else {
                200
            }
        }
        val records = (1..120).associate { "hc-$it" to bigRecord("hc-$it", kb = 15) }
        seed(records.toList())
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals("todos entregan pese a los 413", 120, result.delivered)
        assertEquals(0, result.failed)
        assertTrue("el servidor debió rechazar alguna vez", rejected > 0)
        assertTrue(db.healthDao().pendingOps(target.targetId, 10).isEmpty())
    }

    @Test
    fun `400 con una op envenenada aisla en cuarentena y entrega el resto`() = runBlocking {
        val bodies = mutableListOf<String>()
        // El veneno pasa el pre-vuelo (registro válido) pero el servidor lo
        // rechaza: cualquier lote que lo contenga vuelve 400 de nivel-op.
        val client = fakeClientByBody(bodies) { body ->
            if (body.contains("hc-poison")) {
                400 to """{"detail":"Operación 2: value (objeto) requerido en UPSERT"}"""
            } else {
                200 to ackJsonFor(body)
            }
        }
        val ids = (1..9).map { "hc-$it" } + "hc-poison"
        seedOrdered(ids)
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals("todo lo sano se entrega", 9, result.delivered)
        assertEquals("el veneno queda en cuarentena", 1, result.quarantined)
        assertEquals(0, result.failed)
        assertTrue(result.permanentError == null)
        assertTrue(db.healthDao().pendingOps(target.targetId, 10).isEmpty())
    }

    @Test
    fun `400 de nivel lote no biseca y para con fallo`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClientByBody(bodies) { _ ->
            400 to """{"detail":"device_id requerido"}"""
        }
        seedOrdered((1..6).map { "hc-$it" })
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals("un solo POST, sin bisección", 1, bodies.size)
        assertEquals(0, result.delivered)
        assertEquals(6, result.failed)
        assertEquals(0, result.quarantined)
        assertTrue(result.permanentError?.contains("400") == true)
    }

    @Test
    fun `ops huerfanas van a cuarentena sin POST`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClientByBody(bodies) { body -> 200 to ackJsonFor(body) }
        val targetId = db.healthDao().upsertTarget(SyncTargetEntity(0, "http://x/", "test", true, 1L))
        // Op sin registro local: jamás podría entregarse.
        db.healthDao().upsertOutbox(HealthOutboxEntity(targetId, "hc-ghost", "UPSERT", 100L, 0, 1L))
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertTrue("sin red para huérfanos", bodies.isEmpty())
        assertEquals(1, result.quarantined)
        assertEquals("sin registro local", result.quarantineSample)
        assertEquals(0, result.delivered)
        assertTrue(db.healthDao().pendingOps(target.targetId, 10).isEmpty())
    }

    @Test
    fun `401 no biseca y para con fallo`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClientByBody(bodies) { _ ->
            401 to """{"detail":"Token inválido"}"""
        }
        seedOrdered((1..4).map { "hc-$it" })
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals("un solo POST ante 401", 1, bodies.size)
        assertEquals(4, result.failed)
        assertEquals(0, result.quarantined)
    }

    @Test
    fun `el crudo legacy se entrega, no se cuarentena`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClientByBody(bodies) { body -> 200 to ackJsonFor(body) }
        val targetId = db.healthDao().upsertTarget(SyncTargetEntity(0, "http://x/", "test", true, 1L))
        db.healthDao().upsertRecord(legacyStepsRecord("hc-legacy"))
        db.healthDao().upsertOutbox(HealthOutboxEntity(targetId, "hc-legacy", "UPSERT", 100L, 0, 1L))
        val target = db.healthDao().activeTargets().single()
        val result = repo.uploadPending(client, target, "tok", "dev")

        assertEquals(1, result.delivered)
        assertEquals(0, result.quarantined)
        assertTrue(result.quarantineSample == null)
        assertTrue(db.healthDao().pendingOps(target.targetId, 10).isEmpty())
    }

    @Test
    fun `requeue restaura el crudo caido una sola vez`() = runBlocking {
        val bodies = mutableListOf<String>()
        val client = fakeClientByBody(bodies) { body -> 200 to ackJsonFor(body) }
        val targetId = db.healthDao().upsertTarget(SyncTargetEntity(0, "http://x/", "test", true, 1L))
        // Registro legacy SIN op (cuarentena errónea anterior): se re-encola y entrega.
        db.healthDao().upsertRecord(legacyStepsRecord("hc-dropped"))
        val target = db.healthDao().activeTargets().single()

        val first = repo.uploadPending(client, target, "tok", "dev")
        assertEquals(1, first.delivered)
        assertEquals(0, first.quarantined)

        // Segunda pasada: el flag evita re-encolar lo ya entregado (sin bucle).
        val second = repo.uploadPending(client, target, "tok", "dev")
        assertEquals(0, second.delivered)
        assertEquals(1, bodies.size)
    }
}
