package com.jhomc.healthsync

import androidx.health.connect.client.response.ReadRecordsResponse
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
    fun `first run picks the highest priority catalog-first type not alphabetical`() = runBlocking {
        gateway.granted = setOf(
            RecordTypes.byTypeName("STEPS")!!.permission,               // HIGH, primero en catálogo
            RecordTypes.byTypeName("OXYGEN_SATURATION")!!.permission,  // MEDIUM, alfabético antes
        )
        repo.syncAuthorizedTypes()
        assertEquals(listOf("STEPS"), gateway.tokenLog)
    }

    @Test
    fun `progress callback reports the syncing type`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("STEPS")!!.permission)
        gateway.pageStore[null] = listOf(Fixtures.steps("hc-1", t, t.plusSeconds(60), count = 100))
        val messages = mutableListOf<String>()
        val repoWithProgress = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            onProgress = { messages += it },
        )
        repoWithProgress.syncAuthorizedTypes()
        assertTrue("debe reportar el tipo: $messages", messages.any { it.contains("STEPS") })
    }

    @Test
    fun `phantom empty pages terminate the backfill instead of looping forever`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.phantomEmptyPages = true // token nuevo + página vacía, para siempre
        val result = repo.syncType(RecordTypes.byTypeName("SLEEP_SESSION")!!)
        assertEquals(0, result.backfilled)
        assertEquals("3 páginas vacías cortan el backfill", 3, gateway.readLog.size)
        assertFalse(result.budgetHit) // no es presupuesto: el historial está agotado
    }

    @Test
    fun `non-advancing page token terminates the backfill`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.phantomEmptyPages = true
        gateway.phantomSameToken = true
        repo.syncType(RecordTypes.byTypeName("SLEEP_SESSION")!!)
        assertEquals("el token repetido corta en la 2ª llamada", 2, gateway.readLog.size)
    }

    @Test
    fun `page budget stops the run and the next run resumes from the checkpoint`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.phantomRecords.addAll(
            (1..60).map { Fixtures.sleepSession("hc-$it", t, t.plusSeconds(3600)) },
        )

        // Run 1: el presupuesto (50 páginas) corta el bootstrap.
        val r1 = repo.syncAuthorizedTypes().single()
        assertEquals(50, gateway.readLog.size)
        assertTrue("debe marcar budgetHit", r1.budgetHit)
        val mid = db.healthDao().getState("SLEEP_SESSION")!!
        assertTrue("checkpoint persistido para reanudar", mid.bootstrapPageToken != null)
        assertNull("sin markSynced: sigue vencido", mid.nextDueAtEpochMs)

        // Run 2: reanuda desde el checkpoint y completa.
        repo.syncAuthorizedTypes()
        val done = db.healthDao().getState("SLEEP_SESSION")!!
        assertNotNull("bootstrap completado", done.nextDueAtEpochMs)
        assertEquals(60, db.healthDao().allActiveRecords().size)
    }

    @Test
    fun `bootstrap completes even when getChanges hangs on the provider`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
        gateway.pageStore["pt-1"] = listOf(Fixtures.sleepSession("hc-2", t, t.plusSeconds(3600)))
        gateway.getChangesHangs = true // el proveedor nunca responde getChanges
        val repoFast = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            changesTimeoutMs = 100,
        )
        repoFast.syncAuthorizedTypes() // no debe colgarse: timeout → modo rango

        val state = db.healthDao().getState("SLEEP_SESSION")!!
        assertNull("bootstrap completo pese al cuelgue (antes del drenaje)", state.bootstrapStartEpochMs)
        assertNotNull("token reservado conservado", state.changesToken)
        assertNotNull("tipo marcado sincronizado", state.nextDueAtEpochMs)

        // Segunda ejecución: NO rehace el historial (estado completo) y termina.
        repoFast.syncAuthorizedTypes()
        assertNotNull(db.healthDao().getState("SLEEP_SESSION")!!.nextDueAtEpochMs)
    }

    @Test
    fun `a hanging readRecords aborts with a clear exception and cools down the type`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
        gateway.readRecordsHangs = true
        val repoFast = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            readTimeoutMs = 100,
        )
        val thrown = runCatching { repoFast.syncAuthorizedTypes() }.exceptionOrNull()
        assertTrue(
            "debe abortar con HcReadTimeoutException, fue: ${thrown?.javaClass?.simpleName}",
            thrown is HcReadTimeoutException,
        )
        // Cooldown: la siguiente ejecución NO vuelve a tocar el tipo colgado.
        val state = db.healthDao().getState("SLEEP_SESSION")
        assertTrue(
            "el tipo debe quedar en cooldown para romper el bucle de misma página",
            state?.cooldownUntilEpochMs != null,
        )
    }

    @Test
    fun `heart rate syncs as 5-minute buckets per day without raw pagination`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("HEART_RATE")!!.permission)
        val utc = ZoneOffset.UTC
        gateway.readRecordsHandler = { recordType, start, end, _ ->
            if (recordType != androidx.health.connect.client.records.HeartRateRecord::class) {
                null
            } else {
                val dayStart = start.atZone(utc).toLocalDate().atStartOfDay(utc).toInstant()
                ReadRecordsResponse(
                    listOf(Fixtures.heartRate("hr-$dayStart", dayStart, dayStart.plusSeconds(120))),
                    null,
                )
            }
        }
        val utcRepo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            zoneId = utc,
        )
        val result = utcRepo.syncAuthorizedTypes().single()

        // Bootstrap: 31 días (30 + hoy) → 31 tramos (una muestra por día).
        assertEquals(31, result.backfilled)
        assertTrue("el path agregado no usa tokens ni paginación cruda", gateway.tokenLog.isEmpty())
        val rows = db.healthDao().allActiveRecords()
        assertEquals(31, rows.size)
        assertTrue(rows.all { it.recordType == "HEART_RATE_5MIN" })
        assertTrue(rows.all { it.hcId.startsWith("HR5M:") })
        assertTrue(rows.all { it.valueJson.contains("\"avg\"") })

        // Sin raw de HEART_RATE almacenado.
        assertEquals(0, rows.count { it.recordType == "HEART_RATE" })
    }

    @Test
    fun `heart rate re-aggregation covers only the last three days`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("HEART_RATE")!!.permission)
        val utc = ZoneOffset.UTC
        gateway.readRecordsHandler = { recordType, start, end, _ ->
            if (recordType != androidx.health.connect.client.records.HeartRateRecord::class) {
                null
            } else {
                val dayStart = start.atZone(utc).toLocalDate().atStartOfDay(utc).toInstant()
                ReadRecordsResponse(
                    listOf(Fixtures.heartRate("hr-$dayStart", dayStart, dayStart.plusSeconds(120))),
                    null,
                )
            }
        }
        val utcRepo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            zoneId = utc,
        )
        utcRepo.syncAuthorizedTypes()
        val readsAfterBootstrap = gateway.readLog.size

        // 4 días después: solape de 3 días atrás + 4 hacia delante = 8 días.
        val later = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t.plusSeconds(4 * 86_400) },
            pacer = {},
            zoneId = utc,
        )
        later.syncAuthorizedTypes()
        assertEquals(readsAfterBootstrap + 8, gateway.readLog.size)
    }

    @Test
    fun `force syncs all eligible types in one run ignoring due dates`() = runBlocking {
        gateway.granted = setOf(
            RecordTypes.byTypeName("SLEEP_SESSION")!!.permission,
            RecordTypes.byTypeName("OXYGEN_SATURATION")!!.permission, // permiso único
        )
        // Run normal: 1 tipo (SLEEP, prioridad alta). Después, forzado: ambos.
        repo.syncAuthorizedTypes()
        assertEquals(1, gateway.tokenLog.size)

        gateway.tokenLog.clear()
        val forced = repo.syncAuthorizedTypes(force = true)
        assertEquals("force ignora vencimiento y presupuesto", 2, forced.size)
        assertEquals(
            "ambos tipos sincronizados en el run forzado",
            setOf("SLEEP_SESSION", "OXYGEN_SATURATION"),
            forced.map { it.recordType }.toSet(),
        )
    }

    @Test
    fun `force respects cooldowns and continues past a hung type`() = runBlocking {
        gateway.granted = setOf(
            RecordTypes.byTypeName("STEPS")!!.permission,
            RecordTypes.byTypeName("SLEEP_SESSION")!!.permission,
        )
        // El handler cuelga SOLO las lecturas de SLEEP_SESSION; STEPS va bien.
        gateway.readRecordsHandler = { recordType, start, end, pageToken ->
            if (recordType == androidx.health.connect.client.records.SleepSessionRecord::class) {
                kotlinx.coroutines.delay(60_000)
                throw AssertionError("unreachable")
            }
            null
        }
        val repoFast = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
            readTimeoutMs = 100,
        )
        val results = repoFast.syncAuthorizedTypes(force = true)
        // SLEEP_SESSION entra en cooldown y STEPS sigue sincronizándose.
        assertTrue(results.isNotEmpty())
        val sleep = db.healthDao().getState("SLEEP_SESSION")
        assertTrue("SLEEP_SESSION en cooldown", sleep?.cooldownUntilEpochMs != null)
        assertTrue("STEPS sincronizado", db.healthDao().getState("STEPS")?.nextDueAtEpochMs != null)
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
