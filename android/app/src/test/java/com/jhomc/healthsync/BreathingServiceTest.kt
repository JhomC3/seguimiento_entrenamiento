package com.jhomc.healthsync

import android.app.NotificationManager
import android.app.Application
import android.app.Notification
import android.content.Context
import android.content.Intent
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import java.time.Duration
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock
import org.robolectric.shadows.ShadowToast

/**
 * Pegamento del servicio B5 (Fase 2): arranque, fases con reloj controlado
 * (SystemClock está congelado en Robolectric: los deltas solo llegan con
 * ShadowSystemClock), pausa que no engorda la sesión, persistencia real en
 * Room al parar y Toast único con el sumidero de audio roto (el emulador
 * siempre rompe: write=false).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class BreathingServiceTest {

    private lateinit var controller: ServiceController<BreathingService>
    private val service: BreathingService get() = controller.get()
    private val fastPattern = BreathingPattern(0.5, 0.0, 0.5, 0.0)

    private fun startIntent(totalS: Int = -1, pattern: BreathingPattern = fastPattern): Intent =
        Intent().apply {
            action = BreathingService.ACTION_START
            putExtra(BreathingService.EXTRA_PATTERN, pattern.toJson().toString())
            putExtra(BreathingService.EXTRA_TOTAL_S, totalS)
            putExtra(BreathingService.EXTRA_SOUND, true)
            putExtra(BreathingService.EXTRA_VIBRATION, true)
            putExtra(BreathingService.EXTRA_TIMBRE, SoundStyle.AIRE.name)
        }

    private fun actionIntent(action: String): Intent = Intent().setAction(action)

    @Before
    fun setUp() {
        BreathingService.forceState(BreathRunState.Idle)
        controller = Robolectric.buildService(BreathingService::class.java).create()
    }

    /** Arranca la sesión en la instancia bajo test (cada test es dueño suyo). */
    private fun startSession(totalS: Int = -1) {
        service.onStartCommand(startIntent(totalS), 0, 1)
    }

    @After
    fun tearDown() {
        runCatching { service.onStartCommand(actionIntent(BreathingService.ACTION_STOP), 0, 99) }
        awaitState(3000) { it is BreathRunState.Idle || it is BreathRunState.Finished }
        controller.destroy()
        BreathingService.forceState(BreathRunState.Idle)
    }

    private fun awaitState(timeoutMs: Long = 3000, pred: (BreathRunState) -> Boolean): BreathRunState {
        val end = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < end) {
            val s = BreathingService.state.value
            if (pred(s)) return s
            Thread.sleep(20)
        }
        fail("estado no alcanzado en ${timeoutMs}ms: ${BreathingService.state.value}")
        throw AssertionError()
    }

    /** Salto de reloj que el bucle consume en su siguiente tick (50 ms). */
    private fun advance(ms: Long) {
        ShadowSystemClock.advanceBy(Duration.ofMillis(ms))
        Thread.sleep(150)
    }

    private fun idleMain() {
        shadowOf(Looper.getMainLooper()).idle()
    }

    @Test
    fun `arranca en Running con BPM 0 y Libre sin restante`() {
        startSession()
        val s = awaitState { it is BreathRunState.Running } as BreathRunState.Running
        assertEquals(BreathPhase.INHALE, s.phase)
        assertEquals(0.0, s.avgBpm, 0.0)
        assertEquals(0L, s.elapsedMs)
        assertEquals(-1L, s.totalRemainingMs)
        assertTrue(s.cycle >= 1)
    }

    @Test
    fun `audio roto avisa una sola vez con Toast`() {
        // Fábrica rota: el estático no cargó (sin audio; sigue la guía visual).
        service.playerFactory = { StaticPhasePlayer(listOf(null)) }
        startSession()
        awaitState { it is BreathRunState.Running }
        val end = System.currentTimeMillis() + 3000
        while (System.currentTimeMillis() < end && ShadowToast.shownToastCount() == 0) {
            idleMain()
            Thread.sleep(30)
        }
        assertEquals(1, ShadowToast.shownToastCount())
        // Más ticks con broken ya no repiten el aviso (audioWarned).
        repeat(5) { advance(100) }
        idleMain()
        assertEquals(1, ShadowToast.shownToastCount())
    }

    @Test
    fun `fases con reloj REST anuncia la siguiente y BPM usa la formula del servidor`() {
        startSession()
        awaitState { it is BreathRunState.Running }
        advance(300) // INHALE 250 ms + 50 ms de REST (cierre adaptativo 250)
        val rest = awaitState(3000) {
            it is BreathRunState.Running && it.phase == BreathPhase.REST
        } as BreathRunState.Running
        assertEquals(BreathPhase.EXHALE, rest.nextPhase)
        advance(650) // activo total = 950 ms → simulate(1 s) = (1 ciclo, 60.0)
        val run = awaitState(3000) {
            it is BreathRunState.Running && it.elapsedMs == 950L
        } as BreathRunState.Running
        assertEquals(60.0, run.avgBpm, 0.0)
        assertEquals(BreathPhase.REST, run.phase)
    }

    @Test
    fun `pausa congela el reloj y reanudar no engorda la sesion`() {
        startSession()
        awaitState { it is BreathRunState.Running }
        advance(300)
        service.onStartCommand(actionIntent(BreathingService.ACTION_TOGGLE), 0, 2)
        val paused = awaitState { it is BreathRunState.Paused } as BreathRunState.Paused
        advance(500) // el reloj corre, pero el servicio está cancelado
        val still = BreathingService.state.value as BreathRunState.Paused
        assertEquals(paused.phaseRemainingMs, still.phaseRemainingMs)
        assertEquals(paused.fraction, still.fraction, 0.0f)
        service.onStartCommand(actionIntent(BreathingService.ACTION_TOGGLE), 0, 3)
        awaitState { it is BreathRunState.Running }
        // Los 500 ms de pausa no suman: el activo sigue donde estaba.
        advance(100)
        val run = awaitState { it is BreathRunState.Running && it.elapsedMs > 0 } as BreathRunState.Running
        assertTrue(run.elapsedMs <= 400L)
    }

    @Test
    fun `stop antes de 5 s vuelve a Idle sin persistir`() {
        startSession()
        awaitState { it is BreathRunState.Running }
        advance(600)
        val dao = HealthDatabaseBuilder.get(service).breathingDao()
        val before = runBlocking { dao.pendingCount() }
        service.onStartCommand(actionIntent(BreathingService.ACTION_STOP), 0, 4)
        awaitState { it is BreathRunState.Idle }
        assertEquals(before, runBlocking { dao.pendingCount() })
    }

    @Test
    fun `stop con 8 s activos persiste en Room y termina con Finished`() {
        startSession(totalS = 600)
        awaitState { it is BreathRunState.Running }
        repeat(4) { advance(2000) } // 8000 ms activos (coerce máx. 2000 por tick)
        // La DB de la app se comparte entre tests de la misma JVM: base relativa.
        val dao = HealthDatabaseBuilder.get(service).breathingDao()
        val base = runBlocking { dao.pendingCount() }
        service.onStartCommand(actionIntent(BreathingService.ACTION_STOP), 0, 5)
        val fin = awaitState(5000) { it is BreathRunState.Finished } as BreathRunState.Finished
        // simulate(8 s) con ciclo de 1 s: 8 ciclos, RPM 60.0, 0.1 min.
        assertEquals(8, fin.ciclos)
        assertEquals(0.1, fin.minutos, 0.0)
        assertTrue(fin.resumen.startsWith("0.5/0"))
        runBlocking {
            assertEquals(base + 1, dao.pendingCount())
            val row = dao.sessionById(fin.clientSessionId)
            assertNotNull(row)
            assertEquals(false, row!!.delivered)
            assertEquals(8, row.ciclos)
            assertEquals(60.0, row.bpm, 0.0)
        }
    }

    @Test
    fun `stop con 8 s y ciclo de 12 s no guarda (ni un ciclo) y avisa`() {
        val long = BreathingPattern(6.0, 0.0, 6.0, 0.0)
        service.onStartCommand(startIntent(-1, long), 0, 6)
        awaitState { it is BreathRunState.Running }
        repeat(4) { advance(2000) } // 8000 ms activos (< 1 ciclo de 12 s)
        val dao = HealthDatabaseBuilder.get(service).breathingDao()
        val base = runBlocking { dao.pendingCount() }
        service.onStartCommand(actionIntent(BreathingService.ACTION_STOP), 0, 7)
        awaitState { it is BreathRunState.Idle }
        // Misma regla que el servidor: lo condenado no se encola.
        assertEquals(base, runBlocking { dao.pendingCount() })
        idleMain()
        assertTrue((ShadowToast.getTextOfLatestToast() ?: "").startsWith("Muy corta"))
    }

    @Test
    fun `companions emiten intents y la notificacion lleva las acciones`() {
        BreathingService.forceState(BreathRunState.Idle)
        val app = ApplicationProvider.getApplicationContext<Application>()
        BreathingService.start(app, fastPattern, 300, sound = true, vibration = true, timbre = SoundStyle.AIRE)
        val started = shadowOf(app).getNextStartedService()
        assertNotNull(started)
        assertEquals(BreathingService.ACTION_START, started.action)
        assertEquals(300, started.getIntExtra(BreathingService.EXTRA_TOTAL_S, -1))
        assertTrue(BreathingService.state.value is BreathRunState.Running)
        BreathingService.toggle(app)
        assertEquals(BreathingService.ACTION_TOGGLE, shadowOf(app).getNextStartedService().action)
        BreathingService.stop(app)
        assertEquals(BreathingService.ACTION_STOP, shadowOf(app).getNextStartedService().action)
        // consumeFinished solo limpia Finished.
        BreathingService.forceState(BreathRunState.Finished("id", 1, 0.1, "p"))
        BreathingService.consumeFinished()
        assertTrue(BreathingService.state.value is BreathRunState.Idle)
        BreathingService.forceState(BreathRunState.Idle)
        BreathingService.consumeFinished()
        assertTrue(BreathingService.state.value is BreathRunState.Idle)
    }

    @Test
    fun `notificacion construida con titulo y acciones de pausa y fin`() {
        val app = ApplicationProvider.getApplicationContext<Context>()
        BreathingService.createChannel(app)
        val nm = app.getSystemService(NotificationManager::class.java)
        assertNotNull(nm.getNotificationChannel(BreathingService.CHANNEL_ID))
        val n = BreathingService.buildNotification(app, "En pausa: Exhale", paused = true)
        assertEquals("Respiración", n.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        assertEquals("En pausa: Exhale", n.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
        assertEquals(2, n.actions.size)
    }
}
