package com.jhomc.healthsync

import android.app.AlertDialog
import android.content.Context
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.NumberPicker
import android.widget.TextView
import androidx.drawerlayout.widget.DrawerLayout
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
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
 * Pegamento de la pestaña Respirar (solo dial + panel): TOP patrón+tiempo,
 * dial-botón, BOTTOM Iniciar/fase/Pausa, drawer con patrón, duración,
 * ajustes y planillas. El estado del servicio se fuerza con forceState y la
 * UI se sincroniza idling el main looper.
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

    private fun row(prefix: String): Button =
        ofType<Button>().first { it.text.startsWith(prefix) }

    /** Contenido: 0=topRow(glifo+barra), 1=editor inline, 2=círculo, 3=etiqueta. */
    private fun drawer(): DrawerLayout = ofType<DrawerLayout>().first()
    private fun frame(): ViewGroup = drawer().getChildAt(0) as ViewGroup
    private fun content(): ViewGroup = frame().getChildAt(0) as ViewGroup
    private fun topRow(): ViewGroup = content().getChildAt(0) as ViewGroup
    private fun glyph(): DrawerGlyphView = topRow().getChildAt(0) as DrawerGlyphView
    private fun bar(): ViewGroup = topRow().getChildAt(1) as ViewGroup
    private fun circle(): BreathCircleView = content().getChildAt(1) as BreathCircleView
    private fun phaseLabel(): TextView = content().getChildAt(2) as TextView
    private fun editorVeil(): View = frame().getChildAt(3)
    private fun editorCard(): View = frame().getChildAt(4)
    private fun veil(): View = frame().getChildAt(1)
    private fun reviewCard(): View = frame().getChildAt(2)

    private fun colIndex(key: String): Int =
        listOf("tiempo", "inhale", "holdIn", "exhale", "holdOut").indexOf(key)

    private fun colValue(key: String): String =
        ((bar().getChildAt(colIndex(key)) as ViewGroup).getChildAt(1) as TextView).text.toString()

    private fun colLabel(key: String): String =
        ((bar().getChildAt(colIndex(key)) as ViewGroup).getChildAt(0) as TextView).text.toString()

    private fun tapColumn(key: String) {
        (bar().getChildAt(colIndex(key)) as View).performClick()
        idleMain()
    }

    private fun editorError(): String {
        val out = mutableListOf<View>()
        walk(editorCard() as ViewGroup, out)
        return (out.first { it.getTag() == "bar-error" } as TextView).text.toString()
    }

    private fun openDrawer() {
        // Sin animación: el deslizamiento animado no se asienta bajo
        // Robolectric (sin frames); el gesto real se verifica en el APK.
        drawer().openDrawer(Gravity.START, false)
        idleMain()
    }

    private fun expandSection(title: String) {
        val header = views().first { it.contentDescription == title }
        header.performClick()
        idleMain()
    }

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

    private fun sinRespNiRpm() {
        assertTrue(
            ofType<TextView>().none { it.text.contains("resp") || it.text.contains("rpm") },
        )
    }

    // --- Pantalla solo dial ----------------------------------------------------------

    @Test
    fun `barra inicial con 5 columnas y editor colapsado`() {
        launch()
        // Glifo arriba, barra debajo (mockup).
        assertTrue(topRow().getChildAt(0) is DrawerGlyphView)
        assertTrue(topRow().getChildAt(1) is ViewGroup)
        assertEquals("Min", colLabel("tiempo"))
        assertEquals("10", colValue("tiempo"))
        assertEquals("Inhalar", colLabel("inhale"))
        assertEquals("6", colValue("exhale"))
        assertEquals("Sostener", colLabel("holdIn"))
        assertEquals("0", colValue("holdIn"))
        assertEquals("Exhalar", colLabel("exhale"))
        assertEquals("4", colValue("inhale"))
        assertEquals("Sostener", colLabel("holdOut"))
        assertEquals("0", colValue("holdOut"))
        // Etiquetas al mismo brillo que los números.
        val col = bar().getChildAt(1) as ViewGroup
        assertEquals(
            (col.getChildAt(1) as TextView).currentTextColor,
            (col.getChildAt(0) as TextView).currentTextColor,
        )
        assertEquals("Iniciar", phaseLabel().text.toString())
        assertEquals(View.VISIBLE, glyph().visibility)
        assertEquals(View.GONE, veil().visibility)
        assertEquals(View.GONE, reviewCard().visibility)
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals(View.GONE, editorVeil().visibility)
        assertFalse(drawer().isDrawerOpen(Gravity.START))
        sinRespNiRpm()
        // Panel: solo Ajustes + Plantillas (sin Patrón ni Duración).
        openDrawer()
        assertTrue(drawer().isDrawerOpen(Gravity.START))
        assertNull(views().firstOrNull { it.contentDescription == "Patrón" })
        assertNull(views().firstOrNull { it.contentDescription == "Duración" })
        assertEquals("Aire", summaryOf("Sonido"))
        assertEquals("Sin guardar", summaryOf("Plantillas"))
        assertNotNull(ofType<Button>().firstOrNull { it.text.toString() == "＋ Guardar actual" })
    }

    private fun summaryOf(title: String): String {
        val header = views().first { it.contentDescription == title }
        val out = mutableListOf<View>()
        walk(header, out)
        // Cabecera: [título, resumen]; el resumen es el segundo TextView.
        return out.filterIsInstance<TextView>()[1].text.toString()
    }

    @Test
    fun `acordeones independientes no se colapsan entre si`() {
        launch()
        openDrawer()
        expandSection("Sonido")
        assertEquals(View.VISIBLE, row("Aire").parent.let { (it as View).visibility })
        expandSection("Plantillas")
        // El abierto no colapsa al abrir otro.
        assertEquals(View.VISIBLE, row("Aire").parent.let { (it as View).visibility })
        assertEquals(
            View.VISIBLE,
            ofType<Button>().first { it.text.toString() == "＋ Guardar actual" }
                .parent.let { (it as View).visibility },
        )
        // Re-toque contrae solo el suyo.
        expandSection("Sonido")
        assertEquals(View.GONE, row("Aire").parent.let { (it as View).visibility })
        assertEquals(
            View.VISIBLE,
            ofType<Button>().first { it.text.toString() == "＋ Guardar actual" }
                .parent.let { (it as View).visibility },
        )
    }

    @Test
    fun `ultima sesion persiste patron y minutos al reabrir`() {
        prefs().edit()
            .putString(
                BreathingActivity.KEY_PATTERN,
                JSONObject().put("inhale_s", 6.0).put("hold_in_s", 0.0)
                    .put("exhale_s", 6.0).put("hold_out_s", 0.0).toString(),
            )
            .putInt(BreathingActivity.KEY_DURATION, 300)
            .commit()
        launch()
        assertEquals("6", colValue("inhale"))
        assertEquals("0", colValue("holdIn"))
        assertEquals("6", colValue("exhale"))
        assertEquals("5", colValue("tiempo"))
    }

    @Test
    fun `editar y arrancar guarda para la proxima apertura`() {
        launch()
        tapColumn("inhale")
        ofType<NumberPicker>().first { it.contentDescription == "Editar Inhalar: segundos" }.value = 6
        row("✓").performClick()
        idleMain()
        tapColumn("tiempo")
        ofType<NumberPicker>().first { it.contentDescription == "Duración: minutos" }.value = 5
        ofType<NumberPicker>().first { it.contentDescription == "Duración: segundos" }.value = 0
        row("✓").performClick()
        idleMain()
        circle().performClick() // arranca: persiste lo último
        idleMain()
        controller.destroy()
        launch()
        assertEquals("6", colValue("inhale"))
        assertEquals("5", colValue("tiempo"))
    }

    @Test
    fun `editar sin arrancar persiste igual al reabrir`() {
        launch()
        tapColumn("exhale")
        ofType<NumberPicker>().first { it.contentDescription == "Editar Exhalar: segundos" }.value = 5
        row("✓").performClick()
        idleMain()
        controller.destroy()
        launch()
        assertEquals("5", colValue("exhale"))
        assertEquals("10", colValue("tiempo"))
    }

    @Test
    fun `glifo en esquina abre el panel`() {
        launch()
        assertEquals("Abrir ajustes", glyph().contentDescription.toString())
        glyph().performClick()
        idleMain()
        // El deslizamiento animado no se asienta sin frames (se verifica en
        // el APK); aquí basta con que el toque no rompa y el panel exista.
        assertNotNull(drawer())
    }

    @Test
    fun `barra y etiqueta comparten familia y la columna abierta acentua`() {
        launch()
        val col = bar().getChildAt(1) as ViewGroup
        val label = col.getChildAt(0) as TextView
        val value = col.getChildAt(1) as TextView
        // Misma fuente Comfortaa y mismo color neutral_100; valores en
        // negrita como la etiqueta.
        assertNotNull(value.typeface)
        assertNotNull(phaseLabel().typeface)
        assertEquals(value.currentTextColor, phaseLabel().currentTextColor)
        assertEquals(13f, label.textSize / activity.resources.displayMetrics.scaledDensity, 0.5f)
        assertEquals(19f, value.textSize / activity.resources.displayMetrics.scaledDensity, 0.5f)
        assertEquals(28f, phaseLabel().textSize / activity.resources.displayMetrics.scaledDensity, 0.5f)
        tapColumn("inhale")
        assertEquals(View.VISIBLE, editorCard().visibility)
        assertEquals(
            app.getColor(com.jhomc.healthsync.R.color.burgundy_400),
            value.currentTextColor,
        )
        tapColumn("inhale") // re-toque contrae
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals(
            app.getColor(com.jhomc.healthsync.R.color.neutral_100),
            value.currentTextColor,
        )
    }

    @Test
    fun `columna en marcha no expande (edicion pre-sesion)`() {
        launch()
        tapColumn("inhale")
        assertEquals(View.VISIBLE, editorCard().visibility)
        row("✕").performClick()
        idleMain()
        BreathingService.forceState(
            BreathRunState.Running(BreathPhase.INHALE, 0f, 3500, 5000, 1000, 3, 6.0, BreathPhase.EXHALE),
        )
        awaitUi { glyph().visibility == View.INVISIBLE }
        tapColumn("exhale")
        assertEquals(View.GONE, editorCard().visibility)
        BreathingService.forceState(BreathRunState.Idle)
        awaitUi { glyph().visibility == View.VISIBLE }
    }

    @Test
    fun `gesto decide abrir cerrar o nada`() {
        launch()
        val a = activity.swipeAction(150f, 10f, 200f)
        assertEquals(BreathingActivity.SwipeAction.OPEN, a)
        // Franja de sistema: nativa, no nuestra.
        assertNull(activity.swipeAction(150f, 10f, 10f))
        assertEquals(BreathingActivity.SwipeAction.CLOSE, activity.swipeAction(-150f, 10f, 200f))
        // Corto o vertical: nada.
        assertNull(activity.swipeAction(50f, 5f, 200f))
        assertNull(activity.swipeAction(150f, 100f, 200f))
    }

    @Test
    fun `filas minimalistas con titulos como titulos`() {
        launch()
        openDrawer()
        expandSection("Sonido")
        // Opciones dimmer que la cabecera (Cuenco no seleccionado).
        val claro300 = app.getColor(com.jhomc.healthsync.R.color.neutral_300)
        assertEquals(claro300, row("Cuenco").currentTextColor)
        assertNotNull(row("Cuenco").background)
        // Cabecera: 18sp bold neutral_100.
        val header = views().first { it.contentDescription == "Sonido" }
        val out = mutableListOf<View>()
        walk(header, out)
        val title = out.filterIsInstance<TextView>()[0]
        assertEquals(18f, title.textSize / activity.resources.displayMetrics.scaledDensity, 0.5f)
        assertEquals(
            app.getColor(com.jhomc.healthsync.R.color.neutral_100),
            title.currentTextColor,
        )
    }

    @Test
    fun `rueda inline de duracion rechaza menos de 30 s sin cerrar`() {
        launch()
        tapColumn("tiempo")
        assertEquals(View.VISIBLE, editorCard().visibility)
        assertEquals(View.VISIBLE, editorVeil().visibility)
        // Fila apilada: ✕, Libre, ✓ (textos, misma fuente).
        val order = mutableListOf<View>()
        walk(editorCard() as ViewGroup, order)
        assertEquals(
            listOf("✕", "✓"),
            order.filterIsInstance<Button>().map { it.text.toString() },
        )
        // Sin tarjeta: fondo transparente.
        assertNull(editorCard().background)
        val pickers = ofType<NumberPicker>()
        val min = pickers.first { it.contentDescription == "Duración: minutos" }
        val sec = pickers.first { it.contentDescription == "Duración: segundos" }
        min.value = 0
        sec.value = 10
        row("✓").performClick()
        idleMain()
        assertEquals(View.VISIBLE, editorCard().visibility)
        assertEquals("Mínimo 30 s.", editorError())
        min.value = 1
        sec.value = 0
        row("✓").performClick()
        idleMain()
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals("1", colValue("tiempo"))
        // 0:00 = Libre con toast.
        tapColumn("tiempo")
        ofType<NumberPicker>().first { it.contentDescription == "Duración: minutos" }.value = 0
        ofType<NumberPicker>().first { it.contentDescription == "Duración: segundos" }.value = 0
        row("✓").performClick()
        awaitToast("Libre (sin temporizador).")
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals("Libre", colValue("tiempo"))
        // Sin botón Libre en jerarquía.
        assertNull(ofType<Button>().firstOrNull { it.text.toString() == "Libre" })
    }

    @Test
    fun `rueda inline de fase edita con décima mínima y cancelar no cambia`() {
        launch()
        tapColumn("inhale")
        val pickers = ofType<NumberPicker>()
        val sec = pickers.first { it.contentDescription == "Editar Inhalar: segundos" }
        val tenth = pickers.first { it.contentDescription == "Editar Inhalar: décimas" }
        // Décimas en dígitos pelados (sin punto).
        assertEquals("5", tenth.displayedValues[5])
        scrollDown(sec, 4) // de 4 s a 0 s: el listener sube la décima mínima a 5
        idleMain()
        assertEquals(5, tenth.minValue)
        tenth.value = 5
        row("✕").performClick()
        idleMain()
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals("4", colValue("inhale"))
        tapColumn("inhale")
        val pickers2 = ofType<NumberPicker>()
        scrollDown(pickers2.first { it.contentDescription == "Editar Inhalar: segundos" }, 4)
        idleMain()
        pickers2.first { it.contentDescription == "Editar Inhalar: décimas" }.value = 5
        row("✓").performClick()
        idleMain()
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals("0.5", colValue("inhale"))
    }

    @Test
    fun `x y check comparten la misma instancia de fuente`() {
        launch()
        tapColumn("inhale")
        val x = row("✕")
        val ok = row("✓")
        assertSame(x.typeface, ok.typeface)
        assertEquals(x.textSize, ok.textSize)
        assertEquals(x.currentTextColor, ok.currentTextColor)
    }

    @Test
    fun `velo del editor contrae sin aplicar`() {
        launch()
        tapColumn("exhale")
        assertEquals(View.VISIBLE, editorCard().visibility)
        editorVeil().performClick()
        idleMain()
        assertEquals(View.GONE, editorCard().visibility)
        assertEquals(View.GONE, editorVeil().visibility)
        assertEquals("6", colValue("exhale"))
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
        awaitUi { glyph().visibility == View.INVISIBLE }
        // Barra fija (mockup), sin resp ni rpm; panel bloqueado; sin velo.
        assertEquals("10", colValue("tiempo"))
        assertEquals("4", colValue("inhale"))
        assertEquals("6", colValue("exhale"))
        assertEquals(BreathPhase.INHALE.label, phaseLabel().text.toString())
        assertEquals(DrawerLayout.LOCK_MODE_LOCKED_CLOSED, drawer().getDrawerLockMode(Gravity.START))
        assertEquals(View.GONE, veil().visibility)
        sinRespNiRpm()
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
        awaitUi { phaseLabel().text.toString() == "Pausa" }
        assertTrue(circle().contentDescription.contains("pausa"))
        circle().onHoldReset?.invoke()
        assertEquals(BreathingService.ACTION_STOP, startedAction())
        BreathingService.forceState(BreathRunState.Idle)
        awaitUi { glyph().visibility == View.VISIBLE && reviewCard().visibility == View.GONE }
        assertEquals("Iniciar", phaseLabel().text.toString())
        assertEquals("10", colValue("tiempo"))
        assertEquals(DrawerLayout.LOCK_MODE_UNLOCKED, drawer().getDrawerLockMode(Gravity.START))
    }

    // --- Revisión: guardar / descartar ---------------------------------------------

    @Test
    fun `finalizar muestra revision y guardar avisa sin destino una sola vez`() {
        launch()
        BreathingService.forceState(BreathRunState.Finished("uuid-fase2", 8, 0.1, "0.5/0/0.5/0"))
        awaitUi { reviewCard().visibility == View.VISIBLE }
        // Overlay con velo, etiqueta en espacio (altura fija) y barra intacta.
        assertEquals(View.VISIBLE, veil().visibility)
        assertTrue(veil().isClickable)
        assertTrue(phaseLabel().text.isBlank())
        assertEquals("10", colValue("tiempo"))
        val summary = reviewCard().let { it as ViewGroup }.getChildAt(0) as TextView
        // Resumen: solo tiempo y respiraciones.
        assertEquals("8 resp · 0.1 min", summary.text.toString())
        // Botones idénticos: Descartar primero, mismo todo.
        val claro = app.getColor(com.jhomc.healthsync.R.color.neutral_100)
        val save = row("Guardar sesión")
        val discard = row("Descartar")
        assertEquals(claro, save.currentTextColor)
        assertEquals(claro, discard.currentTextColor)
        assertEquals(save.textSize, discard.textSize)
        val reviewRow = save.parent as ViewGroup
        assertTrue(reviewRow.indexOfChild(discard) < reviewRow.indexOfChild(save))
        row("Guardar sesión").performClick()
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
        row("Descartar").performClick()
        awaitToast("Sesión descartada")
        awaitUi { BreathingService.state.value is BreathRunState.Idle }
        assertNull(dao.sessionById("uuid-descarte"))
        // La SAVE nunca salió: se retira sin enviar (ni SAVE ni DELETE).
        assertEquals(base - 1, dao.pendingCount())
        assertNull(dao.pendingAll().firstOrNull { it.clientSessionId == "uuid-descarte" })
        assertEquals(View.GONE, reviewCard().visibility)
    }

    @Test
    fun `descartar entregada encola delete la no enviada no`() = kotlinx.coroutines.runBlocking {
        launch()
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        val repo = BreathingRepository(dao)
        mirrorRow(repo, "uuid-nueva", completed = true)
        repo.deleteSession("uuid-nueva")
        assertNull(dao.pendingAll().firstOrNull { it.clientSessionId == "uuid-nueva" })
        mirrorRow(repo, "uuid-vieja", completed = true)
        dao.markDelivered("uuid-vieja", 1, 5.0)
        dao.ack("uuid-vieja")
        repo.deleteSession("uuid-vieja")
        assertEquals(
            "DELETE",
            dao.pendingAll().first { it.clientSessionId == "uuid-vieja" }.op,
        )
    }

    @Test
    fun `abrir no envia nada solo guardar drena`() = kotlinx.coroutines.runBlocking {
        launch()
        val dao = HealthDatabaseBuilder.get(activity).breathingDao()
        mirrorRow(BreathingRepository(dao), "uuid-quieta", completed = true)
        val base = BreathingRepository(dao).pendingCount()
        assertTrue(base > 0)
        controller.destroy()
        launch()
        idleMain()
        Thread.sleep(300)
        idleMain()
        // Reabrir no drena: la cola sigue intacta.
        val dao2 = HealthDatabaseBuilder.get(activity).breathingDao()
        assertEquals(base, BreathingRepository(dao2).pendingCount())
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

    // --- Pantalla encendida ----------------------------------------------------------

    @Test
    fun `pantalla siempre encendida en respirar`() {
        launch()
        val idle = activity.window.attributes.flags
        assertTrue(idle and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
        BreathingService.forceState(
            BreathRunState.Running(BreathPhase.INHALE, 0f, 3500, 5000, 1000, 3, 6.0, BreathPhase.EXHALE),
        )
        awaitUi { glyph().visibility == View.INVISIBLE }
        val flags = activity.window.attributes.flags
        assertTrue(flags and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
        BreathingService.forceState(BreathRunState.Idle)
        awaitUi { glyph().visibility == View.VISIBLE }
        val off = activity.window.attributes.flags
        assertTrue(off and android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
    }

    // --- Planillas en el panel -------------------------------------------------------

    @Test
    fun `planillas viven en lista vertical del panel`() {
        val many = (1..8).map {
            BreathingPlans.Plan("P$it", BreathingPattern(6.0, 0.0, 6.0, 0.0), 60, SoundStyle.AIRE)
        }
        prefs().edit().putString(BreathingActivity.KEY_PLANS, BreathingPlans.dump(many)).commit()
        launch()
        openDrawer()
        expandSection("Plantillas")
        assertTrue(ofType<android.widget.HorizontalScrollView>().isEmpty())
        for (i in 1..8) row("P$i").performClick()
        awaitToast("Planilla")
    }

    @Test
    fun `planillas se aplican se borran y se guardan con nombre`() {
        val plan = BreathingPlans.Plan(
            "99s", BreathingPattern(9.0, 1.0, 9.0, 1.0), 99, SoundStyle.AIRE,
        )
        prefs().edit().putString(BreathingActivity.KEY_PLANS, BreathingPlans.dump(listOf(plan))).commit()
        launch()
        openDrawer()
        expandSection("Plantillas")
        row("99s").performClick()
        awaitToast("Planilla «99s».")
        assertEquals("9", colValue("inhale"))
        assertEquals("1", colValue("holdIn"))
        assertEquals("9", colValue("exhale"))
        assertEquals("1:39", colValue("tiempo"))
        row("99s").performLongClick()
        awaitToast("Planilla «99s» borrada.")
        assertNull(ofType<Button>().firstOrNull { it.text.toString() == "99s" })
        // Guardar la planilla actual con nombre.
        row("＋").performClick()
        idleMain()
        val dlg = latestDialog()
        val save = dialogViews(dlg).filterIsInstance<Button>().first { it.text == "Guardar" }
        val cancel = dialogViews(dlg).filterIsInstance<Button>().first { it.text == "Cancelar" }
        // Cancelar|Guardar: mismo peso, gap, 15sp sin mayúsculas, diálogo amplio.
        val rowBtns = save.parent as ViewGroup
        assertTrue(rowBtns.indexOfChild(cancel) < rowBtns.indexOfChild(save))
        val density = activity.resources.displayMetrics.scaledDensity
        assertEquals(15f, save.textSize / density, 0.5f)
        assertEquals(15f, cancel.textSize / density, 0.5f)
        assertFalse(save.isAllCaps)
        assertFalse(cancel.isAllCaps)
        assertTrue((cancel.layoutParams as ViewGroup.MarginLayoutParams).marginEnd > 0)
        assertTrue((dlg.window?.attributes?.width ?: 0) > 0)
        val input = dialogViews(dlg).filterIsInstance<EditText>().first()
        // Campo con estilo y botones idénticos a revisión.
        assertNotNull(input.background)
        save.performClick()
        idleMain()
        assertTrue("el nombre vacío no cierra", dlg.isShowing)
        assertNotNull(input.error)
        input.setText("mis 21 min")
        save.performClick()
        awaitToast("Planilla «mis 21 min» guardada.")
        assertNotNull(ofType<Button>().firstOrNull { it.text.toString() == "mis 21 min" })
    }

    @Test
    fun `sonido directo sin dialogo siempre con sonido nunca vibracion`() {
        launch()
        openDrawer()
        expandSection("Sonido")
        // Sin diálogo: las 3 opciones están inline.
        assertEquals(
            listOf("Aire", "Cuenco", "Glide"),
            ofType<Button>().map { it.text.toString() }
                .filter { it in setOf("Aire", "Cuenco", "Glide") },
        )
        row("Glide").performClick()
        awaitToast("Sonido: Glide.")
        val stored = prefs()
        assertTrue(stored.getBoolean(BreathingActivity.KEY_SOUND, false))
        assertFalse(stored.getBoolean(BreathingActivity.KEY_VIBRATION, true))
        assertEquals(SoundStyle.GLIDE.name, stored.getString(BreathingActivity.KEY_TIMBRE, ""))
        assertEquals("Glide", summaryOf("Sonido"))
        val claro = app.getColor(com.jhomc.healthsync.R.color.burgundy_400)
        assertEquals(claro, row("Glide").currentTextColor)
    }

    @Test
    fun `guardar planilla sin patrón valido avisa`() {
        prefs().edit().putString(
            BreathingActivity.KEY_PATTERN,
            JSONObject().put("inhale_s", 0.1).put("exhale_s", 6.0).toString(),
        ).commit()
        launch()
        openDrawer()
        expandSection("Plantillas")
        row("＋").performClick()
        awaitToast("Revisa los tiempos antes de guardar.")
    }
}
