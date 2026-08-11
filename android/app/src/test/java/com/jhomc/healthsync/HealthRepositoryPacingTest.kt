package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositoryPacingTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        gateway = FakeHealthConnectGateway()
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun `pacer fires between pages but not after the last one`() = runBlocking {
        // Desviación del plan: Fixtures.sleepSession en vez de Fixtures.steps —
        // READ_STEPS es un permiso compartido (STEPS + STEPS_CADENCE) y
        // syncType exigiría gestionar dos tipos; SLEEP_SESSION tiene permiso
        // único, un solo candidato → determinista.
        gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
        gateway.pageStore["pt-1"] = listOf(Fixtures.sleepSession("hc-2", t, t.plusSeconds(3600)))
        gateway.pageStore["pt-2"] = listOf(Fixtures.sleepSession("hc-3", t, t.plusSeconds(3600)))
        var paces = 0
        val repo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = { paces++ },
        )
        repo.syncType(RecordTypes.byTypeName("SLEEP_SESSION")!!)
        // 3 páginas (null, pt-1, pt-2) → 2 pausas entre ellas.
        assertTrue("2 pausas entre 3 páginas, hubo $paces", paces == 2)
    }
}
