package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.DraftRow
import com.jhomc.healthsync.data.EntrenoDraftEntity
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.canonicalRowsHash
import com.jhomc.healthsync.data.doneJson
import com.jhomc.healthsync.data.parseDone
import com.jhomc.healthsync.data.parsePayload
import com.jhomc.healthsync.data.payloadJson
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Libreta del bolsillo (v8): round-trip de borradores+done, hash canónico
 * para detectar ediciones web por debajo (ignora uuid, pilla valores).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class EntrenoDraftsDaoTest {

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

    private fun rows() = listOf(
        DraftRow("u1", "Press", "80", "8", "1", "", "", ""),
        DraftRow("u2", "Remo", "60", "10", "2", "", "", ""),
    )

    @Test
    fun `put y get por fecha con done`() = runBlocking {
        val dao = db.entrenoDraftDao()
        assertNull(dao.forFecha("2026-09-12"))
        dao.put(EntrenoDraftEntity("2026-09-12", payloadJson(rows()), doneJson(setOf("u1")), "base1", 5L))
        val got = dao.forFecha("2026-09-12")!!
        assertEquals(rows(), parsePayload(got.payloadJson))
        assertEquals(setOf("u1"), parseDone(got.doneJson))
        assertEquals("base1", got.baseHash)
        dao.clear("2026-09-12")
        assertNull(dao.forFecha("2026-09-12"))
    }

    @Test
    fun `put reemplaza por fecha`() = runBlocking {
        val dao = db.entrenoDraftDao()
        dao.put(EntrenoDraftEntity("2026-09-12", payloadJson(rows()), doneJson(emptySet()), "b1", 1L))
        dao.put(EntrenoDraftEntity("2026-09-12", payloadJson(rows()), doneJson(setOf("u1", "u2")), "b1", 2L))
        val got = dao.forFecha("2026-09-12")!!
        assertEquals(setOf("u1", "u2"), parseDone(got.doneJson))
        assertEquals(2L, got.updatedAtEpochMs)
    }

    @Test
    fun `hash ignora uuid pero pilla cambios de valor`() {
        val a = rows()
        val reordered = listOf(a[1].copy(uuid = "zz"), a[0].copy(uuid = "yy"))
        assertNotEquals(
            canonicalRowsHash(a),
            canonicalRowsHash(a.map { it.copy(kg = "82.5") }),
        )
        assertNotEquals(canonicalRowsHash(a), canonicalRowsHash(reordered))
        // Mismo contenido y orden, otros uuid: idéntico.
        val same = a.map { it.copy(uuid = "otro-${it.uuid}") }
        assertEquals(canonicalRowsHash(a), canonicalRowsHash(same))
        assertTrue(parsePayload("no-json").isEmpty())
        assertTrue(parseDone("no-json").isEmpty())
    }
}
