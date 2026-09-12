package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.WorkIntervalEntity
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Tramos de trabajo: abrir en Ir, cerrar en check, huérfanos se abandonan. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class WorkIntervalDaoTest {

    private lateinit var db: HealthDatabase

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `abrir y cerrar tramo`() = runBlocking {
        val dao = db.workDao()
        val id = dao.insert(
            WorkIntervalEntity(
                fecha = "2026-09-12", ejercicio = "Press", clientSetUuid = "u1",
                setOrdenAparente = 1, startWallMs = 1_000L, startElapsedMs = 10_000L,
                createdAtEpochMs = 1_000L,
            ),
        )
        assertTrue(id > 0)
        assertEquals(1, dao.openAll().size)
        dao.close(id, 2_000L, 25_000L)
        assertTrue(dao.openAll().isEmpty())
    }

    @Test
    fun `abandonAllOpen no reanuda`() = runBlocking {
        val dao = db.workDao()
        dao.insert(
            WorkIntervalEntity(
                fecha = "2026-09-11", ejercicio = "Remo", clientSetUuid = "old",
                setOrdenAparente = 2, startWallMs = 1_000L, startElapsedMs = 5_000L,
                createdAtEpochMs = 1_000L,
            ),
        )
        dao.abandonAllOpen(9_000L, 8_000L)
        assertTrue(dao.openAll().isEmpty())
    }
}
