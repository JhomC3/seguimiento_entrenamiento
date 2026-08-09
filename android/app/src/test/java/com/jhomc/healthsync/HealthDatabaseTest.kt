package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.HealthOutboxEntity
import com.jhomc.healthsync.data.HealthRecordEntity
import com.jhomc.healthsync.data.SyncTargetEntity
import java.time.Instant
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
class HealthDatabaseTest {

    private lateinit var db: HealthDatabase
    private lateinit var dao: com.jhomc.healthsync.data.HealthDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        dao = db.healthDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun entity(
        hcId: String,
        revision: Long = 100L,
        deleted: Boolean = false,
    ) = HealthRecordEntity(
        hcId = hcId,
        recordType = "STEPS",
        startEpochMs = 1_000_000L,
        endEpochMs = 1_000_001L,
        lastModifiedEpochMs = revision,
        dataOriginPackage = "com.samsung.health",
        timeZoneOffsetMinutes = -300,
        payloadSchemaVersion = 1,
        valueJson = "{\"count\":1}",
        deletedAtEpochMs = if (deleted) 2_000_000L else null,
        sourceUpdatedAtEpochMs = 1_000_000L,
    )

    @Test
    fun `upsert same hc_id twice keeps one row`() = runBlocking {
        dao.upsertRecord(entity("a", revision = 100))
        dao.upsertRecord(entity("a", revision = 200))
        val row = dao.getRecord("a")
        assertEquals(200L, row!!.lastModifiedEpochMs)
        assertEquals(1, dao.allActiveRecords().size)
    }

    @Test
    fun `logical delete hides record from active queries`() = runBlocking {
        dao.upsertRecord(entity("a"))
        dao.markDeleted("a", now = 2_000_000L)
        assertNull(dao.activeRecord("a"))
        assertNull(dao.getRecord("a")!!.deletedAtEpochMs?.let { null } ?: dao.activeRecord("a"))
        assertTrue(dao.getRecord("a")!!.deletedAtEpochMs != null)
        assertEquals(0, dao.allActiveRecords().size)
    }

    @Test
    fun `outbox keeps one pending op per target per record`() = runBlocking {
        val targetId = dao.upsertTarget(SyncTargetEntity(0, "https://host/", "mac", true, 1L))
        dao.upsertRecord(entity("a", revision = 100))
        dao.upsertOutbox(HealthOutboxEntity(targetId, "a", "UPSERT", 100, 0, 1L))
        dao.applyChangeAndEnqueue(entity("a", revision = 200), null, nowMs = 2L)
        val pending = dao.pendingOps(targetId, limit = 100)
        assertEquals(1, pending.size)
        assertEquals(200L, pending[0].revision)
        assertEquals("UPSERT", pending[0].operation)
    }

    @Test
    fun `delete change enqueues a DELETE op`() = runBlocking {
        val targetId = dao.upsertTarget(SyncTargetEntity(0, "https://host/", "mac", true, 1L))
        dao.applyChangeAndEnqueue(entity("a"), "a", nowMs = 2L)
        val pending = dao.pendingOps(targetId, limit = 100)
        assertEquals(1, pending.size)
        assertEquals("DELETE", pending[0].operation)
        assertNull(dao.activeRecord("a"))
    }

    @Test
    fun `seed target replays active records without touching source`() = runBlocking {
        dao.upsertRecord(entity("a"))
        dao.upsertRecord(entity("b"))
        dao.markDeleted("b", now = 2_000_000L)
        val newTarget = dao.upsertTarget(SyncTargetEntity(0, "https://new/", "nuevo", true, 1L))
        dao.seedTarget(newTarget, nowMs = 3L)
        val pending = dao.pendingOps(newTarget, limit = 100)
        assertEquals(1, pending.size)
        assertEquals("a", pending[0].hcId)
    }

    @Test
    fun `backfill page persists rows and outbox entries`() = runBlocking {
        val targetId = dao.upsertTarget(SyncTargetEntity(0, "https://host/", "mac", true, 1L))
        dao.applyBackfillPage(listOf(entity("a"), entity("b")), nowMs = 1L)
        assertEquals(2, dao.allActiveRecords().size)
        assertEquals(2, dao.pendingOps(targetId, limit = 100).size)
    }
}
