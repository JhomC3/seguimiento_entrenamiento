package com.jhomc.healthsync

import android.app.AlertDialog
import android.content.Context
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.NumberPicker
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.jhomc.healthsync.data.SecureTargetStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Pestaña Respirar: el círculo ES el botón (toque = empezar/pausar/continuar,
 * mantener 1.5 s = terminar). Patrón y TIMER en chips (toque = editor
 * deslizante) y el resto tras el engranaje ⚙. Al terminar: revisión con
 * [Guardar sesión] o Descartar (nada se envía solo).
 * En marcha la configuración se oculta: solo círculo + stats.
 */
class BreathingActivity : ComponentActivity() {

    private lateinit var repo: BreathingRepository
    private lateinit var circle: BreathCircleView
    private lateinit var root: LinearLayout
    private lateinit var statsView: TextView
    private lateinit var phaseLabel: TextView
    private lateinit var configContainer: LinearLayout
    private lateinit var reviewCard: LinearLayout
    private lateinit var reviewSummary: TextView
    private lateinit var durationChip: Button
    private lateinit var plansRow: LinearLayout
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

    private val chipButtons = mutableMapOf<String, Button>()

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

        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 20, 28, 28)
        }

        statsView = TextView(this).apply {
            gravity = Gravity.END
            textSize = 16f
            text = statsText(null)
            asBreather()
        }
        root.addView(statsView)

        circle = BreathCircleView(this).apply {
            // Ocupa lo que sobre: sin hueco negro abajo en pantallas normales.
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f,
            )
            onTap = { circleTap() }
            onHoldReset = { circleHold() }
        }
        root.addView(circle)
        phaseLabel = TextView(this).apply {
            gravity = Gravity.CENTER
            textSize = 28f
            text = ""
            asBreather(bold = true)
            setPadding(0, 12, 0, 12)
        }
        root.addView(phaseLabel)

        reviewCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = LinearLayout.GONE
            setPadding(0, 8, 0, 8)
        }
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
        reviewRow.addView(friendlyButton("Guardar sesión").apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.2f)
            setOnClickListener { saveReview() }
        })
        reviewRow.addView(friendlyOutlineButton("Descartar").apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setOnClickListener { discardReview() }
        })
        reviewCard.addView(reviewRow)
        root.addView(reviewCard)

        configContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        configContainer.addView(patternChips())
        val secondRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 16, 0, 0)
        }
        durationChip = Button(this).apply {
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.4f)
            setOnClickListener { editDuration() }
            asBreather()
        }
        secondRow.addView(durationChip)
        secondRow.addView(Button(this).apply {
            text = "⚙"
            textSize = 22f
            contentDescription = "Ajustes de respiración"
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            asBreather()
            setOnClickListener { showSettings() }
        })
        configContainer.addView(secondRow)
        plansRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 12, 0, 0)
        }
        configContainer.addView(
            android.widget.HorizontalScrollView(this).apply {
                isHorizontalScrollBarEnabled = false
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                )
                addView(plansRow)
            },
        )
        root.addView(configContainer)
        refreshDurationChip()
        refreshPlansRow()

        setContentView(ScrollView(this).apply {
            isFillViewport = true
            addView(root)
        })
        observeRun()
        lifecycleScope.launch(Dispatchers.IO) {
            runCatching { repairOrphans() }
            drain(silent = true)
        }
        // Permiso HC justo-a-tiempo al entrar (una vez por creación): las
        // sesiones terminadas ya nacen con permiso y el espejo no lo pide tarde.
        if (savedInstanceState == null) ensureHcPermission()
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
        saveDefault(pattern)
        BreathingService.start(this, pattern, totalS, sound, vibration, timbre)
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

    // --- Chips -----------------------------------------------------------------------

    private fun patternChips(): LinearLayout {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val defs = listOf(
            Triple("inhale", "INHALE", { inhale }),
            Triple("holdIn", "HOLD", { holdIn }),
            Triple("exhale", "EXHALE", { exhale }),
            Triple("holdOut", "HOLD", { holdOut }),
        )
        for ((key, label, get) in defs) {
            row.addView(Button(this).apply {
                text = chipText(label, get())
                textSize = 18f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                setOnClickListener { editChip(key, label) }
                asBreather()
                chipButtons[key] = this
            })
        }
        return row
    }

    /** Hold en 0 muestra OFF (el editor permite ponerlo). */
    private fun chipText(label: String, value: Double): String =
        if (value == 0.0 && label == "HOLD") "$label\nOFF" else "$label\n${fmt(value)}s"

    private fun setValue(key: String, value: Double) {
        when (key) {
            "inhale" -> inhale = value
            "holdIn" -> holdIn = value
            "exhale" -> exhale = value
            "holdOut" -> holdOut = value
        }
        refreshChips()
    }

    private fun getValue(key: String): Double = when (key) {
        "inhale" -> inhale
        "holdIn" -> holdIn
        "exhale" -> exhale
        "holdOut" -> holdOut
        else -> 0.0
    }

    private fun refreshChips() {
        for ((key, button) in chipButtons) {
            val label = button.text.split("\n").firstOrNull() ?: ""
            button.text = chipText(label, getValue(key))
        }
    }

    /** Editor deslizante: segundos (1 en 1) + décimas (0.1). La décima mínima
     *  se ajusta sola (inhala/exhala no bajan de 0.5): los estados inválidos
     *  no existen en vez de dar error. */
    private fun editChip(key: String, label: String) {
        val range = BreathingValidation.phaseRange(key)
        val secMin = range.start.toInt()
        val secPicker = NumberPicker(this).apply {
            minValue = secMin
            maxValue = 60
            wrapSelectorWheel = false
            contentDescription = "$label: segundos"
        }
        val tenthPicker = NumberPicker(this).apply {
            minValue = 0
            maxValue = 9
            displayedValues = Array(10) { ".$it" }
            wrapSelectorWheel = false
            contentDescription = "$label: décimas"
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
        val cols = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        cols.addView(secPicker)
        cols.addView(tenthPicker)
        AlertDialog.Builder(this)
            .setTitle("$label (segundos · décimas)")
            .setView(cols)
            .setPositiveButton("Listo") { _, _ ->
                BreathingValidation.phaseValue(key, secPicker.value, tenthPicker.value)?.let {
                    setValue(key, it)
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun durationLabel(): String = if (totalS > 0) "TIMER\n${totalS / 60}m ${totalS % 60}s" else "TIMER\nLibre"

    private fun refreshDurationChip() {
        durationChip.text = durationLabel()
        durationChip.textSize = 18f
    }

    // --- Planillas (prefs JSON, tope 8): toque = cargar, mantener = borrar ---

    private fun refreshPlansRow() {
        plansRow.removeAllViews()
        for (plan in plans) {
            plansRow.addView(Button(this).apply {
                text = plan.nombre
                textSize = 15f
                asBreather()
                setOnClickListener { applyPlan(plan) }
                setOnLongClickListener { deletePlan(plan); true }
            })
        }
        plansRow.addView(Button(this).apply {
            text = "＋"
            textSize = 18f
            contentDescription = "Guardar planilla actual"
            asBreather()
            setOnClickListener { askPlanName() }
        })
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
        val input = EditText(this).apply {
            hint = "Nombre (p. ej. 21 min)"
            inputType = InputType.TYPE_CLASS_TEXT
        }
        AlertDialog.Builder(this)
            .setTitle("Guardar planilla")
            .setView(input)
            .setPositiveButton("Guardar", null)
            .setNegativeButton("Cancelar", null)
            .create()
            .apply {
                setOnShowListener {
                    getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                        val name = input.text.toString().trim()
                        val next = BreathingPlans.add(plans, base.copy(nombre = name))
                        if (next == null) {
                            input.error = if (name.isEmpty()) "Pon un nombre." else "Tope de 8 planillas."
                        } else {
                            plans = next
                            persistPlans()
                            refreshPlansRow()
                            toast("Planilla «$name» guardada.")
                            dismiss()
                        }
                    }
                }
                show()
            }
    }

    private fun applyPlan(plan: BreathingPlans.Plan) {
        inhale = plan.pattern.inhaleS
        holdIn = plan.pattern.holdInS
        exhale = plan.pattern.exhaleS
        holdOut = plan.pattern.holdOutS
        totalS = plan.duracionS ?: -1
        timbre = plan.timbre
        refreshChips()
        refreshDurationChip()
        toast("Planilla «${plan.nombre}».")
    }

    private fun deletePlan(plan: BreathingPlans.Plan) {
        plans = BreathingPlans.remove(plans, plan.nombre)
        persistPlans()
        refreshPlansRow()
        toast("Planilla «${plan.nombre}» borrada.")
    }

    /** Duración editable: minutos + segundos + Libre, con error en el diálogo. */
    private fun editDuration() {
        val cols = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
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
        cols.addView(minPicker)
        cols.addView(secPicker)
        val error = TextView(this).apply {
            gravity = Gravity.CENTER
            setTextColor(getColor(R.color.danger_text))
        }
        val wrap = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(cols)
            addView(error)
        }
        val dlg = AlertDialog.Builder(this)
            .setTitle("Duración")
            .setView(wrap)
            .setPositiveButton("Listo", null)
            .setNeutralButton("Libre") { _, _ ->
                totalS = -1
                refreshDurationChip()
            }
            .setNegativeButton("Cancelar", null)
            .create()
        dlg.setOnShowListener {
            dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val total = BreathingValidation.durationValue(minPicker.value, secPicker.value)
                if (total == null) {
                    error.text = "Mínimo 30 s (o Libre)."
                } else {
                    totalS = total
                    refreshDurationChip()
                    dlg.dismiss()
                }
            }
        }
        dlg.show()
    }

    // --- Ajustes ⚙ ----------------------------------------------------------------------

    private fun showSettings() {
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 24, 48, 0)
        }
        body.addView(TextView(this).apply { text = "Sonido"; textSize = 16f })
        val styleNames = SoundStyle.entries.map { it.label }.toTypedArray()
        var stylePos = SoundStyle.entries.indexOf(timbre).coerceAtLeast(0)
        body.addView(TextView(this).apply { id = STYLE_VIEW_ID })
        val soundBox = CheckBox(this).apply {
            text = "Sonido"
            textSize = 16f
            isChecked = sound
        }
        body.addView(soundBox)
        val vibrationBox = CheckBox(this).apply {
            text = "Vibración"
            textSize = 16f
            isChecked = vibration
        }
        body.addView(vibrationBox)
        val dlg = AlertDialog.Builder(this)
            .setTitle("Ajustes")
            .setView(body)
            .setSingleChoiceItems(styleNames, stylePos) { _, which ->
                stylePos = which
                body.findViewById<TextView>(STYLE_VIEW_ID)?.text =
                    "Estilo: ${SoundStyle.entries[which].label}"
            }
            .setPositiveButton("Guardar") { _, _ ->
                sound = soundBox.isChecked
                vibration = vibrationBox.isChecked
                timbre = SoundStyle.entries[stylePos]
                prefs().edit()
                    .putBoolean(KEY_SOUND, sound)
                    .putBoolean(KEY_VIBRATION, vibration)
                    .putString(KEY_TIMBRE, timbre.name)
                    .apply()
                toast("Ajustes guardados (sonido: ${timbre.label}).")
            }
            .setNegativeButton("Cerrar", null)
            .create()
        dlg.show()
        body.findViewById<TextView>(STYLE_VIEW_ID)?.text = "Estilo: ${timbre.label}"
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
                            root,
                            android.transition.Fade().apply { duration = 250 },
                        )
                    }
                    keepScreen(state !is BreathRunState.Idle)
                    when (state) {
                        is BreathRunState.Idle -> {
                            circle.mode = BreathCircleView.Mode.IDLE
                            circle.reset()
                            phaseLabel.text = ""
                            statsView.text = statsText(null)
                            reviewCard.visibility = LinearLayout.GONE
                            reviewSessionId = null
                            configContainer.visibility = LinearLayout.VISIBLE
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
                            statsView.text = statsText(state)
                            reviewCard.visibility = LinearLayout.GONE
                            configContainer.visibility = LinearLayout.GONE
                        }
                        is BreathRunState.Paused -> {
                            circle.mode = BreathCircleView.Mode.PAUSED
                            circle.setStage(state.phase, state.fraction)
                            phaseLabel.text = "Paused"
                            configContainer.visibility = LinearLayout.GONE
                        }
                        is BreathRunState.Finished -> {
                            circle.mode = BreathCircleView.Mode.IDLE
                            circle.reset()
                            phaseLabel.text = ""
                            reviewSessionId = state.clientSessionId
                            reviewSummary.text =
                                "Sesión: ${state.ciclos} resp · ${"%.1f".format(state.minutos)} min · ${state.resumen}s"
                            reviewCard.visibility = LinearLayout.VISIBLE
                        }
                    }
                }
            }
        }
    }

    /** Pantalla encendida solo mientras la sesión vive (Idle la libera). */
    private fun keepScreen(on: Boolean) {
        if (on) {
            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    private fun statsText(state: BreathRunState.Running?): String {
        if (state == null) return "--:-- · 0 resp · -- rpm"
        val clockMs = if (state.totalRemainingMs < 0) state.elapsedMs else state.totalRemainingMs
        val mm = (clockMs / 60_000).toInt()
        val ss = ((clockMs % 60_000) / 1000).toInt()
        val bpm = if (state.avgBpm > 0) "%.1f".format(state.avgBpm) else "--"
        return "%02d:%02d · %d resp · %s rpm".format(mm, ss, state.cycle, bpm)
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

    /** Drenado oportunista y silencioso (cola pendiente, sin UI). */
    /** Drenado oportunista: devuelve el mensaje para la UI (llamar con silent). */
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

    private fun drain(silent: Boolean) {
        lifecycleScope.launch(Dispatchers.IO) {
            val msg = drainOnce()
            if (!silent) withContext(Dispatchers.Main) { toast(msg) }
        }
    }

    private suspend fun credentials(): Pair<String, String>? {
        val store = SecureTargetStore(this)
        // Self-seed como el diario: el destino embebido del debug vale sin
        // pasar por la pantalla principal.
        val target = store.target() ?: run {
            val url = BuildConfig.DEFAULT_SYNC_URL
            val token = BuildConfig.DEFAULT_SYNC_TOKEN
            if (url.isEmpty() || token.isEmpty()) return null
            store.saveTarget(url, "default")
            store.saveToken(token)
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
        const val STYLE_VIEW_ID = 0x7e0001
    }
}
