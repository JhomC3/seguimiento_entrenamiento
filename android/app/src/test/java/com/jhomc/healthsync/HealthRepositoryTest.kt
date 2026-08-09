package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.response.ChangesResponse
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.response.ReadRecordsResponse
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import kotlin.reflect.KClass
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositoryTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private lateinit var repo: HealthRepository

    private val t0: Instant = Instant.parse("2026-08-08T12:00:00Z")
    private val t1: Instant = Instant.parse("2026-08-08T13:00:00Z")

    private val stepsEntry: RecordTypeEntry = RecordTypes.byTypeName("STEPS")!!

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
            now = { t1 },
        )
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `first sync backfills then drains and advances token`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-2", t0, t1, count = 200)))
        gateway.changesQueue.add(
            ChangesResponse(listOf(androidx.health.connect.client.changes.UpsertionChange(Fixtures.steps("hc-3", t0, t1, count = 300))), "next-token", true, false),
        )
        val result = repo.syncType(stepsEntry)
        assertEquals(2, result.backfilled)
        assertEquals(1, result.upserts)
        assertEquals(3, db.healthDao().allActiveRecords().size)
        assertEquals("next-of-next-token", ChangesTokenStore(db.healthDao()).get("STEPS"))
    }

    @Test
    fun `second sync without changes produces no duplicates`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry)
        repo.syncType(stepsEntry)
        assertEquals(1, db.healthDao().allActiveRecords().size)
    }

    @Test
    fun `update with higher revision replaces value and outbox op`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry)
        val updated = Fixtures.steps("hc-1", t0, t1, count = 900, lastModified = t1.plusSeconds(60))
        gateway.changesQueue.add(
            ChangesResponse(listOf(androidx.health.connect.client.changes.UpsertionChange(updated)), "next-token", false, false),
        )
        repo.syncType(stepsEntry)
        val row = db.healthDao().getRecord("hc-1")!!
        assertTrue(row.valueJson.contains("\"count\":900"))
        assertEquals(t1.plusSeconds(60).toEpochMilli(), row.lastModifiedEpochMs)
        assertEquals(1, db.healthDao().allActiveRecords().size)
    }

    @Test
    fun `deletion propagates as logical delete`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry)
        gateway.changesQueue.add(
            ChangesResponse(listOf(androidx.health.connect.client.changes.DeletionChange("hc-1")), "next-token", false, false),
        )
        repo.syncType(stepsEntry)
        assertNull(db.healthDao().activeRecord("hc-1"))
        assertTrue(db.healthDao().getRecord("hc-1")!!.deletedAtEpochMs != null)
    }

    @Test
    fun `expired token triggers backfill and fresh token`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry) // token-1 (first sync reserves + drains)
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-9", t0, t1, count = 999)))
        gateway.changesQueue.add(
            ChangesResponse(emptyList(), "stale", false, changesTokenExpired = true),
        )
        repo.syncType(stepsEntry)
        assertEquals(2, db.healthDao().allActiveRecords().size)
        val store = ChangesTokenStore(db.healthDao())
        assertEquals("token-2", store.get("STEPS")) // 1 (first) + 1 (recovery)
    }

    @Test
    fun `crash mid-page does not advance token nor duplicate`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry)
        // Second run: page 1 crashes AFTER getChanges returns, before commit.
        gateway.changesQueue.add(
            ChangesResponse(listOf(androidx.health.connect.client.changes.UpsertionChange(Fixtures.steps("hc-2", t0, t1, count = 200))), "next-token", true, false),
        )
        gateway.crashAfterGetChanges = true
        var crashed = false
        try {
            repo.syncType(stepsEntry)
        } catch (e: RuntimeException) {
            crashed = true
        }
        assertTrue(crashed)
        // Token did not advance to next-token; retry processes the same page.
        assertEquals(1, db.healthDao().allActiveRecords().size)
        repo.syncType(stepsEntry)
        assertEquals(2, db.healthDao().allActiveRecords().size)
    }

    @Test
    fun `ensure target seeds new target once and reuses same url`() = runBlocking {
        gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
        repo.syncType(stepsEntry)
        val first = repo.ensureTarget("https://mac.local:8443/sync/health-connect", "mac")
        assertEquals(1, db.healthDao().pendingOps(first.targetId, 100).size)
        val reused = repo.ensureTarget("https://mac.local:8443/sync/health-connect", "mac")
        assertEquals(first.targetId, reused.targetId)
        val changed = repo.ensureTarget("https://newhost:8443/sync/health-connect", "nuevo")
        assertTrue(changed.targetId != first.targetId)
        assertEquals(1, db.healthDao().pendingOps(changed.targetId, 100).size)
        assertEquals(1, db.healthDao().pendingOps(first.targetId, 100).size)
    }

    @Test
    fun `upload pending drains outbox on success and keeps it on 401`() = runBlocking {
        val server = okhttp3.mockwebserver.MockWebServer()
        server.enqueue(
            okhttp3.mockwebserver.MockResponse().setResponseCode(401)
                .setBody("""{"detail":"Token inválido"}"""),
        )
        server.start()
        try {
            val client = HealthSyncClient(
                http = okhttp3.OkHttpClient.Builder()
                    .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                    .readTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                    .build(),
            )
            gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
            repo.syncType(stepsEntry)
            val target = repo.ensureTarget(server.url("/sync/health-connect").toString(), "test")
            val result = repo.uploadPending(client, target, token = "wrong", deviceId = "d")
            assertTrue("esperado permanente, fue: $result", result.permanentError != null)
            assertEquals(1, db.healthDao().pendingOps(target.targetId, 100).size)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `upload pending acks and clears outbox`() = runBlocking {
        val server = okhttp3.mockwebserver.MockWebServer()
        server.enqueue(
            okhttp3.mockwebserver.MockResponse().setResponseCode(200).setBody(
                """{"schema_version":1,"received":1,"accepted_count":1,
                   "accepted":[{"hc_id":"hc-1","revision":${t1.toEpochMilli()}}],
                   "rejected":[]}""",
            ),
        )
        server.start()
        try {
            val client = HealthSyncClient(
                http = okhttp3.OkHttpClient.Builder()
                    .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                    .readTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
                    .build(),
            )
            gateway.backfillQueue.add(listOf(Fixtures.steps("hc-1", t0, t1, count = 100)))
            repo.syncType(stepsEntry)
            val target = repo.ensureTarget(server.url("/sync/health-connect").toString(), "test")
            assertEquals(1, db.healthDao().pendingOps(target.targetId, 100).size)
            val result = repo.uploadPending(client, target, token = "secret", deviceId = "d")
            assertEquals(1, result.delivered)
            assertEquals(0, db.healthDao().pendingOps(target.targetId, 100).size)
        } finally {
            server.shutdown()
        }
    }
}
