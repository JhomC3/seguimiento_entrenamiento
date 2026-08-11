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
    fun `foreground-required rejection maps to a non-retryable exception`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.failReadsWithForegroundRequired = true
        val thrown = runCatching { repo.syncAuthorizedTypes() }.exceptionOrNull()
        assertTrue(
            "debe convertirse en ForegroundRequiredException, fue: ${thrown?.javaClass?.simpleName}",
            thrown is ForegroundRequiredException,
        )
        // No entra en cooldown: el tipo sigue vencido para el próximo run en primer plano.
        val state = db.healthDao().getState("SLEEP_SESSION")
        assertTrue(state?.cooldownUntilEpochMs == null)
    }

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

    @Test
    fun `rate limit sets cooldown and the type is skipped while cooling`() = runBlocking {
        // READ_STEPS cubre STEPS + STEPS_CADENCE (permisos compartidos en el SDK
        // 1.1.0, verificado en la Task 3). Se usa SLEEP_SESSION: permiso único,
        // un solo tipo candidato → determinista.
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.failNextTokenWithRateLimit = true
        runCatching { repo.syncAuthorizedTypes() } // run 1: SLEEP_SESSION → rate limit → cooldown (re-lanza por diseño)
        // El tipo quedó en enfriamiento: una ejecución inmediata no lo toca (cero llamadas).
        gateway.tokenLog.clear(); gateway.readLog.clear(); gateway.changesLog.clear()
        repo.syncAuthorizedTypes()
        assertEquals(0, gateway.tokenLog.size) // criterio 5: una ventana de enfriamiento → cero llamadas fallidas
        assertEquals(0, gateway.readLog.size)
    }

    @Test
    fun `interrupted bootstrap resumes from the last confirmed page`() = runBlocking {
        // SLEEP_SESSION: permiso único (READ_STEPS es compartido, ver Task 3).
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
        gateway.pageStore["pt-1"] = listOf(Fixtures.sleepSession("hc-2", t, t.plusSeconds(3600)))
        gateway.pageStore["pt-2"] = listOf(Fixtures.sleepSession("hc-3", t, t.plusSeconds(3600)))

        // Primera ejecución: se corta (rate limit) tras confirmar la página 1.
        gateway.failReadsWithRateLimit = true
        runCatching { repo.syncAuthorizedTypes() }
        assertTrue(gateway.readLog.map { it.second }.contains("pt-1"))

        // Segunda ejecución: el cooldown (1 h) expira justo en t+1h → reanuda.
        val repoAfterHour = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t.plusSeconds(3600) },
            pacer = {},
        )
        repoAfterHour.syncAuthorizedTypes()

        // criterio 3: continúa en la página pendiente (pt-1), no relee desde null.
        val pageTokensSeen = gateway.readLog.map { it.second }
        assertTrue("debe reanudar con el checkpoint guardado", "pt-1" in pageTokensSeen)
        assertTrue("no vuelve a empezar desde null sin necesidad", pageTokensSeen.count { it == null } == 1)
    }

    @Test
    fun `type with recent changes is promoted and overdue again sooner`() = runBlocking {
        // SLEEP_SESSION: permiso único (READ_STEPS es compartido, ver Task 3) y
        // prioridad HIGH inicial (está en HIGH_FREQUENCY_TYPES).
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
        repo.syncAuthorizedTypes()
        val state = db.healthDao().getState("SLEEP_SESSION")!!
        assertEquals(HealthSyncPlanner.PRIORITY_HIGH, state.priority)
        assertEquals(t.toEpochMilli() + 6L * 3_600_000, state.nextDueAtEpochMs!!)
        assertEquals(0, state.emptyRuns)
    }

    @Test
    fun `six empty rounds demote a type from high to cold and stretch its interval`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission) // único tipo → determinista
        // SLEEP_SESSION parte de HIGH (2): 3 rondas vacías → MEDIUM, otras 3 → LOW (7 días).
        gateway.pageStore.clear() // sin datos
        repeat(6) {
            repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), now = { t.plusSeconds(it * 86_400L) }, pacer = {})
            repo.syncAuthorizedTypes()
        }
        val state = db.healthDao().getState("SLEEP_SESSION")!!
        assertEquals(HealthSyncPlanner.PRIORITY_LOW, state.priority)
        assertEquals(
            7L * 24 * 3_600_000,
            state.nextDueAtEpochMs!! - t.plusSeconds(5 * 86_400L).toEpochMilli(),
        )
    }
}
