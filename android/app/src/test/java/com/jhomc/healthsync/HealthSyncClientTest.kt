package com.jhomc.healthsync

import com.jhomc.healthsync.data.HealthOutboxEntity
import com.jhomc.healthsync.data.HealthRecordEntity
import java.util.concurrent.TimeUnit
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthSyncClientTest {

    private fun record(hcId: String, revision: Long, count: Int) = HealthRecordEntity(
        hcId = hcId,
        recordType = "STEPS",
        startEpochMs = 1_000_000,
        endEpochMs = 1_000_100,
        lastModifiedEpochMs = revision,
        dataOriginPackage = "com.samsung.health",
        timeZoneOffsetMinutes = -300,
        payloadSchemaVersion = 1,
        valueJson = "{\"count\":$count}",
        sourceUpdatedAtEpochMs = 1L,
    )

    private fun upsertOp(hcId: String, revision: Long) = HealthOutboxEntity(
        targetId = 1, hcId = hcId, operation = "UPSERT", revision = revision,
        attemptCount = 0, createdAtEpochMs = 1L,
    )

    private fun deleteOp(hcId: String, revision: Long) = HealthOutboxEntity(
        targetId = 1, hcId = hcId, operation = "DELETE", revision = revision,
        attemptCount = 0, createdAtEpochMs = 1L,
    )

    private val client = HealthSyncClient()

    @Test
    fun `http url is rejected`() {
        assertTrue(client.validateTargetUrl("http://192.168.1.5:8000/sync/health-connect").isFailure)
    }

    @Test
    fun `https url is accepted`() {
        assertTrue(client.validateTargetUrl("https://host.local:8443/sync/health-connect").isSuccess)
    }

    @Test
    fun `url without scheme is rejected`() {
        assertTrue(client.validateTargetUrl("host.local:8443").isFailure)
    }

    @Test
    fun `batch payload is bounded and complete`() {
        val records = mapOf("a" to record("a", 100, 8123), "b" to record("b", 200, 999))
        val payload = client.buildBatchPayload(
            deviceId = "android-test",
            ops = listOf(upsertOp("a", 100), deleteOp("b", 250)),
            records = records,
        )
        assertEquals(1, payload.getInt("schema_version"))
        assertEquals("android-test", payload.getString("device_id"))
        val ops = payload.getJSONArray("operations")
        assertEquals(2, ops.length())
        val upsert = ops.getJSONObject(0)
        assertEquals("UPSERT", upsert.getString("op"))
        assertEquals("STEPS", upsert.getString("record_type"))
        assertEquals(8123L, upsert.getJSONObject("value").getLong("count"))
        val delete = ops.getJSONObject(1)
        assertEquals("DELETE", delete.getString("op"))
        assertTrue(!delete.has("value"))
    }

    @Test
    fun `post to server parses per-op acks`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"received":2,"accepted_count":2,
                   "accepted":[{"hc_id":"a","revision":100},{"hc_id":"b","revision":200}],
                   "rejected":[]}""".trimIndent(),
            ),
        )
        server.start()
        try {
            val outcome = client.postBatch(
                server.url("/sync/health-connect").toString(),
                token = "secret",
                payload = JSONObject("{}"),
            )
            assertTrue(outcome is UploadOutcome.Accepted)
            val accepted = outcome as UploadOutcome.Accepted
            assertEquals(2, accepted.acked.size)
            assertEquals(ServerAck("a", 100), accepted.acked[0])
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `permanent http status maps to permanent error`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Token inválido"}"""))
        server.start()
        try {
            val outcome = client.postBatch(
                server.url("/sync/health-connect").toString(),
                token = "wrong",
                payload = JSONObject("{}"),
            )
            assertTrue(outcome is UploadOutcome.PermanentError)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `400 conserva el detail del servidor para aislar el veneno`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"detail":"Operación 3: record_type desconocido 'SPEED'"}"""),
        )
        server.start()
        try {
            val outcome = client.postBatch(
                server.url("/sync/health-connect").toString(),
                token = "secret",
                payload = JSONObject("{}"),
            )
            assertTrue(outcome is UploadOutcome.PermanentError)
            val detail = (outcome as UploadOutcome.PermanentError).detail
            assertTrue("el detail debe identificar la op, fue: $detail", detail.contains("Operación 3"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `preflight detecta ops invalidas antes del post`() {
        val okRecord = record("a", 100, 10)
        val badType = okRecord.copy(hcId = "b", recordType = "SPEED")
        val badEnd = okRecord.copy(hcId = "c", startEpochMs = 2_000, endEpochMs = 1_000)
        val badValue = okRecord.copy(hcId = "d", valueJson = "no-json")
        val records = mapOf("a" to okRecord, "b" to badType, "c" to badEnd, "d" to badValue)
        val ops = listOf(
            upsertOp("a", 100),
            upsertOp("b", 100),
            upsertOp("c", 100),
            upsertOp("d", 100),
            HealthOutboxEntity(1, "e", "NOPE", 100, 0, 1L),
        )
        val bad = client.findInvalidOperations(ops, records, setOf("STEPS"))
        assertEquals(setOf(1, 2, 3, 4), bad.keys)
        assertTrue(bad[1]!!.contains("allow-list"))
    }

    @Test
    fun `server 5xx maps to transient error`() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(503))
        server.start()
        try {
            val outcome = client.postBatch(
                server.url("/sync/health-connect").toString(),
                token = "secret",
                payload = JSONObject("{}"),
            )
            assertTrue(outcome is UploadOutcome.TransientError)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `untrusted tls certificate maps to transient error`() {
        val server = MockWebServer()
        val sslContext = javax.net.ssl.SSLContext.getInstance("TLS")
        sslContext.init(null, null, null)
        server.useHttps(sslContext.socketFactory, false) // self-signed
        server.enqueue(MockResponse().setResponseCode(200))
        server.start()
        try {
            val outcome = client.postBatch(
                server.url("/sync/health-connect").toString(),
                token = "secret",
                payload = JSONObject("{}"),
            )
            assertTrue("esperaba error transitorio, fue: $outcome", outcome is UploadOutcome.TransientError)
        } finally {
            server.shutdown()
        }
    }
}
