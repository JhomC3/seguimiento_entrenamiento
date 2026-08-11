package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositorySchedulingTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private lateinit var repo: HealthRepository
    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        gateway = FakeHealthConnectGateway()
        gateway.granted = RecordTypes.all.map { it.permission }.toSet() // todos autorizados
        repo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
        )
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun `a run with 38 authorized types calls only the budgeted ones`() = runBlocking {
        repo.syncAuthorizedTypes()
        assertTrue("criterio 1: 1 tipo por ejecución", gateway.tokenLog.size == 1)
        assertTrue(gateway.readLog.size <= 1) // solo el backfill del tipo elegido
    }

    @Test
    fun `five runs rotate across distinct types with persisted cursor`() = runBlocking {
        val chosen = mutableSetOf<String>()
        repeat(5) {
            gateway.tokenLog.clear()
            repo.syncAuthorizedTypes()
            chosen += gateway.tokenLog
        }
        assertEquals(5, chosen.size) // criterio 2: tipos distintos en 5 ejecuciones
    }

    @Test
    fun `nothing due means zero health connect calls`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("STEPS")!!.permission)
        repo.syncAuthorizedTypes() // primer run: STEPS sincronizado, next_due_at futuro
        // READ_STEPS cubre también STEPS_CADENCE en el SDK 1.1.0 (permiso compartido):
        // segundo run para su primer sync, luego nada queda vencido.
        repo.syncAuthorizedTypes()
        gateway.tokenLog.clear(); gateway.readLog.clear(); gateway.changesLog.clear()
        repo.syncAuthorizedTypes()
        // criterio 4: sin vencidos → cero llamadas (ni backfill ni token)
        assertEquals(0, gateway.tokenLog.size)
        assertEquals(0, gateway.readLog.size)
        assertEquals(0, gateway.changesLog.size)
    }
}
