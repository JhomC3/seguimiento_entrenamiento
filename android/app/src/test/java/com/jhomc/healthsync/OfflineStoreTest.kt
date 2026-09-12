package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.NutritionCacheEntity
import com.jhomc.healthsync.data.OfflineDao
import com.jhomc.healthsync.data.PendingWriteEntity
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

/**
 * B4: caché de nutrición (payload JSON) + cola offline (una op por
 * dominio+fecha, lo último gana).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class OfflineStoreTest {

    private lateinit var db: HealthDatabase
    private lateinit var dao: OfflineDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        dao = db.offlineDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `nutrition cache guarda y limpia por fecha`() = runBlocking {
        assertNull(dao.nutritionFor("2026-09-07"))
        dao.putNutrition(NutritionCacheEntity("2026-09-07", """{"a":1}""", 5L))
        assertEquals("""{"a":1}""", dao.nutritionFor("2026-09-07")!!.payloadJson)
        dao.clearNutrition("2026-09-07")
        assertNull(dao.nutritionFor("2026-09-07"))
    }

    @Test
    fun `outbox colapsa por dominio y fecha`() = runBlocking {
        dao.enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", """{"v":1}""", 1L))
        dao.enqueue(PendingWriteEntity("sesion", "2026-09-07", "SAVE", """{"v":2}""", 2L))
        dao.enqueue(PendingWriteEntity("diario", "2026-09-07", "SAVE", """{"v":1}""", 3L))
        assertEquals(2, dao.pendingCount())
        val all = dao.pendingAll()
        assertEquals("""{"v":2}""", all.first { it.domain == "sesion" }.payloadJson)
        dao.ack("sesion", "2026-09-07")
        assertEquals(1, dao.pendingCount())
        assertTrue(dao.pendingAll().all { it.domain == "diario" })
    }
}
