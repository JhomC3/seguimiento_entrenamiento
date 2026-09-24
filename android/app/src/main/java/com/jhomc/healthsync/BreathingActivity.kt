package com.jhomc.healthsync

import android.app.AlertDialog
import android.content.Context
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.NumberPicker
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.drawerlayout.widget.DrawerLayout
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.jhomc.healthsync.data.SecureTargetStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Pestaña Respirar: SOLO dial (arriba patrón+definido en dos líneas fijas,
 * centro círculo, abajo estado/`Iniciar`). El círculo ES el botón (toque =
 * empezar/pausar/continuar, mantener 1.5 s = terminar). Todo lo demás vive en
 * el panel izquierdo en acordeones (cerrado por defecto; gesto de borde o
 * glifo): patrón, duración, ajustes y planillas. Al terminar: revisión en
 * overlay con [Guardar sesión] o Descartar. Regla dura: en marcha nada se
 * mueve ni se oculta del flujo (solo el glifo pasa a INVISIBLE).
 */
class BreathingActivity : ComponentActivity() {

    private lateinit var repo: BreathingRepository
    private lateinit var circle: BreathCircleView
    private lateinit var drawerLayout: DrawerLayout
    private lateinit var contentFrame: android.widget.FrameLayout
    private lateinit var content: LinearLayout
    private lateinit var glyph: DrawerGlyphView
    private lateinit var phaseLabel: TextView
    private lateinit var veil: View
    private lateinit var reviewCard: LinearLayout
    private lateinit var reviewSummary: TextView
    private val timbreRowButtons = mutableMapOf<SoundStyle, Button>()
    private lateinit var drawerPlans: LinearLayout
    private lateinit var editorVeil: View
    private lateinit var editorCard: LinearLayout
    private var openBarKey: String? = null
    private var reviewSessionId: String? = null
    private var plans: List<BreathingPlans.Plan> = emptyList()
    private var lastStateClass: kotlin.reflect.KClass<out BreathRunState>? = null
    /**
     * Espejo HC pendiente de permiso: la concesión tardía (callback del
     * diálogo) lo completa. Seam de tests para el gateway del espejo
     * (producción = cliente real).
     */
    internal var pendingMirrorId: String? = null
    internal var mirrorGatewayFactory: (() -> HealthConnectGateway)? = null

    private fun mirrorGateway(): HealthConnectGateway =
        mirrorGatewayFactory?.invoke() ?: RealHealthConnectGateway(this)

    private var inhale = 4.0
    private var holdIn = 0.0
    private var exhale = 6.0
    private var holdOut = 0.0
    private var totalS = 600
    private var sound = true
    private var vibration = false
    private var timbre = SoundStyle.AIRE

    private val barValueViews = mutableMapOf<String, TextView>()
    private val accordionBodies = mutableMapOf<String, View>()
    private val accordionChevrons = mutableMapOf<String, ChevronView>()
    private val accordionSummaries = mutableMapOf<String, TextView>()

    private fun prefs() = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        repo = BreathingRepository(HealthDatabaseBuilder.get(this).breathingDao())
        prefs().let {
            sound = it.getBoolean(KEY_SOUND, true)
            vibration = it.getBoolean(KEY_VIBRATION, false)
            timbre = runCatching { SoundStyle.valueOf(it.getString(KEY_TIMBRE, "AIRE") ?: "AIRE") }
                .getOrDefault(SoundStyle.AIRE)
            loadDefault(it)
        }
        plans = BreathingPlans.load(prefs().getString(KEY_PLANS, "") ?: "")

        drawerLayout = DrawerLayout(this)

        contentFrame = android.widget.FrameLayout(this).apply {
            layoutParams = DrawerLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT,
            )
        }
        // Barra de navegación: el contenido la respeta (el texto inferior
        // nunca queda cortado); el drawer la gestiona solo.
        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(contentFrame) { v, insets ->
            val bars = insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            v.setPadding(28, 20 + bars.top, 28, 28 + bars.bottom)
            insets
        }

        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = android.widget.FrameLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.MATCH_PARENT,
            )
            setPadding(28, 20, 28, 28)
        }

        val topRow = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        // Glifo propio en esquina (dos líneas, la 2ª más corta).
        glyph = DrawerGlyphView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                (48 * resources.displayMetrics.density).toInt(),
                (48 * resources.displayMetrics.density).toInt(),
            )
            onTap = { drawerLayout.openDrawer(Gravity.START) }
        }
        topRow.addView(glyph)
        // Barra glass del mockup: 5 columnas (Tiempo + 4 fases). Toque en
        // columna = rueda inline ahí mismo (ancho completo, bajo la barra).
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            )
            background = android.graphics.drawable.GradientDrawable().apply {
                shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                cornerRadius = 20f * resources.displayMetrics.density
                setColor(0xB3171717.toInt())
                setStroke(
                    resources.displayMetrics.density.coerceAtLeast(1f).toInt(),
                    0x66404040.toInt(),
                )
            }
            setPadding(
                (16 * resources.displayMetrics.density).toInt(),
                (12 * resources.displayMetrics.density).toInt(),
                (16 * resources.displayMetrics.density).toInt(),
                (12 * resources.displayMetrics.density).toInt(),
            )
        }
        for ((key, label) in barColumnDefs()) {
            bar.addView(LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                isClickable = true
                isFocusable = true
                contentDescription = "Editar $label"
                addView(TextView(this@BreathingActivity).apply {
                    text = label
                    gravity = Gravity.CENTER
                    textSize = 13f
                    maxLines = 1
                    includeFontPadding = false
                    ellipsize = android.text.TextUtils.TruncateAt.END
                    setTextColor(getColor(R.color.neutral_100))
                    setPadding(0, 0, 0, (4 * resources.displayMetrics.density).toInt())
                    asBreather(bold = true)
                })
                addView(TextView(this@BreathingActivity).apply {
                    gravity = Gravity.CENTER
                    textSize = 19f
                    maxLines = 1
                    includeFontPadding = false
                    ellipsize = android.text.TextUtils.TruncateAt.END
                    setTextColor(getColor(R.color.neutral_100))
                    asBreather()
                }.also { barValueViews[key] = it })
                setOnClickListener { toggleBarEditor(key) }
            })
        }
        topRow.addView(bar)
        content.addView(topRow)

        circle = BreathCircleView(this).apply {
            // Ocupa lo que sobre: la pantalla es solo dial.
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f,
            )
            onTap = { circleTap() }
            onHoldReset = { circleHold() }
        }
        content.addView(circle)
        phaseLabel = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 28f
            maxLines = 1
            includeFontPadding = false
            text = "Iniciar"
            setTextColor(getColor(R.color.neutral_100))
            asBreather(bold = true)
            setPadding(0, 12, 0, 12)
        }
        content.addView(phaseLabel)
        contentFrame.addView(content)

        // Revisión en overlay: no participa del flujo (el dial no se mueve).
        veil = View(this).apply {
            visibility = View.GONE
            isClickable = true
            isFocusable = true
            setBackgroundColor(0xCC000000.toInt())
            applyGlassBlur(this)
            layoutParams = android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }
        contentFrame.addView(veil)

        reviewCard = glassCard()
        reviewSummary = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 17f
            asBreather()
            setPadding(0, 0, 0, 16)
        }
        reviewCard.addView(reviewSummary)
        val reviewRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        reviewRow.addView(friendlyOutlineButton("Descartar").apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { discardReview() }
        })
        reviewRow.addView(friendlyButton("Guardar sesión").apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { saveReview() }
        })
        reviewCard.addView(reviewRow)
        contentFrame.addView(reviewCard)

        // Editor en popup: mismo glass que la revisión (el dial no se mueve).
        // Velo glass: sobre fondo casi negro el blur apenas se nota (no hay
        // nada que difuminar); el efecto lo da el dim fuerte + la textura.
        editorVeil = View(this).apply {
            visibility = View.GONE
            isClickable = true
            isFocusable = true
            setBackgroundColor(0xCC000000.toInt())
            applyGlassBlur(this)
            layoutParams = android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            )
            setOnClickListener { collapseBarEditor() }
        }
        contentFrame.addView(editorVeil)
        // Sin tarjeta ni bordes: ruedas flotando sobre el blur total.
        editorCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            setPadding(48, 32, 48, 32)
            layoutParams = android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER,
            )
        }
        contentFrame.addView(editorCard)

        drawerLayout.addView(contentFrame)
        drawerLayout.addView(buildDrawer())
        refreshBar()
        refreshSonidoRows()

        setContentView(drawerLayout)
        // Pantalla siempre encendida en Respirar (flag de ventana: se libera
        // solo al salir; el botón físico sigue bloqueando).
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        // Atrás cierra editor o panel antes que la pantalla.
        onBackPressedDispatcher.addCallback(
            this,
            object : androidx.activity.OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (editorCard.visibility == View.VISIBLE) {
                        collapseBarEditor()
                    } else if (drawerLayout.isDrawerOpen(Gravity.START)) {
                        drawerLayout.closeDrawer(Gravity.START)
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            },
        )
        observeRun()
        // Solo repara huérfanas en local: abrir no envía nada (RF-8).
        lifecycleScope.launch(Dispatchers.IO) {
            runCatching { repairOrphans() }
        }
    }

    private val mindfulnessPermission =
        registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { granted ->
            if (!granted) {
                prefs().edit().putBoolean(KEY_HC_DENIED, true).apply()
                pendingMirrorId = null
            } else {
                onMirrorPermissionGranted()
            }
        }

    /** La concesión tardía completa el espejo pendiente (carrera del diálogo). */
    internal fun onMirrorPermissionGranted() {
        val id = pendingMirrorId ?: return
        lifecycleScope.launch(Dispatchers.IO) {
            if (tryMirrorSession(id) is MindfulnessWriter.Outcome.Published) {
                withContext(Dispatchers.Main) { toast("HC ✓") }
            }
        }
    }

    /** Toast corto: único feedback de la pantalla (nada persistente). */
    private fun toast(msg: String) {
        runOnUiThread {
            android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * Permiso justo-a-tiempo al guardar una completada: si ya está concedido
     * o denegado antes, no hace nada; si no, pide una vez. Guardar continúa
     * igual se conceda o no (el escritor omite en silencio).
     */
    private fun ensureHcPermission() {
        if (prefs().getBoolean(KEY_HC_DENIED, false)) return
        lifecycleScope.launch(Dispatchers.IO) {
            val gw = runCatching { mirrorGateway() }.getOrNull() ?: return@launch
            val available = runCatching { gw.sdkStatus() }.getOrNull() ==
                androidx.health.connect.client.HealthConnectClient.SDK_AVAILABLE
            if (!available) return@launch
            val granted = runCatching {
                gw.grantedPermissions().contains(HealthConnectManager(gw).mindfulnessWritePermission())
            }.getOrDefault(false)
            if (!granted) {
                withContext(Dispatchers.Main) {
                    runCatching {
                        mindfulnessPermission.launch(
                            HealthConnectManager(gw).mindfulnessWritePermission(),
                        )
                    }
                }
            }
        }
    }

    // --- Gesto global del panel ----------------------------------------------------

    internal enum class SwipeAction { OPEN, CLOSE }

    private var swipeDownX = 0f
    private var swipeDownY = 0f
    private var swipeTracking = false

    /**
     * Deslizar horizontal abre/cierra el panel en cualquier zona (observa,
     * nunca consume: delega siempre). La franja de sistema (~40dp) queda para
     * el gesto nativo (borde + atrás). En marcha el candado de DrawerLayout
     * ignora la apertura: sin checks redundantes.
     */
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                swipeDownX = event.x
                swipeDownY = event.y
                swipeTracking = true
            }
            MotionEvent.ACTION_UP -> {
                if (swipeTracking) {
                    swipeTracking = false
                    val d = resources.displayMetrics.density
                    when (
                        swipeAction(
                            (event.x - swipeDownX) / d,
                            (event.y - swipeDownY) / d,
                            swipeDownX / d,
                        )
                    ) {
                        SwipeAction.OPEN -> drawerLayout.openDrawer(Gravity.START)
                        SwipeAction.CLOSE -> drawerLayout.closeDrawer(Gravity.START)
                        null -> Unit
                    }
                }
            }
            MotionEvent.ACTION_CANCEL -> swipeTracking = false
        }
        return super.dispatchTouchEvent(event)
    }

    /** Decisión pura del gesto (testeable): dx/dy y origen en dp. */
    internal fun swipeAction(dxDp: Float, dyDp: Float, downXDp: Float): SwipeAction? {
        if (kotlin.math.abs(dxDp) <= 100 || kotlin.math.abs(dxDp) <= 2 * kotlin.math.abs(dyDp)) {
            return null
        }
        return if (dxDp > 0) {
            if (downXDp > 40) SwipeAction.OPEN else null
        } else {
            SwipeAction.CLOSE
        }
    }

    // --- Círculo-botón ------------------------------------------------------------

    private fun circleTap() {
        when (BreathingService.state.value) {
            is BreathRunState.Running, is BreathRunState.Paused -> BreathingService.toggle(this)
            else -> startSession()
        }
    }

    private fun circleHold() {
        val state = BreathingService.state.value
        if (state is BreathRunState.Running || state is BreathRunState.Paused) {
            BreathingService.stop(this)
        }
    }

    private fun startSession() {
        val pattern = currentPattern()
        if (pattern == null) {
            toast("Revisa los tiempos (inhale/exhale 0.5–60 s).")
            return
        }
        collapseBarEditor()
        saveDefault(pattern)
        // Siempre con sonido, nunca vibración (orden del dueño).
        BreathingService.start(this, pattern, totalS, true, false, timbre)
    }

    /** La última config ejecutada queda por defecto al volver. */
    private fun saveDefault(pattern: BreathingPattern) {
        prefs().edit()
            .putString(KEY_PATTERN, pattern.toJson().toString())
            .putInt(KEY_DURATION, totalS)
            .putString(KEY_TIMBRE, timbre.name)
            .apply()
    }

    private fun loadDefault(prefs: android.content.SharedPreferences) {
        runCatching {
            BreathingPattern.fromJson(org.json.JSONObject(prefs.getString(KEY_PATTERN, "") ?: ""))
        }.getOrNull()?.let {
            inhale = it.inhaleS
            holdIn = it.holdInS
            exhale = it.exhaleS
            holdOut = it.holdOutS
        }
        totalS = prefs.getInt(KEY_DURATION, totalS)
    }

    // --- Panel izquierdo en acordeones (minimalista) --------------------------------

    /** Tarjeta glass (revisión y editor): mismo lenguaje, sin mover el flujo. */
    private fun glassCard(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        visibility = View.GONE
        background = android.graphics.drawable.GradientDrawable().apply {
            shape = android.graphics.drawable.GradientDrawable.RECTANGLE
            cornerRadius = 20f * resources.displayMetrics.density
            setColor(0xB3171717.toInt())
            setStroke(
                resources.displayMetrics.density.coerceAtLeast(1f).toInt(),
                0x669B1B30.toInt(),
            )
        }
        elevation = 8f * resources.displayMetrics.density
        setPadding(48, 32, 48, 32)
        layoutParams = android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
            android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER,
        )
    }

    /** Glass: doble blur + desaturado detrás del velo (API 31+); dim si no. */
    private fun applyGlassBlur(v: View) {
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            val pass = android.graphics.RenderEffect.createBlurEffect(
                25f, 25f, android.graphics.Shader.TileMode.CLAMP,
            )
            val frost = android.graphics.RenderEffect.createChainEffect(pass, pass)
            val matrix = android.graphics.ColorMatrix().apply { setSaturation(0.6f) }
            v.setRenderEffect(
                android.graphics.RenderEffect.createChainEffect(
                    android.graphics.RenderEffect.createColorFilterEffect(
                        android.graphics.ColorMatrixColorFilter(matrix),
                    ),
                    frost,
                ),
            )
        }
    }

    /** Fila minimalista: fondo transparente con ripple, texto a la izquierda. */
    private fun drawerRow(text: String): Button = Button(this).apply {
        this.text = text
        textSize = 15f
        gravity = Gravity.START or Gravity.CENTER_VERTICAL
        minHeight = (48 * resources.displayMetrics.density).toInt()
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT,
        )
        val ripple = android.util.TypedValue().let { tv ->
            theme.resolveAttribute(android.R.attr.selectableItemBackground, tv, true)
            getDrawable(tv.resourceId)
        }
        background = ripple
        setTextColor(getColor(R.color.neutral_300))
        asBreather()
    }

    /** Cabecera de acordeón: título + resumen + chevron. Toque = expandir. */
    private fun accordionHeader(key: String, title: String, parent: LinearLayout): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            minimumHeight = (56 * resources.displayMetrics.density).toInt()
            isClickable = true
            isFocusable = true
            contentDescription = title
        }
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        texts.addView(TextView(this).apply {
            text = title.uppercase()
            textSize = 18f
            setLetterSpacing(0.08f)
            setTextColor(getColor(R.color.neutral_100))
            asBreather(bold = true)
        })
        texts.addView(TextView(this).apply {
            textSize = 14f
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setTextColor(getColor(R.color.neutral_500))
            asBreather()
        }.also { accordionSummaries[key] = it })
        row.addView(texts)
        row.addView(ChevronView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                (32 * resources.displayMetrics.density).toInt(),
                (32 * resources.displayMetrics.density).toInt(),
            )
        }.also { accordionChevrons[key] = it })
        row.setOnClickListener { toggleAccordion(key) }
        parent.addView(row)
        parent.addView(View(this).apply {
            setBackgroundColor(getColor(R.color.neutral_700))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                (1 * resources.displayMetrics.density).toInt().coerceAtLeast(1),
            )
        })
        return row
    }

    /** Cada acordeón abre/cierra por su cuenta (no colapsa a los demás). */
    private fun toggleAccordion(key: String) {
        val body = accordionBodies[key] ?: return
        val open = body.visibility != View.VISIBLE
        body.visibility = if (open) View.VISIBLE else View.GONE
        accordionChevrons[key]?.expanded = open
    }

    /** Edición pre-sesión: en marcha las columnas no expanden. */
    private fun sessionLive(): Boolean {
        val s = BreathingService.state.value
        return s is BreathRunState.Running || s is BreathRunState.Paused
    }

    private fun barColumnDefs(): List<Triple<String, String, String>> = listOf(
        Triple("tiempo", "Min", "Editar Min"),
        Triple("inhale", "Inhalar", "Editar Inhalar"),
        Triple("holdIn", "Sostener", "Editar Sostener tras inhalar"),
        Triple("exhale", "Exhalar", "Editar Exhalar"),
        Triple("holdOut", "Sostener", "Editar Sostener tras exhalar"),
    )

    /** Una abierta cada vez; re-toque o Cancelar cierra. En marcha no expande (RF-5). */
    internal fun toggleBarEditor(key: String) {
        if (sessionLive()) return
        if (openBarKey == key) {
            collapseBarEditor()
            return
        }
        openBarKey = key
        editorCard.removeAllViews()
        editorCard.addView(if (key == "tiempo") durationEditor() else phaseEditor(key))
        editorVeil.visibility = View.VISIBLE
        editorCard.visibility = View.VISIBLE
        for ((k, v) in barValueViews) {
            v.setTextColor(getColor(if (k == key) R.color.burgundy_400 else R.color.neutral_100))
        }
    }

    internal fun collapseBarEditor() {
        openBarKey = null
        editorVeil.visibility = View.GONE
        editorCard.visibility = View.GONE
        editorCard.removeAllViews()
        for ((_, v) in barValueViews) v.setTextColor(getColor(R.color.neutral_100))
    }

    /** Rueda inline de fase (misma validación que el diálogo retirado). */
    private fun phaseEditor(key: String): View {
        val range = BreathingValidation.phaseRange(key)
        val secMin = range.start.toInt()
        val desc = barColumnDefs().first { it.first == key }.third
        val secPicker = NumberPicker(this).apply {
            minValue = secMin
            maxValue = 60
            wrapSelectorWheel = false
            contentDescription = "$desc: segundos"
        }
        val tenthPicker = NumberPicker(this).apply {
            minValue = 0
            maxValue = 9
            displayedValues = Array(10) { "$it" }
            wrapSelectorWheel = false
            contentDescription = "$desc: décimas"
        }
        fun syncTenths() {
            val minTenths = if (secPicker.value == 0 && range.start > 0) {
                (range.start * 10).toInt()
            } else {
                0
            }
            if (tenthPicker.minValue != minTenths) {
                tenthPicker.minValue = minTenths
                if (tenthPicker.value < minTenths) tenthPicker.value = minTenths
            }
        }
        val current = getValue(key)
        secPicker.value = current.toInt().coerceIn(secMin, 60)
        tenthPicker.value = ((current * 10).toInt() % 10).coerceIn(0, 9)
        syncTenths()
        secPicker.setOnValueChangedListener { _, _, _ -> syncTenths() }
        return inlineEditorWrap(listOf(secPicker, tenthPicker), "Revisa el valor.", onDone = {
            BreathingValidation.phaseValue(key, secPicker.value, tenthPicker.value)?.let {
                setValue(key, it)
                collapseBarEditor()
                true
            } ?: false
        })
    }

    /** Rueda inline de duración (misma validación que el diálogo retirado). */
    private fun durationEditor(): View {
        val minPicker = NumberPicker(this).apply {
            minValue = 0
            maxValue = 120
            displayedValues = Array(121) { "${it}m" }
            value = if (totalS > 0) (totalS / 60).coerceIn(0, 120) else 10
            wrapSelectorWheel = false
            contentDescription = "Duración: minutos"
        }
        val secPicker = NumberPicker(this).apply {
            minValue = 0
            maxValue = 59
            displayedValues = Array(60) { "${it}s" }
            value = if (totalS > 0) (totalS % 60) else 0
            wrapSelectorWheel = false
            contentDescription = "Duración: segundos"
        }
        val wrap = inlineEditorWrap(listOf(minPicker, secPicker), "Mínimo 30 s.", onDone = {
            if (minPicker.value == 0 && secPicker.value == 0) {
                totalS = -1
                persistDefaults()
                refreshBar()
                collapseBarEditor()
                toast("Libre (sin temporizador).")
                true
            } else {
                val total = BreathingValidation.durationValue(minPicker.value, secPicker.value)
                if (total == null) {
                    false
                } else {
                    totalS = total
                    persistDefaults()
                    refreshBar()
                    collapseBarEditor()
                    true
                }
            }
        })
        return wrap
    }

    /**
     * Contenido del popup: ruedas + error + fila ✕|✓ (misma fuente).
     * `onDone` aplica y dice si cierra.
     */
    private fun inlineEditorWrap(
        pickers: List<NumberPicker>,
        errorText: String,
        onDone: () -> Boolean,
    ): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(0, 8, 0, 8)
        }
        val cols = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        for (p in pickers) {
            // Ruedas grandes y legibles sobre el blur.
            p.scaleX = 1.25f
            p.scaleY = 1.25f
            p.setPadding(0, 16, 0, 16)
            cols.addView(p)
        }
        box.addView(cols)
        val error = TextView(this).apply {
            tag = "bar-error"
            gravity = Gravity.CENTER
            setTextColor(getColor(R.color.danger_text))
        }
        box.addView(error)
        // Fila horizontal (✕ izquierda, [Libre], ✓ derecha) en texto con la
        // misma instancia de fuente. Solo cambia la posición.
        val rowBtns = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val face = sharedGlyphFace()
        fun glyphButton(text: String, description: String): Button =
            Button(this).apply {
                this.text = text
                textSize = 26f
                contentDescription = description
                minHeight = (64 * resources.displayMetrics.density).toInt()
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                val ripple = android.util.TypedValue().let { tv ->
                    theme.resolveAttribute(android.R.attr.selectableItemBackground, tv, true)
                    getDrawable(tv.resourceId)
                }
                background = ripple
                setTextColor(getColor(R.color.neutral_100))
                typeface = face
                paint.isFakeBoldText = true
            }
        rowBtns.addView(glyphButton("✕", "Cancelar").apply {
            setOnClickListener { collapseBarEditor() }
        })
        rowBtns.addView(glyphButton("✓", "Listo").apply {
            setOnClickListener { if (!onDone()) error.text = errorText }
        })
        box.addView(rowBtns)
        return box
    }

    /**
     * Fuente compartida de ✕/✓: la que traiga AMBOS glifos (misma fuente
     * garantizada también en el render, no solo en el objeto).
     */
    private fun sharedGlyphFace(): android.graphics.Typeface {
        val comfortaa = runCatching { resources.getFont(R.font.comfortaa_bold) }.getOrNull()
        val probe = android.graphics.Paint()
        if (comfortaa != null) {
            probe.typeface = comfortaa
            if (runCatching { probe.hasGlyph("✕") && probe.hasGlyph("✓") }.getOrDefault(false)) {
                return comfortaa
            }
        }
        val roboto = android.graphics.Typeface.DEFAULT_BOLD
        probe.typeface = roboto
        if (runCatching { probe.hasGlyph("✕") && probe.hasGlyph("✓") }.getOrDefault(false)) {
            return roboto
        }
        return comfortaa ?: roboto
    }

    private fun accordionBody(key: String, parent: LinearLayout, open: Boolean): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = if (open) View.VISIBLE else View.GONE
            setPadding(
                (16 * resources.displayMetrics.density).toInt(), 0,
                0, (8 * resources.displayMetrics.density).toInt(),
            )
            accordionBodies[key] = this
            parent.addView(this)
        }
    }

    /** Panel: acordeones Ajustes / Plantillas. Cerrado por defecto. */
    private fun buildDrawer(): ScrollView {
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            // Negro puro (orden del dueño; fuera de tokens a propósito).
            setBackgroundColor(0xFF000000.toInt())
            setPadding(48, 32, 48, 32)
        }
        accordionHeader("sonido", "Sonido", inner)
        accordionBody("sonido", inner, open = false).apply {
            for (style in SoundStyle.entries) {
                addView(drawerRow("").apply {
                    setOnClickListener { selectTimbre(style) }
                    timbreRowButtons[style] = this
                })
            }
        }
        accordionHeader("plantillas", "Plantillas", inner)
        accordionBody("plantillas", inner, open = false).apply {
            drawerPlans = LinearLayout(this@BreathingActivity).apply {
                orientation = LinearLayout.VERTICAL
            }
            addView(drawerPlans)
            addView(drawerRow("＋ Guardar actual").apply {
                contentDescription = "Guardar planilla actual"
                setOnClickListener { askPlanName() }
            })
        }
        refreshPlansRow()
        return ScrollView(this).apply {
            isFillViewport = true
            layoutParams = DrawerLayout.LayoutParams(
                (300 * resources.displayMetrics.density).toInt(),
                LinearLayout.LayoutParams.MATCH_PARENT,
                Gravity.START,
            )
            addView(inner)
        }
    }

    private fun setValue(key: String, value: Double) {
        when (key) {
            "inhale" -> inhale = value
            "holdIn" -> holdIn = value
            "exhale" -> exhale = value
            "holdOut" -> holdOut = value
        }
        persistDefaults()
        refreshBar()
    }

    /** Cada cambio se persiste al instante (no solo al arrancar). */
    private fun persistDefaults() {
        currentPattern()?.let { saveDefault(it) }
    }

    private fun getValue(key: String): Double = when (key) {
        "inhale" -> inhale
        "holdIn" -> holdIn
        "exhale" -> exhale
        "holdOut" -> holdOut
        else -> 0.0
    }

    /** Barra del mockup: Tiempo `10 min`/`Libre`, fases en número. */
    private fun refreshBar() {
        barValueViews["tiempo"]?.text = fmtDur(totalS)
        barValueViews["inhale"]?.text = fmt(inhale)
        barValueViews["holdIn"]?.text = fmt(holdIn)
        barValueViews["exhale"]?.text = fmt(exhale)
        barValueViews["holdOut"]?.text = fmt(holdOut)
    }

    private fun fmtDur(total: Int): String {
        if (total <= 0) return "Libre"
        val m = total / 60
        val s = total % 60
        return if (s == 0) "$m" else "$m:${"%02d".format(s)}"
    }

    /** Timbres directos (sin diálogo): toque aplica al instante. */
    private fun selectTimbre(style: SoundStyle) {
        sound = true
        vibration = false
        timbre = style
        prefs().edit()
            .putBoolean(KEY_SOUND, true)
            .putBoolean(KEY_VIBRATION, false)
            .putString(KEY_TIMBRE, timbre.name)
            .apply()
        refreshSonidoRows()
        toast("Sonido: ${timbre.label}.")
    }

    private fun refreshSonidoRows() {
        for ((style, button) in timbreRowButtons) {
            button.text = style.label
            button.setTextColor(
                getColor(if (style == timbre) R.color.burgundy_400 else R.color.neutral_300),
            )
        }
        accordionSummaries["sonido"]?.text = timbre.label
    }

    // --- Planillas (prefs JSON, tope 8): toque = cargar, mantener = borrar ---

    private fun refreshPlansRow() {
        drawerPlans.removeAllViews()
        for (plan in plans) {
            drawerPlans.addView(drawerRow(plan.nombre).apply {
                setOnClickListener { applyPlan(plan) }
                setOnLongClickListener { deletePlan(plan); true }
            })
        }
        accordionSummaries["plantillas"]?.text =
            if (plans.isEmpty()) "Sin guardar" else "${plans.size} guardada(s)"
    }

    private fun persistPlans() {
        prefs().edit().putString(KEY_PLANS, BreathingPlans.dump(plans)).apply()
    }

    private fun currentPlan(): BreathingPlans.Plan? {
        val pattern = currentPattern() ?: return null
        return BreathingPlans.Plan("", pattern, totalS.takeIf { it > 0 }, timbre)
    }

    private fun askPlanName() {
        val base = currentPlan()
        if (base == null) {
            toast("Revisa los tiempos antes de guardar.")
            return
        }
        val d = resources.displayMetrics.density
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((24 * d).toInt(), (16 * d).toInt(), (24 * d).toInt(), (8 * d).toInt())
        }
        val input = EditText(this).apply {
            hint = "Nombre (p. ej. 21 min)"
            inputType = InputType.TYPE_CLASS_TEXT
            textSize = 16f
            minHeight = (52 * d).toInt()
            setPadding((16 * d).toInt(), 0, (16 * d).toInt(), 0)
            setTextColor(getColor(R.color.neutral_100))
            setHintTextColor(getColor(R.color.neutral_500))
            background = android.graphics.drawable.GradientDrawable().apply {
                shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                cornerRadius = 12f * d
                setColor(getColor(R.color.overlay_row))
            }
            asBreather()
        }
        box.addView(input)
        val rowBtns = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, (16 * d).toInt(), 0, 0)
        }
        var dlg: AlertDialog? = null
        rowBtns.addView(friendlyOutlineButton("Cancelar").apply {
            val p = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            p.marginEnd = (12 * resources.displayMetrics.density).toInt()
            layoutParams = p
            textSize = 15f
            isAllCaps = false
            setOnClickListener { dlg?.dismiss() }
        })
        rowBtns.addView(friendlyButton("Guardar").apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            textSize = 15f
            isAllCaps = false
            setOnClickListener {
                val name = input.text.toString().trim()
                val next = BreathingPlans.add(plans, base.copy(nombre = name))
                if (next == null) {
                    input.error = if (name.isEmpty()) "Pon un nombre." else "Tope de 8 planillas."
                } else {
                    plans = next
                    persistPlans()
                    refreshPlansRow()
                    toast("Planilla «$name» guardada.")
                    dlg?.dismiss()
                }
            }
        })
        box.addView(rowBtns)
        dlg = AlertDialog.Builder(this)
            .setTitle("Guardar planilla")
            .setView(box)
            .create()
        dlg.show()
        // Popup amplio: 90% del ancho (la medida real se ve en el APK).
        dlg.window?.let { w ->
            val lp = w.attributes
            lp.width = (resources.displayMetrics.widthPixels * 0.9).toInt()
            w.attributes = lp
        }
    }

    private fun applyPlan(plan: BreathingPlans.Plan) {
        inhale = plan.pattern.inhaleS
        holdIn = plan.pattern.holdInS
        exhale = plan.pattern.exhaleS
        holdOut = plan.pattern.holdOutS
        totalS = plan.duracionS ?: -1
        timbre = plan.timbre
        persistDefaults()
        refreshBar()
        refreshSonidoRows()
        toast("Planilla «${plan.nombre}».")
    }

    private fun deletePlan(plan: BreathingPlans.Plan) {
        plans = BreathingPlans.remove(plans, plan.nombre)
        persistPlans()
        refreshPlansRow()
        toast("Planilla «${plan.nombre}» borrada.")
    }

    // --- Patrón ---------------------------------------------------------------------

    private fun currentPattern(): BreathingPattern? {
        if (inhale !in 0.5..60.0 || exhale !in 0.5..60.0) return null
        if (holdIn !in 0.0..60.0 || holdOut !in 0.0..60.0) return null
        return BreathingPattern(
            inhaleS = inhale, holdInS = holdIn, exhaleS = exhale, holdOutS = holdOut,
        )
    }

    // --- Estados -----------------------------------------------------------------------

    private fun observeRun() {
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                BreathingService.state.collect { state ->
                    // Transición con fundido solo al cambiar de estructura
                    // (no en cada tick): mismo estado final, sin salto.
                    if (state::class != lastStateClass) {
                        lastStateClass = state::class
                        android.transition.TransitionManager.beginDelayedTransition(
                            content,
                            android.transition.Fade().apply { duration = 250 },
                        )
                    }
                    // Cero saltos: el flujo (TOP, dial, etiqueta) nunca cambia
                    // de visibilidad ni de texto por tick; solo el círculo y
                    // la fase se actualizan, y la revisión va en overlay.
                    when (state) {
                        is BreathRunState.Idle -> {
                            circle.mode = BreathCircleView.Mode.IDLE
                            circle.reset()
                            phaseLabel.text = "Iniciar"
                            refreshBar()
                            veil.visibility = View.GONE
                            reviewCard.visibility = LinearLayout.GONE
                            reviewSessionId = null
                            glyph.visibility = View.VISIBLE
                            setDrawerEnabled(true)
                        }
                        is BreathRunState.Running -> {
                            circle.mode = BreathCircleView.Mode.RUNNING
                            if (state.phase != BreathPhase.REST) {
                                // En REST el círculo se congela y se anuncia lo que viene.
                                circle.setStage(state.phase, state.fraction)
                                phaseLabel.text = state.phase.label
                            } else {
                                phaseLabel.text = state.nextPhase.label
                            }
                            veil.visibility = View.GONE
                            reviewCard.visibility = LinearLayout.GONE
                            // INVISIBLE (no GONE): reserva el sitio, nada se mueve.
                            glyph.visibility = View.INVISIBLE
                            setDrawerEnabled(false)
                        }
                        is BreathRunState.Paused -> {
                            circle.mode = BreathCircleView.Mode.PAUSED
                            circle.setStage(state.phase, state.fraction)
                            phaseLabel.text = "Pausa"
                            glyph.visibility = View.INVISIBLE
                            setDrawerEnabled(false)
                        }
                        is BreathRunState.Finished -> {
                            circle.mode = BreathCircleView.Mode.IDLE
                            circle.reset()
                            // Espacio (nunca vacío): la altura no colapsa.
                            phaseLabel.text = " "
                            refreshBar()
                            reviewSessionId = state.clientSessionId
                            reviewSummary.text =
                                "${state.ciclos} resp · ${"%.1f".format(state.minutos)} min"
                            veil.visibility = View.VISIBLE
                            reviewCard.visibility = LinearLayout.VISIBLE
                            glyph.visibility = View.VISIBLE
                            setDrawerEnabled(true)
                        }
                    }
                }
            }
        }
    }

    /** Panel bloqueado en marcha (gesto y glifo muertos); libre en reposo. */
    private fun setDrawerEnabled(enabled: Boolean) {
        drawerLayout.setDrawerLockMode(
            if (enabled) {
                DrawerLayout.LOCK_MODE_UNLOCKED
            } else {
                DrawerLayout.LOCK_MODE_LOCKED_CLOSED
            },
        )
    }

    // --- Revisión: guardar o descartar --------------------------------------------------

    /**
     * "Guardar sesión": envía la cola (si no hay red, queda en cola) y espeja
     * la completada en HC cuando hay permiso; si la concesión llega tarde, el
     * callback del permiso completa el espejo pendiente.
     */
    private fun saveReview() {
        val id = reviewSessionId ?: return
        reviewSessionId = null
        reviewCard.visibility = LinearLayout.GONE
        // Permiso HC justo-a-tiempo (solo completadas lo usan); guardar continúa igual.
        ensureHcPermission()
        lifecycleScope.launch(Dispatchers.IO) {
            val msg = StringBuilder(drainOnce())
            when (tryMirrorSession(id)) {
                is MindfulnessWriter.Outcome.Published -> msg.append(" HC ✓")
                is MindfulnessWriter.Outcome.Skipped -> msg.append(" (HC: sin permiso)")
                else -> Unit
            }
            withContext(Dispatchers.Main) {
                toast(msg.toString())
                BreathingService.consumeFinished()
            }
        }
    }

    /**
     * Espejo HC de una completada (idempotente por client_session_id).
     * null = no se intentó (sin fila, parcial o sin HC); con HC disponible,
     * el "sin permiso" deja la sesión pendiente para la concesión tardía.
     */
    internal suspend fun tryMirrorSession(id: String): MindfulnessWriter.Outcome? {
        val row = runCatching { repo.sessionById(id) }.getOrNull() ?: return null
        if (!row.completada) return null
        val gw = runCatching { mirrorGateway() }.getOrNull() ?: return null
        val available = runCatching { gw.sdkStatus() }.getOrNull() ==
            androidx.health.connect.client.HealthConnectClient.SDK_AVAILABLE
        if (!available) return null
        val minutos = (row.realS / 60.0).let { kotlin.math.round(it * 10) / 10.0 }
        val finished = FinishedBreathing(
            clientSessionId = row.clientSessionId,
            startMs = row.startMs,
            endMs = row.endMs,
            tzOffsetMin = row.tzOffsetMin,
            plannedS = row.plannedS,
            pattern = runCatching {
                BreathingPattern.fromJson(org.json.JSONObject(row.patternJson))
            }.getOrNull() ?: return null,
            completed = true,
        )
        val outcome = try {
            MindfulnessWriter(gw, HealthConnectManager(gw)).write(finished, row.ciclos, minutos)
        } catch (e: Exception) {
            android.util.Log.w("Breathing", "espejo HC falló: ${e.message}")
            return null
        }
        if (outcome is MindfulnessWriter.Outcome.Skipped && outcome.reason == "sin_permiso") {
            pendingMirrorId = id
        } else if (pendingMirrorId == id) {
            pendingMirrorId = null
        }
        return outcome
    }

    /** "Descartar": borra la sesión sin enviar (nunca salió del móvil). */
    private fun discardReview() {
        val id = reviewSessionId ?: return
        reviewSessionId = null
        if (pendingMirrorId == id) pendingMirrorId = null
        reviewCard.visibility = LinearLayout.GONE
        lifecycleScope.launch(Dispatchers.IO) {
            runCatching {
                repo.deleteSession(id)
            }.onFailure {
                withContext(Dispatchers.Main) { toast("Error al descartar: ${it.message}") }
                return@launch
            }
            withContext(Dispatchers.Main) {
                toast("Sesión descartada.")
                BreathingService.consumeFinished()
            }
        }
    }

    /** Drenado solo desde Guardar (nunca al abrir): devuelve el mensaje. */
    private suspend fun drainOnce(): String {
        val creds = credentials() ?: return "Sin destino: abre el APK debug con token."
        return try {
            drainMessage(repo.drain(creds.first, creds.second))
        } catch (e: Exception) {
            "Error al guardar: ${e.message}"
        }
    }

    /**
     * Re-encola una vez las huérfanas (sesiones que el servidor rechazó y el
     * móvil dio por perdidas). Devuelve cuántas re-encoló. El conjunto en
     * prefs evita reintentar eternamente lo que se vuelve a rechazar.
     */
    internal suspend fun repairOrphans(): Int {
        val doneIds = prefs().getStringSet(KEY_REPAIRED, emptySet())?.toMutableSet()
            ?: mutableSetOf()
        var n = 0
        for (row in repo.orphanSessions()) {
            val id = row.clientSessionId
            if (id in doneIds) continue
            if (runCatching { repo.reenqueue(id) }.getOrDefault(false)) n++
            doneIds += id
        }
        prefs().edit().putStringSet(KEY_REPAIRED, doneIds).apply()
        return n
    }

    private suspend fun credentials(): Pair<String, String>? {
        val store = SecureTargetStore(this)
        // Self-seed como el diario: el destino embebido del debug vale sin
        // pasar por la pantalla principal. Blindado: si el seed falla (p. ej.
        // sin AndroidKeyStore), se avisa sin tumbar el guardado.
        val target = store.target() ?: run {
            val url = BuildConfig.DEFAULT_SYNC_URL
            val token = BuildConfig.DEFAULT_SYNC_TOKEN
            if (url.isEmpty() || token.isEmpty()) return null
            runCatching {
                store.saveTarget(url, "default")
                store.saveToken(token)
            }.onFailure {
                android.util.Log.w("Breathing", "self-seed falló: ${it.message}")
            }
            store.target() ?: return null
        }
        val token = store.token() ?: return null
        val apiBase = TrainingApiClient.apiBaseFor(target.url, BuildConfig.DEFAULT_API_BASE) ?: return null
        return apiBase to token
    }

    private fun fmt(v: Double): String = if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()

    companion object {
        /**
         * Mensaje de guardado según el drenado (puro, testeable): distingue
         * entregado, rechazo del servidor, cola por red y respuesta HTTP.
         */
        fun drainMessage(r: BreathingRepository.DrainResult): String = when {
            r.rest == 0 && r.rejected == 0 -> "Sesión guardada."
            r.rest == 0 -> "Rechazada (HTTP ${r.rejectedStatus ?: "?"})."
            r.fault == null -> "En cola."
            r.fault.startsWith("HTTP") -> "En cola (${r.fault})."
            else -> "En cola (sin red)."
        }

        const val PREFS = "breathing"
        const val KEY_SOUND = "sound"
        const val KEY_VIBRATION = "vibration"
        const val KEY_TIMBRE = "timbre"
        const val KEY_PATTERN = "pattern"
        const val KEY_DURATION = "duracion"
        const val KEY_PLANS = "planillas"
        const val KEY_HC_DENIED = "hc_denied"
        const val KEY_REPAIRED = "reparadas"
    }
}
