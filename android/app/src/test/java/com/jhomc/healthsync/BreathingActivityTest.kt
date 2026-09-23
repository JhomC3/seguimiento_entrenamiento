package com.jhomc.healthsync

import android.app.AlertDialog
import android.content.Context
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.NumberPicker
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowDialog
import org.robolectric.shadows.ShadowToast

/**
 * Pegamento de la pestaña Respirar (Fase 2): chips, editor deslizante con
 * mínimo 0.5 s, diálogo de duración con piso de 30 s, círculo (tap/hold),
 * revisión Guardar/Descartar, planillas y ajustes. El estado del servicio se
 * fuerza con forceState y la UI se sincroniza idling el main looper.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@OptIn(androidx.health.connect.client.feature.ExperimentalMindfulnessSessionApi::class)
class BreathingActivityTest {

    private lateinit var controller: ActivityController<BreathingActivity>
    private val activity: BreathingActivity get() = controller.get()
    private val app: Context get() = ApplicationProvider.getApplicationContext()

    @Before
    fun setUp() {
        BreathingService.forceState(BreathRunState.Idle)
        clearPrefs()
    }

    @After
    fun tearDown() {
        if (::controller.isInitialized) controller.destroy()
        BreathingService.forceState(BreathRunState.Idle)
        clearPrefs()
    }

    private fun prefs() = app.getSharedPreferences(BreathingActivity.PREFS, Context.MODE_PRIVATE)

    private fun clearPrefs() {
        prefs().edit().clear().commit()
    }

    private fun launch() {
        controller = Robolectric.buildActivity(BreathingActivity::class.java).setup()
        idleMain()
    }

    private fun idleMain() {
        shadowOf(android.os.Looper.getMainLooper()).idle()
    }

    private fun walk(v: View, out: MutableList<View>) {
        out += v
        if (v is ViewGroup) for (i in 0 until v.childCount) walk(v.getChildAt(i), out)
    }

    private fun views(): List<View> {
        val out = mutableListOf<View>()
        walk(activity.window.decorView, out)
        return out
    }

    private inline fun <reified T : View> ofType(): List<T> = views().filterIsInstance<T>()

    private fun button(prefix: String): Button =
        ofType<Button>().first { it.text.startsWith(prefix) }

    private fun root(): ViewGroup {
        val scroll = ofType<ScrollView>().first()
        return scroll.getChildAt(0) as ViewGroup
    }

    /** stats=0, círculo=1, etiqueta=2, revisión=3, configuración=4. */
    private fun statsText(): String = (root().getChildAt(0) as TextView).text.toString()
    private fun circle(): BreathCircleView = root().getChildAt(1) as BreathCircleView
    private fun phaseLabel(): TextView = root().getChildAt(2) as TextView
    private fun reviewCard(): View = root().getChildAt(3)
    private fun configContainer(): View = root().getChildAt(4)

    private fun latestDialog(): AlertDialog {
        val d = ShadowDialog.getLatestDialog()
        assertNotNull("no hay diálogo abierto", d)
        return d as AlertDialog
    }

    private fun dialogViews(d: AlertDialog): List<View> {
        val out = mutableListOf<View>()
        walk(d.window!!.decorView, out)
        return out
    }

    /**
     * Baja el picker N pasos: el valor lo fija `setValue` (programático sí lo
     * acepta) y el aviso lo dispara el listener como haría la rueda —
     * `setValue` a secas nunca lo notifica.
     */
    private fun scrollDown(picker: NumberPicker, steps: Int) {
        val old = picker.value
        val target = old - steps
        picker.value = target
        val listener = checkNotNull(shadowOf(picker).onValueChangeListener) {
            "el picker no tiene OnValueChangedListener"
        }
        listener.onValueChange(picker, old, target)
    }

    private fun awaitUi(timeoutMs: Long = 3000, pred: () -> Boolean) {
        val end = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < end) {
            idleMain()
            if (pred()) return
            Thread.sleep(20)
        }
        fail("UI no alcanzada en ${timeoutMs}ms")
    }

    private fun awaitToast(expectedPrefix: String, timeoutMs: Long = 3000): String {
        val end = System.currentTimeMillis() + timeoutMs
        var last: String? = null
        while (System.currentTimeMillis() < end) {
            idleMain()
            last = ShadowToast.getTextOfLatestToast()
            if (last != null && last.startsWith(expectedPrefix)) return last
            Thread.sleep(20)
        }
        fail("toast «$expectedPrefix» no llegó (último: $last)")
        throw AssertionError()
    }

    private fun startedAction(): String? =
        shadowOf(app as android.app.Application).getNextStartedService()?.action

    // --- Chips y duración ----------------------------------------------------------

    @Test
    fun `chips iniciales muestran HOLD OFF y TIMER 10m`() {
        launch()
        assertEquals("INHALE\n4s", button("INHALE").text.toString())
        assertEquals("EXHALE\n6s", button("EXHALE").text.toString())
        assertEquals(2, ofType<Button>().count { it.text.startsWith("HOLD\nOFF") })
        assertEquals("TIMER\n10m 0s", button("TIMER").text.toString())
        assertEquals("--:-- · 0 resp · -- rpm", statsText())
        assertNotNull(ofType<Button>().firstOrNull { it.text.toString() == "＋" })
        assertEquals(View.VISIBLE, configContainer().visibility)
    }

    @Test
    fun `dialogo duracion rechaza menos de 30 s sin cerrar`() {
        launch()
        button("TIMER").performClick()
        idleMain()
        val dlg = latestDialog()
        assertTrue(dlg.isShowing)
        val min = dialogViews(dlg).filterIsInstance<NumberPicker>()
            .first { it.contentDescription == "Duración: minutos" }
        val sec = dialogViews(dlg).filterIsInstance<NumberPicker>()
            .first { it.contentDescription == "Duración: segundos" }
        min.value = 0
        sec.value = 10
        dlg.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        idleMain()
        assertTrue("el diálogo debe seguir abierto", dlg.isShowing)
        val error = dialogViews(dlg).filterIsInstance<TextView>().first { !it.text.isNullOrEmpty() && it.text.contains("Mínimo") }
        assertEquals("Mínimo 30 s (o Libre).", error.text.toString())
        min.value = 1
        sec.value = 0
        dlg.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        idleMain()
        assertFalse(dlg.isShowing)
        assertEquals("TIMER\n1m 0s", button("TIMER").text.toString())
        // Libre: sin temporizador.
        button("TIMER").performClick()
        idleMain()
        val dlg2 = latestDialog()
        dlg2.getButton(AlertDialog.BUTTON_NEUTRAL).performClick()
        idleMain()
        assertEquals("TIMER\nLibre", button("TIMER").text.toString())
    }

    @Test
    fun `chip de fase edita con décima mínima y cancelar no cambia`() {
        launch()
        val inhale = button("INHALE")
        inhale.performClick()
        idleMain()
        val dlg = latestDialog()
        val pickers = dialogViews(dlg).filterIsInstance<NumberPicker>()
        val sec = pickers.first { it.contentDescription == "INHALE: segundos" }
        val tenth = pickers.first { it.contentDescription == "INHALE: décimas" }
        scrollDown(sec, 4) // de 4 s a 0 s: el listener sube la décima mínima a 5
        idleMain()
        assertEquals(5, tenth.minValue)
        tenth.value = 5
        dlg.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()
        idleMain()
        assertEquals("INHALE\n4s", inhale.text.toString())
        inhale.performClick()
        idleMain()
        val dlg2 = latestDialog()
        val pickers2 = dialogViews(dlg2).filterIsInstance<NumberPicker>()
        scrollDown(pickers2.first { it.contentDescription == "INHALE: segundos" }, 4)
        idleMain()
        pickers2.first { it.contentDescription == "INHALE: décimas" }.value = 5
        dlg2.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        idleMain()
        assertEquals("INHALE\n0.5s", inhale.text.toString())
    }

    // --- Círculo -------------------------------------------------------------------

    @Test
    fun `patron invalido avisa con Toast y no arranca`() {
        prefs().edit().putString(
            BreathingActivity.KEY_PATTERN,
            JSONObject().put("inhale_s", 0.1).put("exhale_s", 6.0).toString(),
        ).commit()
        launch()
        circle().performClick()
        awaitToast("Revisa los tiempos")
        assertNull(startedAction())
    }

    @Test
    fun `con sesion en curso el circle alterna y el hold detiene`() {
        launch()
        BreathingService.forceState(
            BreathRunState.Running(BreathPhase.INHALE, 0f, 3500, 5000, 1000, 3, 6.0, BreathPhase.EXHALE),
        )
        awaitUi { configContainer().visibility == View.GONE }
        assertEquals("00:05 · 3 resp · 6.0 rpm", statsText())
        assertEquals(BreathPhase.INHALE.label, phaseLabel().text.toString())
        // En REST el círculo se congela y la etiqueta anuncia la siguiente.
        BreathingService.forceState(
            BreathRunState.Running(BreathPhase.REST, 1f, 200, 5200, 1200, 3, 6.0, BreathPhase.EXHALE),
        )
        awaitUi { phaseLabel().text.toString() == BreathPhase.EXHALE.label }
        // En REST el círculo se congela en la fase anterior (0.4.6); la
        // etiqueta anuncia la siguiente.
        assertEquals(BreathPhase.INHALE, circle().phase)
        circle().performClick()
        // getNextStartedService consume la cola (lo probamos en ServiceTest).
        assertEquals(BreathingService.ACTION_TOGGLE, startedAction())
        BreathingService.forceState(BreathRunState.Paused(BreathPhase.EXHALE, 0.4f, 2000, 5200, 3))
        awaitUi { phaseLabel().text.toString() == "Paused" }
        assertTrue(circle().contentDescription.contains("pausa"))
        circle().onHoldReset?.invoke()
        assertEquals(BreathingService.ACTION_STOP, startedAction())
        BreathingService.forceState(BreathRunState.Idle)
        awaitUi { configContainer().visibility == View.VISIBLE && reviewCard().visibility == View.GONE }
        assertEquals("--:-- · 0 resp · -- rpm", statsText())
    }

    // --- Revisión: guardar / descartar ---------------------------------------------

    @Test
    fun `finalizar muestra revision y guardar avisa sin destino una sola vez`() {
        launch()
        BreathingService.forceState(BreathRunState.Finished("uuid-fase2", 8, 0.1, "0.5/0/0.5/0"))
        awaitUi { reviewCard().visibility == View.VISIBLE }
        val summary = reviewCard().let { it as ViewGroup }.getChildAt(0) as TextView
        assertTrue(summary.text.toString().contains("Sesión: 8 resp · 0.1 min · 0.5/0/0.5/0s"))
        button("Guardar sesión").performClick()
        awaitToast("Sin destino")
        awaitUi { BreathingService.state.value is BreathRunState.Idle }
        Thread.sleep(200)
        idleMain()
        assertEquals("Sin destino: abre el APK debug con token.", ShadowToast.getTextOfLatestToast())
        assertEquals(1, ShadowToast.shownToastCount())
        assertEquals(View.GONE, reviewCard().visibility)
    }

    @Test
    fun `descartar borra localmente sin enviar nada`() = kotlinx.coroutines.runBlocking {
        launch()
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        val repo = BreathingRepository(dao)
        val finished = FinishedBreathing(
            clientSessionId = "uuid-descarte",
            startMs = 1789282800000L,
            endMs = 1789282800000L + 120_000L,
            tzOffsetMin = 0,
            plannedS = 120,
            pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0),
            completed = true,
        )
        repo.finishSession(finished)
        val base = repo.pendingCount()
        BreathingService.forceState(BreathRunState.Finished("uuid-descarte", 12, 2.0, "4/0/6/0"))
        awaitUi { reviewCard().visibility == View.VISIBLE }
        button("Descartar").performClick()
        awaitToast("Sesión descartada")
        awaitUi { BreathingService.state.value is BreathRunState.Idle }
        assertNull(dao.sessionById("uuid-descarte"))
        // Una op por sesión (PK client_session_id, "lo último gana"): el SAVE
        // se reemplaza por el DELETE → total neto sin cambios. Nada salió del
        // móvil (sin servidor aquí).
        assertEquals(base, dao.pendingCount())
        assertEquals(
            "DELETE",
            dao.pendingAll().first { it.clientSessionId == "uuid-descarte" }.op,
        )
        assertEquals(View.GONE, reviewCard().visibility)
    }

    // --- Espejo HC: reintento diferido -------------------------------------------------

    @Test
    fun `drainMessage distingue entregado rechazo red y http`() {
        val ok = BreathingRepository.DrainResult(1, 0, null, 0, null)
        assertEquals("Sesión guardada.", BreathingActivity.drainMessage(ok))
        val empty = BreathingRepository.DrainResult(0, 0, null, 0, null)
        assertEquals("Sesión guardada.", BreathingActivity.drainMessage(empty))
        val refused = BreathingRepository.DrainResult(0, 0, null, 1, 400)
        assertEquals("Rechazada (HTTP 400).", BreathingActivity.drainMessage(refused))
        val queued = BreathingRepository.DrainResult(0, 2, null, 0, null)
        assertEquals("En cola.", BreathingActivity.drainMessage(queued))
        val gated = BreathingRepository.DrainResult(0, 1, "HTTP 403", 0, null)
        assertEquals("En cola (HTTP 403).", BreathingActivity.drainMessage(gated))
        val down = BreathingRepository.DrainResult(0, 1, "Unable to resolve host", 0, null)
        assertEquals("En cola (sin red).", BreathingActivity.drainMessage(down))
    }

    @Test
    fun `repairOrphans re-encola una vez las huerfanas`() = kotlinx.coroutines.runBlocking {
        launch()
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        val repo = BreathingRepository(dao)
        mirrorRow(repo, "uuid-huerfana", completed = true)
        // Simula el rechazo ya descartado: fila sin op en cola.
        dao.ack("uuid-huerfana")
        val base = repo.pendingCount()
        assertEquals(1, activity.repairOrphans())
        assertEquals(base + 1, repo.pendingCount())
        assertEquals("SAVE", dao.pendingAll().first { it.clientSessionId == "uuid-huerfana" }.op)
        // Segunda vez no repite (conjunto de reparadas).
        assertEquals(0, activity.repairOrphans())
        assertEquals(base + 1, repo.pendingCount())
    }

    @Test
    fun `repairOrphans salta la fila corrupta sin ciclar`() = kotlinx.coroutines.runBlocking {
        launch()
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        val repo = BreathingRepository(dao)
        mirrorRow(repo, "uuid-huerfana-2", completed = true)
        dao.ack("uuid-huerfana-2")
        // Corrompe el patrón: no se puede reconstruir el SAVE.
        val row = dao.sessionById("uuid-huerfana-2")!!
        dao.putSession(row.copy(patternJson = "{roto"))
        val base = repo.pendingCount()
        assertEquals(0, activity.repairOrphans())
        assertEquals(base, repo.pendingCount())
        assertEquals(0, activity.repairOrphans())
    }

    private fun mirrorPerm(gw: FakeHealthConnectGateway): String =
        HealthConnectManager(gw).mindfulnessWritePermission()

    private fun mirrorRow(repo: BreathingRepository, id: String, completed: Boolean) {
        kotlinx.coroutines.runBlocking {
            repo.finishSession(
                FinishedBreathing(
                    clientSessionId = id,
                    startMs = 1789282800000L,
                    endMs = 1789282800000L + 120_000L,
                    tzOffsetMin = 0,
                    plannedS = 120,
                    pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0),
                    completed = completed,
                ),
            )
        }
    }

    @Test
    fun `tryMirror publica completada con permiso`() = kotlinx.coroutines.runBlocking {
        launch()
        val fake = FakeHealthConnectGateway()
        fake.granted = setOf(mirrorPerm(fake))
        activity.mirrorGatewayFactory = { fake }
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        mirrorRow(BreathingRepository(dao), "uuid-mirror-ok", completed = true)
        val out = activity.tryMirrorSession("uuid-mirror-ok")
        assertTrue(out is MindfulnessWriter.Outcome.Published)
        assertEquals(
            listOf("uuid-mirror-ok"),
            fake.insertedMindfulness.map { it.metadata.clientRecordId },
        )
        assertNull(activity.pendingMirrorId)
    }

    @Test
    fun `sin permiso deja pendiente y la concesion tardia lo completa`() {
        kotlinx.coroutines.runBlocking {
            launch()
            val fake = FakeHealthConnectGateway()
            activity.mirrorGatewayFactory = { fake }
            val dao = HealthDatabaseBuilder.get(activity).breathingDao()
            mirrorRow(BreathingRepository(dao), "uuid-mirror-tarde", completed = true)
            val out = activity.tryMirrorSession("uuid-mirror-tarde")
            assertTrue(out is MindfulnessWriter.Outcome.Skipped)
            assertEquals("uuid-mirror-tarde", activity.pendingMirrorId)
            assertTrue(fake.insertedMindfulness.isEmpty())
            // Llega la concesión (callback del diálogo): se espeja y avisa.
            fake.granted = setOf(mirrorPerm(fake))
            activity.onMirrorPermissionGranted()
            val end = System.currentTimeMillis() + 3000
            while (System.currentTimeMillis() < end && fake.insertedMindfulness.isEmpty()) {
                idleMain()
                Thread.sleep(20)
            }
            assertEquals(1, fake.insertedMindfulness.size)
            assertNull(activity.pendingMirrorId)
            awaitToast("HC ✓")
        }
    }

    @Test
    fun `parcial no se espeja`() = kotlinx.coroutines.runBlocking {
        launch()
        val fake = FakeHealthConnectGateway()
        fake.granted = setOf(mirrorPerm(fake))
        activity.mirrorGatewayFactory = { fake }
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        mirrorRow(BreathingRepository(dao), "uuid-mirror-parcial", completed = false)
        assertNull(activity.tryMirrorSession("uuid-mirror-parcial"))
        assertTrue(fake.insertedMindfulness.isEmpty())
    }

    // --- Pantalla encendida y scroll -------------------------------------------------

    @Test
    fun `pantalla encendida solo mientras la sesion vive`() {
        launch()
        BreathingService.forceState(
            BreathRunState.Running(BreathPhase.INHALE, 0f, 3500, 5000, 1000, 3, 6.0, BreathPhase.EXHALE),
        )
        awaitUi { configContainer().visibility == View.GONE }
        val flags = activity.window.attributes.flags
        assertTrue(flags and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
        BreathingService.forceState(BreathRunState.Idle)
        awaitUi { configContainer().visibility == View.VISIBLE }
        val off = activity.window.attributes.flags
        assertEquals(0, off and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    @Test
    fun `planillas viven en fila con scroll horizontal`() {
        val many = (1..8).map {
            BreathingPlans.Plan("P$it", BreathingPattern(6.0, 0.0, 6.0, 0.0), 60, SoundStyle.AIRE)
        }
        prefs().edit().putString(BreathingActivity.KEY_PLANS, BreathingPlans.dump(many)).commit()
        launch()
        val scrolls = ofType<android.widget.HorizontalScrollView>()
        assertTrue(scrolls.isNotEmpty())
        for (i in 1..8) button("P$i").performClick()
        awaitToast("Planilla")
    }

    @Test
    fun `planillas se aplican se borran y se guardan con nombre`() {
        val plan = BreathingPlans.Plan(
            "99s", BreathingPattern(9.0, 1.0, 9.0, 1.0), 99, SoundStyle.AIRE,
        )
        prefs().edit().putString(BreathingActivity.KEY_PLANS, BreathingPlans.dump(listOf(plan))).commit()
        launch()
        button("99s").performClick()
        awaitToast("Planilla «99s».")
        assertEquals("INHALE\n9s", button("INHALE").text.toString())
        assertEquals("HOLD\n1s", ofType<Button>().first { it.text.startsWith("HOLD") }.text.toString())
        assertEquals("TIMER\n1m 39s", button("TIMER").text.toString())
        button("99s").performLongClick()
        awaitToast("Planilla «99s» borrada.")
        assertNull(ofType<Button>().firstOrNull { it.text.toString() == "99s" })
        // Guardar la planilla actual con nombre.
        button("＋").performClick()
        idleMain()
        val dlg = latestDialog()
        val input = dialogViews(dlg).filterIsInstance<EditText>().first()
        dlg.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        idleMain()
        assertTrue("el nombre vacío no cierra", dlg.isShowing)
        assertNotNull(input.error)
        input.setText("mis 21 min")
        dlg.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        awaitToast("Planilla «mis 21 min» guardada.")
        assertNotNull(ofType<Button>().firstOrNull { it.text.toString() == "mis 21 min" })
    }

    @Test
    fun `ajustes guardan sonido vibracion y timbre`() {
        launch()
        ofType<Button>().first { it.text.toString() == "⚙" }.performClick()
        idleMain()
        val dlg = latestDialog()
        val boxes = dialogViews(dlg).filterIsInstance<CheckBox>()
        val soundBox = boxes.first { it.text.toString() == "Sonido" }
        val vibrationBox = boxes.first { it.text.toString() == "Vibración" }
        assertTrue(soundBox.isChecked)
        assertFalse(vibrationBox.isChecked)
        soundBox.isChecked = false
        vibrationBox.isChecked = true
        dlg.listView.performItemClick(null, 2, 2)
        idleMain()
        dlg.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
        awaitToast("Ajustes guardados")
        val stored = prefs()
        assertFalse(stored.getBoolean(BreathingActivity.KEY_SOUND, true))
        assertTrue(stored.getBoolean(BreathingActivity.KEY_VIBRATION, false))
        assertEquals(SoundStyle.entries[2].name, stored.getString(BreathingActivity.KEY_TIMBRE, ""))
    }

    @Test
    fun `guardar planilla sin patrón valido avisa`() {
        prefs().edit().putString(
            BreathingActivity.KEY_PATTERN,
            JSONObject().put("inhale_s", 0.1).put("exhale_s", 6.0).toString(),
        ).commit()
        launch()
        button("＋").performClick()
        awaitToast("Revisa los tiempos antes de guardar.")
    }
}
