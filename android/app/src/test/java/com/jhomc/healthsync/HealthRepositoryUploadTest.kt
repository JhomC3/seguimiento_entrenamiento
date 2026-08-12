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
        return ResponseBody.create(
            null,
            """{"schema_version":1,"received":${ops.length()},"accepted_count":${ops.length()},
               "accepted":$accepted,"rejected":[]}""".trimIndent(),
        )
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
}
