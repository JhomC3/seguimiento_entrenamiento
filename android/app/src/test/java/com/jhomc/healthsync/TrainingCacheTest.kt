package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.TrainingCacheDao
import com.jhomc.healthsync.data.TrainingCacheEntity
import com.jhomc.healthsync.data.TrainingCacheMetaEntity
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
 * Caché de lectura del diario: reemplazo total por día (misma semántica que
 * POST /api/v1/sesion) y limpieza al borrar.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class TrainingCacheTest {

    private lateinit var db: HealthDatabase
    private lateinit var dao: TrainingCacheDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        dao = db.trainingCacheDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `replaceDay guarda meta y filas ordenadas`() = runBlocking {
        dao.replaceDay(
            TrainingCacheMetaEntity("2026-09-07", 19, "LUNES", true, 1L),
            listOf(
                TrainingCacheEntity(fecha = "2026-09-07", setOrden = 2, ejercicio = "Remo", kg = 60.0, reps = 10.0, rir = 2.0, descansoSeg = 90.0, rm = null),
                TrainingCacheEntity(fecha = "2026-09-07", setOrden = 1, ejercicio = "Press", kg = 80.0, reps = 8.0, rir = 1.0, descansoSeg = null, rm = 103.9),
            ),
        )
        val rows = dao.rowsFor("2026-09-07")
        assertEquals(2, rows.size)
        assertEquals("Press", rows[0].ejercicio)
        assertEquals(103.9, rows[0].rm!!, 0.001)
        val meta = dao.metaFor("2026-09-07")!!
        assertEquals(19, meta.semana)
        assertTrue(meta.hasData)
    }

    @Test
    fun `replaceDay reemplaza sin duplicar`() = runBlocking {
        dao.replaceDay(
            TrainingCacheMetaEntity("2026-09-07", 19, "LUNES", true, 1L),
            listOf(TrainingCacheEntity(fecha = "2026-09-07", setOrden = 1, ejercicio = "Press", kg = 80.0, reps = 8.0, rir = 1.0, descansoSeg = null, rm = null)),
        )
        dao.replaceDay(
            TrainingCacheMetaEntity("2026-09-07", 19, "LUNES", true, 2L),
            listOf(TrainingCacheEntity(fecha = "2026-09-07", setOrden = 1, ejercicio = "Remo", kg = 60.0, reps = 10.0, rir = 2.0, descansoSeg = null, rm = null)),
        )
        val rows = dao.rowsFor("2026-09-07")
        assertEquals(1, rows.size)
        assertEquals("Remo", rows[0].ejercicio)
    }

    @Test
    fun `clearDay vacia el dia`() = runBlocking {
        dao.replaceDay(
            TrainingCacheMetaEntity("2026-09-07", 19, "LUNES", true, 1L),
            listOf(TrainingCacheEntity(fecha = "2026-09-07", setOrden = 1, ejercicio = "Press", kg = 80.0, reps = 8.0, rir = 1.0, descansoSeg = null, rm = null)),
        )
        dao.clearDay("2026-09-07", 3L)
        assertTrue(dao.rowsFor("2026-09-07").isEmpty())
        assertEquals(false, dao.metaFor("2026-09-07")!!.hasData)
    }

    @Test
    fun `dia desconocido es null`() = runBlocking {
        assertNull(dao.metaFor("2026-01-01"))
        assertTrue(dao.rowsFor("2026-01-01").isEmpty())
    }
}
