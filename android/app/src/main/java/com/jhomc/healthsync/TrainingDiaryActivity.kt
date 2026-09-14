package com.jhomc.healthsync

import android.graphics.Rect
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.viewModels
import android.app.AlertDialog
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale
import kotlinx.coroutines.launch

/**
 * Diario de entrenamiento (API v1): ver la sesión del día y editarla.
 * Views programáticas como MainActivity (sin Compose/XML). El estado vive en
 * [TrainingDiaryViewModel] (sobrevive a la rotación); esta Activity solo pinta.
 *
 * Celular solo-entrenamiento: sin alimentación, sin botón Hoy, sin contador
 * global. El descanso pertenece a la serie siguiente: al hacer ✓ nace en la
 * siguiente (su dial late visible) y muere en su propio ✓.
 *
 * Reglas honestas de v1 (training-api-contract.md §4-§5):
 * - Guardar reemplaza el día completo: si ya había datos se pide confirmación.
 * - Sin LAN no se guarda ni se borra (la cola offline es v2): error visible.
 * - Sin red pero con visita previa se muestra la última copia ("sin conexión").
 */
class TrainingDiaryActivity : ComponentActivity() {

    private val vm: TrainingDiaryViewModel by viewModels()

    private lateinit var titleView: TextView
    private lateinit var emptyView: TextView
    private lateinit var rowsBox: LinearLayout
    private lateinit var prevButton: Button
    private lateinit var nextButton: Button
    // --- Solo-registro: ejercicio colapsable + series con dial propio ---
    private lateinit var saveDayButton: Button
    private lateinit var resetDayButton: Button
    private var rowsBuiltForFecha: String? = null
    private var rowsBuiltForSession: TrainingSession? = null
    private var rowsBuiltForPreview: Int = 0
    private var rowsBuiltForStructure: Int = -1
    private val headerButtons = mutableMapOf<String, Button>()
    private val headerDescs = mutableMapOf<String, String>()
    private val descansoFields = mutableMapOf<String, TextView>()
    private val dialViews = mutableMapOf<String, RestDialView>()
    private val okButtons = mutableMapOf<String, Button>()
    private val cardBodies = mutableMapOf<String, LinearLayout>()
    private val shownPanels = mutableSetOf<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Pantalla siempre encendida en el diario: con ella apagada entra Doze
        // y el ticker (piips 2:00/3:00) se retrasa. Sin permiso: la flag muere
        // con la ventana al salir (atrás/inicio) y todo vuelve a lo normal.
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        titleView = TextView(this).apply {
            asTitle()
            gravity = Gravity.CENTER
        }
        emptyView = TextView(this).apply {
            asSummary()
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        rowsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val navRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            prevButton = Button(context).apply { text = "◀" }
            nextButton = Button(context).apply { text = "▶" }
            addView(prevButton)
            addView(titleView, navParams())
            addView(nextButton)
        }
        prevButton.setOnClickListener { vm.shiftDay(-1) }
        nextButton.setOnClickListener { vm.shiftDay(1) }

        saveDayButton = primaryButton("Guardar entrenamiento")
        saveDayButton.contentDescription = "Guardar entrenamiento: enviar al servidor ahora"
        saveDayButton.minHeight = (72 * resources.displayMetrics.density).toInt()
        saveDayButton.setOnClickListener { vm.load(vm.state.value.fecha) }
        resetDayButton = Button(this).apply {
            text = "Reiniciar entreno"
            asDanger()
            contentDescription = "Reiniciar entreno: todos los descansos a cero y series desmarcadas"
            setOnClickListener { confirmResetEntreno() }
        }
        rowsBox.layoutTransition = android.animation.LayoutTransition().apply {
            enableTransitionType(android.animation.LayoutTransition.CHANGING)
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
            addView(navRow)
            addView(emptyView)
            addView(rowsBox)
            addView(saveDayButton)
            addView(resetDayButton)
        }
        setContentView(ScrollView(this).apply { addView(root) })

        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.state.collect { render(it) }
            }
        }
        // Rebuild SOLO en cambio estructural/día (si no, las animaciones
        // mueren al recrear vistas). Expandir/done/tick van in-place.
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.structureVersion.collect { rebuildCards() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.expandedUuids.collect { syncPanels() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.doneUuids.collect {
                    refreshHeaders()
                    updateEmptyView()
                    refreshCardChrome()
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.restMs.collect { updateTick() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.runningUuid.collect {
                    updateTick()
                    refreshCardChrome()
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.pausedUuids.collect {
                    updateTick()
                    refreshCardChrome()
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.entrenoRows.collect {
                    for (uuid in descansoFields.keys.toList()) refreshDescansoField(uuid)
                }
            }
        }
    }

    // --- Render ---------------------------------------------------------------

    private fun render(state: DiaryUiState) {
        val session = state.session
        titleView.text = weekdayTitle(state.fecha)
        // Sin letrero de estado (decisión de producto): ni avisos verdes ni
        // errores; la cola offline sigue funcionando en silencio.
        val busy = state.loading || state.saving
        for (b in listOf(saveDayButton, resetDayButton, prevButton, nextButton)) {
            b.isEnabled = !busy
        }
        // Al cambiar de día/sesión/preview, reagrupa. Comparación profunda
        // (no identidad): una recarga idéntica no reconstruye ni mueve scroll.
        if (!busy && (state.fecha != rowsBuiltForFecha || session != rowsBuiltForSession || state.previewId != rowsBuiltForPreview)) {
            vm.ensureEntrenoBuilt()
            rebuildCards()
            rowsBuiltForFecha = state.fecha
            rowsBuiltForSession = session
            rowsBuiltForPreview = state.previewId
            rowsBuiltForStructure = vm.structureVersion.value
        }
        updateEmptyView()
    }

    // --- Editor unificado: tarjetas ---------------------------------------------

    /**
     * Reconstruye las tarjetas. Solo en cambios estructurales o de día: el
     * resto (expandir, ✓, tick) va in-place para que las animaciones vivan.
     */
    private fun rebuildCards() {
        if (!::rowsBox.isInitialized) return
        rowsBox.removeAllViews()
        headerButtons.clear()
        headerDescs.clear()
        descansoFields.clear()
        dialViews.clear()
        okButtons.clear()
        cardBodies.clear()
        shownPanels.clear()
        val rows = vm.entrenoRows.value.filter { !it.draft.isBlank() }
        val groups = vm.entrenoGroups.value
        val done = vm.doneUuids.value
        val expanded = vm.expandedUuids.value
        updateEmptyView()
        rowsBuiltForStructure = vm.structureVersion.value
        val byUuid = SessionFlowState.flattened(groups).associateBy { it.uuid }
        // Lista plana: cada serie se encabeza con su ejercicio repetido
        // (centrado de verdad: gravity en código, el estilo por
        // setTextAppearance la ignora). Sin números de serie a la vista
        // (el ordinal vive solo en contentDescription por accesibilidad).
        // Todas las tarjetas llevan dial (incluida la primera: referencia).
        for (row in rows) {
            val item = byUuid[row.uuid] ?: continue
            val card = rowCard(row, item, row.uuid in expanded, row.uuid in done)
            cardBodies[row.uuid] = card
            rowsBox.addView(card)
        }
        shownPanels.addAll(expanded)
        updateTick()
    }

    /** Día vacío: aviso en su sitio (la sugerencia de descanso manda). */
    private fun updateEmptyView() {
        if (!::emptyView.isInitialized) return
        val (total, _, _) = SessionFlowState.progress(vm.entrenoGroups.value, vm.doneUuids.value)
        if (total == 0) {
            val sug = vm.state.value.suggestion
            emptyView.text = if (sug?.tipo == "descanso") sug.explicacion else "Sin series este día."
            emptyView.visibility = View.VISIBLE
        } else {
            emptyView.visibility = View.GONE
        }
    }

    private fun rowCard(row: EntrenoRow, item: EntrenoItem, isExpanded: Boolean, isDone: Boolean): LinearLayout {
        val dm = resources.displayMetrics.density
        // Tarjeta plana y transparente: cero fondos, cero halos, cero capas.
        // Solo aire entre series. Hecha = nombre en gris; pendiente = blanco.
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = null
            val pad = (4 * dm).toInt()
            setPadding(pad, pad, pad, pad)
            tag = "card_${row.uuid}"
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = (10 * dm).toInt()
            }
        }
        val headerBtn = Button(this).apply {
            text = headerText(item, row.draft.ejercicio)
            asExerciseName()
            // Sin fondo ni sombra elevada: texto flotando + ripple al pulsar.
            setBackgroundResource(resolveSelectableBg())
            stateListAnimator = null
            if (isDone) setTextColor(context.getColor(R.color.neutral_500))
            minHeight = (72 * dm).toInt()
            gravity = Gravity.CENTER
            contentDescription = "${row.draft.ejercicio}, serie ${item.aparenteOrden}: expandir o colapsar"
            setOnClickListener { vm.toggleExpand(item.uuid) }
        }
        headerButtons[item.uuid] = headerBtn
        headerDescs[item.uuid] = headerBtn.contentDescription.toString()
        card.addView(headerBtn)
        if (isExpanded) {
            card.addView(buildPanel(item, row.draft, isDone))
        }
        return card
    }

    /** Estado de la serie para el círculo de guardado (sin efectos). */
    private enum class CardBorder { RUNNING, PAUSED, DONE, IDLE }

    private fun cardStateFor(uuid: String): CardBorder = when {
        vm.runningUuid.value == uuid -> CardBorder.RUNNING
        uuid in vm.pausedUuids.value -> CardBorder.PAUSED
        uuid in vm.doneUuids.value -> CardBorder.DONE
        else -> CardBorder.IDLE
    }

    /** Círculo de guardado con el color del dial (sin símbolo). */
    private fun saveCircle(state: CardBorder): Drawable = GradientDrawable().apply {
        shape = GradientDrawable.OVAL
        setColor(when (state) {
            CardBorder.RUNNING -> getColor(R.color.burgundy_500)
            CardBorder.PAUSED -> android.graphics.Color.argb(110, 210, 61, 95)
            CardBorder.DONE -> getColor(R.color.detail_white)
            CardBorder.IDLE -> getColor(R.color.neutral_500)
        })
    }

    /**
     * Recolorea círculo + nombre con el estado actual. Barato y sin layout:
     * solo en cambios de running/pausado/hecho/construcción, nunca en el
     * tick de 250ms. Sin halos ni capas en las tarjetas.
     */
    private fun refreshCardChrome() {
        if (!::rowsBox.isInitialized) return
        for ((uuid, _) in cardBodies) {
            val st = cardStateFor(uuid)
            okButtons[uuid]?.background = saveCircle(st)
            headerButtons[uuid]?.let { btn ->
                btn.setTextColor(getColor(
                    if (st == CardBorder.DONE) R.color.neutral_500 else R.color.detail_white,
                ))
                val base = headerDescs[uuid] ?: return@let
                btn.contentDescription = if (st == CardBorder.RUNNING) "$base, en descanso" else base
            }
        }
    }

    /**
     * Panel expandido: dial propio arriba (180dp, dueño del descanso), steppers,
     * campo Descanso y círculo abajo. Todas las series llevan dial (la primera
     * no arranca descanso sola, pero sirve de referencia y con tap-Start).
     * Sin Ir ni INICIAR/PAUSAR: el descanso nace en el ✓ anterior y muere en el
     * ✓ propio (incluye el trabajo). Toque en dial = play/pausa/start.
     */
    private fun buildPanel(item: EntrenoItem, draft: TrainingSetDraft, isDone: Boolean): LinearLayout {
        val dm = resources.displayMetrics.density
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            tag = "panel_${item.uuid}"
        }
        val dial = RestDialView(this).apply {
            ownerName = item.ejercicio
            // Toque = play/pausa/start; mantener 3 s = reiniciar.
            onTap = { vm.onDialTap(item.uuid) }
            onHoldReset = { vm.resetRest(item.uuid) }
            startable = !isDone
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                topMargin = (8 * dm).toInt()
                bottomMargin = (8 * dm).toInt()
            }
            tag = "dial_${item.uuid}"
        }
        dialViews[item.uuid] = dial
        panel.addView(dial)
        paintDial(item.uuid, dial)
        if (item.isHiit()) {
            panel.addView(stepperRow(item, draft, "Vel.", "velocidadKmh", "vel", "Bajar velocidad", "Subir velocidad"))
            panel.addView(stepperRow(item, draft, "Dif.", "dificultad", "dif", "Bajar dificultad", "Subir dificultad"))
        } else {
            panel.addView(stepperRow(item, draft, "kg", "kg", "kg", "Bajar peso", "Subir peso", longStep = KG_STEP_LONG))
            panel.addView(stepperRow(item, draft, "reps", "reps", "reps", "Bajar repeticiones", "Subir repeticiones"))
            panel.addView(stepperRow(item, draft, "RIR", "rir", "rir", "Bajar RIR", "Subir RIR"))
        }
        val field = TextView(this).apply {
            asSummary()
            gravity = Gravity.CENTER
            tag = "desc_${item.uuid}"
        }
        descansoFields[item.uuid] = field
        panel.addView(field)
        // Círculo de guardado (72dp centrado, sin símbolo: su color es el del dial).
        val okBtn = Button(this).apply {
            text = ""
            background = saveCircle(if (isDone) CardBorder.DONE else cardStateFor(item.uuid))
            val size = (72 * dm).toInt()
            minimumWidth = size
            minimumHeight = size
            layoutParams = LinearLayout.LayoutParams(size, size).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                topMargin = (8 * dm).toInt()
                bottomMargin = (8 * dm).toInt()
            }
            contentDescription = "Guardar la serie ${item.aparenteOrden}"
            setOnClickListener {
                performHapticFeedback(android.view.HapticFeedbackConstants.CONFIRM)
                vm.guardar(item.uuid)
            }
        }
        okButtons[item.uuid] = okBtn
        panel.addView(okBtn)
        refreshDescansoField(item.uuid)
        return panel
    }

    /** Expandir/colapsar in-place (la LayoutTransition lo anima). Al abrir, revela la tarjeta. */
    private fun syncPanels() {
        if (!::rowsBox.isInitialized) return
        val expanded = vm.expandedUuids.value
        val done = vm.doneUuids.value
        for (uuid in expanded - shownPanels) {
            val card = cardBodies[uuid] ?: continue
            val row = vm.entrenoRows.value.find { it.uuid == uuid } ?: continue
            val item = SessionFlowState.flattened(vm.entrenoGroups.value).find { it.uuid == uuid } ?: continue
            card.addView(buildPanel(item, row.draft, uuid in done))
            shownPanels.add(uuid)
            revealCard(card)
        }
        for (uuid in shownPanels - expanded) {
            val card = cardBodies[uuid] ?: continue
            card.findViewWithTag<LinearLayout>("panel_$uuid")?.let { card.removeView(it) }
            descansoFields.remove(uuid)
            dialViews.remove(uuid)
            okButtons.remove(uuid)
            shownPanels.remove(uuid)
        }
        updateTick()
    }

    /**
     * Lleva la tarjeta abierta a la vista con scroll mínimo (no-op si ya es
     * visible). Se ejecuta tras el layout real (no en `post`: la posición
     * leída antes del layout sale vieja y el scroll termina al fondo).
     */
    private fun revealCard(card: LinearLayout) {
        rowsBox.viewTreeObserver.addOnGlobalLayoutListener(object : ViewTreeObserver.OnGlobalLayoutListener {
            override fun onGlobalLayout() {
                rowsBox.viewTreeObserver.removeOnGlobalLayoutListener(this)
                card.requestRectangleOnScreen(Rect(0, 0, card.width, card.height), true)
            }
        })
    }

    /** ✓ in-place: cabecera, sin reconstruir (no mata la animación). */
    private fun refreshHeaders() {
        val byUuid = SessionFlowState.flattened(vm.entrenoGroups.value).associateBy { it.uuid }
        val draftsByUuid = vm.entrenoRows.value.associate { it.uuid to it.draft }
        for ((uuid, btn) in headerButtons) {
            val item = byUuid[uuid] ?: continue
            btn.text = headerText(item, draftsByUuid[uuid]?.ejercicio ?: "")
        }
    }

    private fun stepperRow(
        item: EntrenoItem,
        draft: TrainingSetDraft,
        label: String,
        draftField: String,
        deltaField: String,
        minusDesc: String,
        plusDesc: String,
        longStep: Double? = null,
    ): LinearLayout {
        val dm = resources.displayMetrics.density
        val shown = TextView(this).apply {
            text = stepperText(label, draft, draftField)
            textSize = 20f
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            tag = "val_${item.uuid}_$deltaField"
            contentDescription = "$label: toca para escribir con teclado"
            setOnClickListener { showValueDialog(item, draft, label, draftField, deltaField) }
        }
        val step = stepFor(deltaField)
        // −/+ planos del mismo color del dato (sin el fondo con borde del
        // botón estándar; el ripple mantiene el feedback táctil).
        fun flatBtn(text: String, desc: String, onTap: () -> Unit): Button = Button(this).apply {
            this.text = text
            textSize = 24f
            setTextColor(context.getColor(R.color.neutral_100))
            setBackgroundResource(resolveSelectableBg())
            minimumWidth = (64 * dm).toInt()
            minHeight = (56 * dm).toInt()
            contentDescription = desc
            setOnClickListener { onTap() }
        }
        val minus = flatBtn("−", minusDesc) {
            vm.entrenoDelta(item.uuid, deltaField, -step)
            refreshStepper(item.uuid)
        }.apply {
            if (longStep != null) setOnLongClickListener { vm.entrenoDelta(item.uuid, deltaField, -longStep); refreshStepper(item.uuid); true }
        }
        val plus = flatBtn("+", plusDesc) {
            vm.entrenoDelta(item.uuid, deltaField, step)
            refreshStepper(item.uuid)
        }.apply {
            if (longStep != null) setOnLongClickListener { vm.entrenoDelta(item.uuid, deltaField, longStep); refreshStepper(item.uuid); true }
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(minus)
            addView(shown)
            addView(plus)
        }
    }

    private fun stepFor(field: String): Double = when (field) {
        "kg" -> KG_STEP
        "reps" -> REPS_STEP
        "rir" -> RIR_STEP
        "vel" -> VEL_STEP
        else -> DIF_STEP
    }

    private fun stepperText(label: String, draft: TrainingSetDraft, field: String): String {
        val v = when (field) {
            "kg" -> draft.kg
            "reps" -> draft.reps
            "rir" -> draft.rir
            "velocidadKmh" -> draft.velocidadKmh
            else -> draft.dificultad
        }.ifBlank { "–" }
        return "$label  $v"
    }

    /** Repinta valor + cabecera in-place tras un stepper (sin reconstruir). */
    private fun refreshStepper(uuid: String) {
        val row = vm.entrenoRows.value.find { it.uuid == uuid } ?: return
        val item = SessionFlowState.flattened(vm.entrenoGroups.value).find { it.uuid == uuid }
        rowsBox.findViewWithTag<TextView>("val_${uuid}_kg")?.text = stepperText("kg", row.draft, "kg")
        rowsBox.findViewWithTag<TextView>("val_${uuid}_reps")?.text = stepperText("reps", row.draft, "reps")
        rowsBox.findViewWithTag<TextView>("val_${uuid}_rir")?.text = stepperText("RIR", row.draft, "rir")
        rowsBox.findViewWithTag<TextView>("val_${uuid}_vel")?.text = stepperText("Vel.", row.draft, "velocidadKmh")
        rowsBox.findViewWithTag<TextView>("val_${uuid}_dif")?.text = stepperText("Dif.", row.draft, "dificultad")
        if (item != null) {
            headerButtons[uuid]?.text = headerText(item, row.draft.ejercicio)
        }
    }

    private fun showValueDialog(item: EntrenoItem, draft: TrainingSetDraft, label: String, draftField: String, deltaField: String) {
        val current = when (draftField) {
            "kg" -> draft.kg
            "reps" -> draft.reps
            "rir" -> draft.rir
            "velocidadKmh" -> draft.velocidadKmh
            else -> draft.dificultad
        }
        val input = EditText(this).apply {
            hint = label
            setText(current)
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_FLAG_DECIMAL or
                InputType.TYPE_NUMBER_FLAG_SIGNED
        }
        AlertDialog.Builder(this)
            .setTitle("$label (serie ${item.aparenteOrden})")
            .setView(input)
            .setPositiveButton("OK") { _, _ ->
                vm.setEntrenoValue(item.uuid, deltaField, input.text.toString())
                refreshStepper(item.uuid)
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    /** Confirma el reinicio total (desmarca series y pone descansos a cero). */
    private fun confirmResetEntreno() {
        AlertDialog.Builder(this)
            .setTitle("Reiniciar entreno")
            .setMessage("Todos los descansos vuelven a 00:00 y las series se desmarcan. Los pesos y reps se conservan. ¿Continuar?")
            .setPositiveButton("Reiniciar") { _, _ -> vm.resetEntreno() }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    /** Cabecera: nombre repetido centrado (sin números a la vista). El ✓ ya no
     * se muestra: las realizadas se distinguen por su halo blanco. */
    private fun headerText(item: EntrenoItem, ejercicio: String): String =
        ejercicio.trim().ifBlank { "(sin nombre)" }

    private fun descansoMsFor(text: String): Long =
        runCatching { (text.trim().toDouble() * 1000).toLong() }.getOrDefault(0L).coerceAtLeast(0L)

    /**
     * Tick 250ms: diales por tarjeta, todo in-place (nunca reconstruye: las
     * animaciones sobreviven). Cada dial muestra su propio descanso: solo el
     * dueño del running late (la serie a hacer, abierta y visible); el resto
     * muestra el registrado fijo de su serie. Single-running intacto.
     */
    /**
     * Pinta un dial con su estado actual. Se usa al crearlo (evita el flash
     * de 00:00: sin esto, el valor real llegaba en el siguiente tick... o
     * nunca, si está en pausa) y en cada tick.
     */
    private fun paintDial(uuid: String, dial: RestDialView) {
        val rest = vm.restMs.value
        val running = vm.runningUuid.value
        val paused = vm.pausedUuids.value
        val draft = vm.entrenoRows.value.find { it.uuid == uuid }?.draft
        val isRunningOwner = running == uuid
        dial.ms = if (isRunningOwner) {
            rest[uuid] ?: 0L
        } else {
            descansoMsFor(draft?.descansoSeg ?: "")
        }
        dial.running = isRunningOwner
        dial.paused = !isRunningOwner && uuid in paused
        dial.startable = uuid !in vm.doneUuids.value
    }

    private fun updateTick() {
        if (!::rowsBox.isInitialized) return
        for ((uuid, dial) in dialViews) {
            paintDial(uuid, dial)
        }
    }

    /** Campo Descanso de una tarjeta (valor registrado o —). */
    private fun refreshDescansoField(uuid: String) {
        val field = descansoFields[uuid] ?: return
        val reg = vm.entrenoRows.value.find { it.uuid == uuid }?.draft?.descansoSeg ?: ""
        field.text = if (reg.isBlank()) "Descanso  —" else "Descanso  $reg s"
    }

    companion object {
        private fun navParams() = LinearLayout.LayoutParams(
            0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f,
        )

        /** Fondo ripple del framework para botones planos (sin dependencias). */
        private fun android.content.Context.resolveSelectableBg(): Int {
            val tv = android.util.TypedValue()
            theme.resolveAttribute(android.R.attr.selectableItemBackground, tv, true)
            return tv.resourceId
        }

        /** Título del día: "lunes 14/09/26" (semana en español, sin semana S..). */
        private fun weekdayTitle(fechaIso: String): String = runCatching {
            val d = LocalDate.parse(fechaIso)
            val wd = d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.forLanguageTag("es"))
            "$wd ${d.format(DateTimeFormatter.ofPattern("dd/MM/yy"))}"
        }.getOrDefault(fechaIso)
    }
}
