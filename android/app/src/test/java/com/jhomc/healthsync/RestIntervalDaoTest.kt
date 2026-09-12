package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.RestIntervalEntity
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Fase 1: start abre, pause cierra con end > start, reanudar abre otro,
 * huérfanos se abandonan al arrancar.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RestIntervalDaoTest {

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
    fun `start abre y pause cierra con end mayor que start`() = runBlocking {
        val dao = db.restDao()
        val id = dao.insert(
            RestIntervalEntity(
                fecha = "2026-09-12", ejercicio = "Press", clientSetUuid = "u1",
                setOrdenAparente = 1, startWallMs = 1_000L, startElapsedMs = 10_000L,
                createdAtEpochMs = 1_000L,
            ),
        )
        assertTrue(id > 0)
        assertEquals(1, dao.openAll().size)
        dao.close(id, 2_000L, 15_000L)
        assertTrue(dao.openAll().isEmpty())
        val row = dao.get(id)!!
        assertEquals("CERRADO", row.estado)
        assertEquals(2_000L, row.endWallMs)
        assertTrue((row.endElapsedMs ?: 0L) > row.startElapsedMs)
    }

    @Test
    fun `reanudar abre otro intervalo del mismo set`() = runBlocking {
        val dao = db.restDao()
        val first = dao.insert(
            RestIntervalEntity(
                fecha = "2026-09-12", ejercicio = "Press", clientSetUuid = "u1",
                setOrdenAparente = 1, startWallMs = 1_000L, startElapsedMs = 10_000L,
                createdAtEpochMs = 1_000L,
            ),
        )
        dao.close(first, 2_000L, 12_000L)
        dao.insert(
            RestIntervalEntity(
                fecha = "2026-09-12", ejercicio = "Press", clientSetUuid = "u1",
                setOrdenAparente = 1, startWallMs = 3_000L, startElapsedMs = 20_000L,
                createdAtEpochMs = 3_000L,
            ),
        )
        assertEquals(2, dao.forSet("u1").size)
        assertEquals(2, dao.forFecha("2026-09-12").size)
    }

    @Test
    fun `abandonAllOpen marca huerfanos sin reanudar`() = runBlocking {
        val dao = db.restDao()
        dao.insert(
            RestIntervalEntity(
                fecha = "2026-09-11", ejercicio = "Remo", clientSetUuid = "old",
                setOrdenAparente = 2, startWallMs = 1_000L, startElapsedMs = 5_000L,
                createdAtEpochMs = 1_000L,
            ),
        )
        dao.abandonAllOpen(9_000L, 8_000L)
        assertTrue(dao.openAll().isEmpty())
        val row = dao.forSet("old").single()
        assertEquals("ABANDONADO", row.estado)
        assertEquals(9_000L, row.endWallMs)
    }
}
