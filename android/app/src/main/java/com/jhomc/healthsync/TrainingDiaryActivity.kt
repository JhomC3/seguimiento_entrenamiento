package com.jhomc.healthsync

import android.os.Bundle
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.viewModels
import android.app.AlertDialog
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch

/**
 * Diario de entrenamiento (API v1): ver la sesión del día y editarla.
 * Views programáticas como MainActivity (sin Compose/XML). El estado vive en
 * [TrainingDiaryViewModel] (sobrevive a la rotación); esta Activity solo pinta.
 *
 * Reglas honestas de v1 (training-api-contract.md §4-§5):
 * - Guardar reemplaza el día completo: si ya había datos se pide confirmación.
 * - Sin LAN no se guarda ni se borra (la cola offline es v2): error visible.
 * - Sin red pero con visita previa se muestra la última copia ("sin conexión").
 */
class TrainingDiaryActivity : ComponentActivity() {

    private val vm: TrainingDiaryViewModel by viewModels()

    private lateinit var titleView: TextView
    private lateinit var statusView: TextView
    private lateinit var summaryView: TextView
    private lateinit var rowsBox: LinearLayout
    private lateinit var prevButton: Button
    private lateinit var todayButton: Button
    private lateinit var nextButton: Button
    private lateinit var addRowButton: Button
    private lateinit var saveButton: Button
    private lateinit var deleteButton: Button
    private lateinit var templatesButton: Button
    private lateinit var exerciseButton: Button
    private lateinit var undoButton: Button
    // --- B2: alimentación ---
    private lateinit var trainingTabButton: Button
    private lateinit var foodTabButton: Button
    private lateinit var foodBox: LinearLayout
    private lateinit var prefillView: TextView
    private lateinit var pesoInput: EditText
    private lateinit var factorProtInput: EditText
    private lateinit var factorGrasaInput: EditText
    private lateinit var kcalInput: EditText
    private lateinit var foodRowsBox: LinearLayout
    private lateinit var addFoodButton: Button
    private lateinit var saveFoodButton: Button
    private lateinit var deleteFoodButton: Button
    private lateinit var mealTemplatesButton: Button
    private lateinit var newFoodButton: Button
    // --- B3: cardio ---
    private lateinit var cardioTitle: TextView
    private lateinit var cardioBox: LinearLayout
    private var cardioBuiltFor: Pair<String, List<CardioSession>>? = null
    // --- Editor unificado (una sola lista: editar + entrenar) ---
    private lateinit var progressView: TextView
    private var rowsBuiltForFecha: String? = null
    private var rowsBuiltForSession: TrainingSession? = null
    private var rowsBuiltForPreview: Int = 0
    private var rowsBuiltForStructure: Int = -1
    private var catalogNames: List<String> = emptyList()
    private var pendingFocusUuid: String? = null
    private val timerViews = mutableMapOf<String, TextView>()
    private val headerButtons = mutableMapOf<String, Button>()
    private val statusLines = mutableMapOf<String, TextView>()

    private data class FoodRowViews(
        val alimento: AutoCompleteTextView,
        val cantidad: EditText,
    )
    // --- B2 ---
    private val foodRowViews = mutableListOf<FoodRowViews>()
    private var foodBuiltForFecha: String? = null
    private var foodBuiltForNutrition: NutritionDay? = null
    private var foodBuiltForPreview: Int = 0
    private var foodNames: List<String> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        titleView = TextView(this).apply { asTitle() }
        statusView = TextView(this)
        summaryView = TextView(this).apply { asSummary() }
        rowsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val navRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            prevButton = Button(context).apply { text = "◀" }
            todayButton = Button(context).apply { text = "HOY" }
            nextButton = Button(context).apply { text = "▶" }
            addView(prevButton, navParams())
            addView(todayButton, navParams())
            addView(nextButton, navParams())
        }
        prevButton.setOnClickListener { vm.shiftDay(-1) }
        nextButton.setOnClickListener { vm.shiftDay(1) }
        todayButton.setOnClickListener { vm.goToday() }

        addRowButton = Button(this).apply { text = "+ Añadir serie" }
        saveButton = primaryButton("Guardar cambios")
        deleteButton = Button(this).apply { text = "Eliminar día"; asDanger() }
        templatesButton = Button(this).apply { text = "Plantillas" }
        exerciseButton = Button(this).apply { text = "Nuevo ejercicio" }
        undoButton = Button(this).apply { text = "Deshacer" }
        cardioTitle = TextView(this).apply { text = "Cardio"; asSectionTitle() }
        cardioBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        progressView = TextView(this).apply { asSummary() }
        addRowButton.setOnClickListener {
            pendingFocusUuid = null
            vm.addEntrenoRow()
            pendingFocusUuid = vm.entrenoRows.value.lastOrNull()?.uuid
        }
        saveButton.setOnClickListener { confirmSave() }
        deleteButton.setOnClickListener { confirmDelete() }
        templatesButton.setOnClickListener { showTemplatesDialog() }
        exerciseButton.setOnClickListener { showExerciseDialog() }
        undoButton.setOnClickListener { vm.undo() }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(titleView)
            addView(navRow)
            addView(tabsRow())
            addView(statusView)
            addView(progressView)
            addView(rowsBox)
            addView(addRowButton)
            addView(saveButton)
            addView(deleteButton)
            addView(templatesButton)
            addView(exerciseButton)
            addView(cardioTitle)
            addView(cardioBox)
            addView(foodBox())
            addView(undoButton)
            addView(summaryView)
        }
        setContentView(ScrollView(this).apply { addView(root) })

        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.state.collect { render(it) }
            }
        }
        // Rebuild estructural: SIN pre-asignar cachés antes (ese era el freeze:
        // la comparación siempre pasaba y expandir/colapsar no repintaba).
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.structureVersion.collect { rebuildCards() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.expandedUuids.collect { rebuildCards() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.doneUuids.collect { rebuildCards() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.restMs.collect { updateTimers() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                vm.runningUuid.collect { updateTimers() }
            }
        }
    }

    // --- Editor unificado: visibilidad ----------------------------------------

    private fun applyTrainingVisibility(isFood: Boolean) {
        val trainVis = if (isFood) View.GONE else View.VISIBLE
        for (v in listOf(progressView, rowsBox, addRowButton, saveButton, deleteButton, templatesButton, exerciseButton, cardioTitle, cardioBox)) {
            v.visibility = trainVis
        }
    }

    // --- Render ---------------------------------------------------------------

    private fun tabsRow(): LinearLayout {
        trainingTabButton = Button(this).apply { text = "Entrenamiento" }
        foodTabButton = Button(this).apply { text = "Alimentación" }
        trainingTabButton.setOnClickListener { vm.setVista("entrenamiento") }
        foodTabButton.setOnClickListener { vm.setVista("alimentacion") }
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(trainingTabButton, navParams())
            addView(foodTabButton, navParams())
        }
    }

    private fun foodBox(): LinearLayout {
        prefillView = TextView(this).apply { textSize = 13f }
        fun param(hint: String): EditText = EditText(this).apply {
            this.hint = hint
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_FLAG_DECIMAL or
                InputType.TYPE_NUMBER_FLAG_SIGNED
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        pesoInput = param("peso kg")
        factorProtInput = param("factor prot")
        factorGrasaInput = param("factor grasa")
        kcalInput = param("kcal obj")
        val paramsRow1 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(pesoInput); addView(factorProtInput)
        }
        val paramsRow2 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(factorGrasaInput); addView(kcalInput)
        }
        foodRowsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        addFoodButton = Button(this).apply { text = "+ Añadir alimento" }
        saveFoodButton = primaryButton("Guardar día")
        deleteFoodButton = Button(this).apply { text = "Eliminar día"; asDanger() }
        mealTemplatesButton = Button(this).apply { text = "Plantillas comida" }
        newFoodButton = Button(this).apply { text = "Nuevo alimento" }
        addFoodButton.setOnClickListener { addFoodRow(FoodDraft("", "")); stashFood() }
        saveFoodButton.setOnClickListener { confirmFoodSave() }
        deleteFoodButton.setOnClickListener { confirmFoodDelete() }
        mealTemplatesButton.setOnClickListener { showMealTemplatesDialog() }
        newFoodButton.setOnClickListener { showFoodDialog() }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(prefillView)
            addView(paramsRow1)
            addView(paramsRow2)
            addView(foodRowsBox)
            addView(addFoodButton)
            addView(saveFoodButton)
            addView(deleteFoodButton)
            addView(mealTemplatesButton)
            addView(newFoodButton)
            visibility = android.view.View.GONE
        }.also { foodBox = it }
    }

    private fun render(state: DiaryUiState) {
        val session = state.session
        val isFood = state.vista == "alimentacion"
        trainingTabButton.text = if (isFood) "Entrenamiento" else "● Entrenamiento"
        foodTabButton.text = if (isFood) "● Alimentación" else "Alimentación"
        titleView.text = buildString {
            append("DÍA ${state.title()}")
            if (!isFood && session != null && (session.semana > 0 || session.dia.isNotEmpty())) {
                append(" · S${session.semana} ${session.dia}")
            }
            if (state.fecha in state.dots) append(" ●")
        }
        when {
            state.loading -> statusView.asStatus("Cargando…", StatusKind.NOTICE)
            state.saving -> statusView.asStatus("Guardando…", StatusKind.NOTICE)
            state.error != null -> statusView.asStatus("Error: ${state.error}", StatusKind.ERROR)
            state.notice != null -> statusView.asStatus(state.notice, StatusKind.SUCCESS)
            state.stale -> statusView.asStatus("Sin conexión: última copia guardada.", StatusKind.NOTICE)
            state.pending > 0 -> statusView.asStatus(
                "${state.pending} cambio(s) pendientes de envío.", StatusKind.NOTICE,
            )
            else -> statusView.asStatus("", StatusKind.NOTICE)
        }
        val busy = state.loading || state.saving
        for (b in listOf(saveButton, deleteButton, addRowButton, templatesButton, exerciseButton,
            undoButton, prevButton, nextButton, todayButton, trainingTabButton, foodTabButton,
            addFoodButton, saveFoodButton, deleteFoodButton, mealTemplatesButton, newFoodButton)) {
            b.isEnabled = !busy
        }
        // Visibilidad por pestaña (mismo `vista` que el Diario web).
        val foodVis = if (isFood) android.view.View.VISIBLE else android.view.View.GONE
        foodBox.visibility = foodVis
        applyTrainingVisibility(isFood)
        // Al cambiar de día/sesión/preview, reagrupa (nunca mientras teclea).
        if (!isFood && !busy && (state.fecha != rowsBuiltForFecha || session !== rowsBuiltForSession || state.previewId != rowsBuiltForPreview)) {
            vm.ensureEntrenoBuilt()
            rebuildCards()
            rowsBuiltForFecha = state.fecha
            rowsBuiltForSession = session
            rowsBuiltForPreview = state.previewId
            rowsBuiltForStructure = vm.structureVersion.value
        }

        if (state.catalog.map { it.ejercicio } != catalogNames) {
            catalogNames = state.catalog.map { it.ejercicio }
        }
        if (isFood) renderFood(state, busy)
        if (!isFood) renderCardio(state, busy)
        summaryView.text = if (isFood) {
            foodSummaryOf(state)
        } else if (state.suggestion?.tipo == "descanso" && session?.hasData != true) {
            state.suggestion.explicacion
        } else {
            summaryOf(session)
        }
    }

    // --- Editor unificado: tarjetas ---------------------------------------------

    /**
     * Reconstruye las tarjetas. Solo en cambios estructurales (versión del VM,
     * expandidas, done, día/sesión): los steppers actualizan in-place y el
     * tick solo repinta números, así no hay saltos de scroll.
     */
    private fun rebuildCards() {
        if (!::rowsBox.isInitialized) return
        rowsBox.removeAllViews()
        timerViews.clear()
        headerButtons.clear()
        statusLines.clear()
        val rows = vm.entrenoRows.value
        val groups = vm.entrenoGroups.value
        val done = vm.doneUuids.value
        val expanded = vm.expandedUuids.value
        val (total, doneCount, pending) = SessionFlowState.progress(groups, done)
        progressView.text = if (total == 0 && rows.all { it.draft.isBlank() }) {
            "Escribe el ejercicio y ajusta con +."
        } else {
            "Serie $doneCount/$total · $pending pendientes"
        }
        rowsBuiltForStructure = vm.structureVersion.value
        val byUuid = SessionFlowState.flattened(groups).associateBy { it.uuid }
        for (row in rows) {
            rowsBox.addView(rowCard(row, byUuid[row.uuid], row.uuid in expanded, row.uuid in done))
        }
        updateTimers()
        // Foco pendiente tras añadir serie o transición blanco→visible.
        pendingFocusUuid?.let { uuid ->
            pendingFocusUuid = null
            rowsBox.findViewWithTag<AutoCompleteTextView>("ex_$uuid")?.requestFocus()
        }
    }

    private fun rowCard(row: EntrenoRow, item: EntrenoItem?, isExpanded: Boolean, isDone: Boolean): LinearLayout {
        val dm = resources.displayMetrics.density
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 8, 0, 8)
        }
        // Nombre del ejercicio: igual que siempre (autocompletado con catálogo).
        val adapter = ArrayAdapter(this, android.R.layout.simple_dropdown_item_1line, catalogNames)
        val ejercicio = AutoCompleteTextView(this).apply {
            asCellInput()
            hint = "Ejercicio"
            setText(row.draft.ejercicio)
            setAdapter(adapter)
            threshold = 1
            tag = "ex_${row.uuid}"
        }
        card.addView(ejercicio)
        var focused = false
        ejercicio.setOnFocusChangeListener { _, hasFocus ->
            if (!hasFocus && !focused) {
                focused = true
                val structural = vm.setEntrenoExercise(row.uuid, ejercicio.text.toString())
                if (structural) pendingFocusUuid = row.uuid
            } else if (hasFocus) {
                focused = false
            }
        }
        val headerRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        if (item == null) {
            val hint = TextView(this).apply {
                text = "Nueva serie · escribe el ejercicio"
                asSummary()
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            }
            headerRow.addView(hint)
        } else {
            val headerBtn = Button(this).apply {
                text = item.summaryLine(formatMmSsFromMs(vm.restMs.value[item.uuid] ?: 0L), isDone)
                minHeight = (64 * dm).toInt()
                isAllCaps = false
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                contentDescription = "Serie ${item.aparenteOrden} ${item.ejercicio}: expandir o colapsar"
                setOnClickListener { vm.toggleExpand(item.uuid) }
            }
            headerButtons[item.uuid] = headerBtn
            headerRow.addView(headerBtn)
        }
        val remove = Button(this).apply { text = "Quitar"; asDanger() }
        remove.contentDescription = "Quitar serie"
        remove.setOnClickListener { vm.removeEntrenoRow(row.uuid) }
        headerRow.addView(remove)
        card.addView(headerRow)
        if (item != null && isExpanded) {
            addExpandedPanel(card, item, row.draft, isDone)
        }
        return card
    }

    private fun addExpandedPanel(card: LinearLayout, item: EntrenoItem, draft: TrainingSetDraft, isDone: Boolean) {
        val dm = resources.displayMetrics.density
        val timerView = TextView(this).apply {
            text = formatMmSsFromMs(vm.restMs.value[item.uuid] ?: 0L)
            textSize = 48f
            gravity = Gravity.CENTER
            // Sin liveRegion: no spamea TalkBack con cada tick.
        }
        timerViews[item.uuid] = timerView
        card.addView(timerView)
        val timerRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val startBtn = Button(this).apply {
            text = "INICIAR"
            minHeight = (64 * dm).toInt()
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            contentDescription = "Iniciar descanso serie ${item.aparenteOrden}"
            setOnClickListener { vm.timerStart(item.uuid) }
        }
        val pauseBtn = Button(this).apply {
            text = "PAUSAR"
            minHeight = (64 * dm).toInt()
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            contentDescription = "Pausar descanso serie ${item.aparenteOrden}"
            setOnClickListener { vm.timerPause(item.uuid) }
        }
        timerRow.addView(startBtn)
        timerRow.addView(pauseBtn)
        card.addView(timerRow)
        val status = TextView(this).apply { asSummary() }
        statusLines[item.uuid] = status
        card.addView(status)
        if (item.isHiit()) {
            card.addView(stepperRow(item, draft, "Vel.", "velocidadKmh", "vel", "Bajar velocidad", "Subir velocidad"))
            card.addView(stepperRow(item, draft, "Dif.", "dificultad", "dif", "Bajar dificultad", "Subir dificultad"))
        } else {
            card.addView(stepperRow(item, draft, "kg", "kg", "kg", "Bajar peso", "Subir peso", longStep = KG_STEP_LONG))
            card.addView(stepperRow(item, draft, "reps", "reps", "reps", "Bajar repeticiones", "Subir repeticiones"))
            card.addView(stepperRow(item, draft, "RIR", "rir", "rir", "Bajar RIR", "Subir RIR"))
        }
        val resetBtn = Button(this).apply {
            text = "Reiniciar descanso (solo display, conserva historial)"
            asDanger()
            textSize = 12f
            contentDescription = "Reiniciar display del cronómetro sin borrar el historial"
            setOnClickListener { vm.timerReset(item.uuid) }
        }
        card.addView(resetBtn)
        val doneBtn = primaryButton(if (isDone) "Hecha ✓ (toca para desmarcar)" else "Serie hecha + descansar")
        doneBtn.contentDescription = "Marcar serie hecha y descansar"
        doneBtn.minHeight = (64 * dm).toInt()
        doneBtn.setOnClickListener {
            if (item.uuid in vm.doneUuids.value) vm.toggleDone(item.uuid) else vm.completeSet(item.uuid)
        }
        card.addView(doneBtn)
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
        val minus = Button(this).apply {
            text = "−"
            textSize = 24f
            minimumWidth = (64 * dm).toInt()
            minHeight = (56 * dm).toInt()
            contentDescription = minusDesc
            setOnClickListener {
                vm.entrenoDelta(item.uuid, deltaField, -step)
                refreshStepper(item.uuid)
            }
            if (longStep != null) setOnLongClickListener { vm.entrenoDelta(item.uuid, deltaField, -longStep); refreshStepper(item.uuid); true }
        }
        val plus = Button(this).apply {
            text = "+"
            textSize = 24f
            minimumWidth = (64 * dm).toInt()
            minHeight = (56 * dm).toInt()
            contentDescription = plusDesc
            setOnClickListener {
                vm.entrenoDelta(item.uuid, deltaField, step)
                refreshStepper(item.uuid)
            }
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
            headerButtons[uuid]?.text = item.summaryLine(
                formatMmSsFromMs(vm.restMs.value[uuid] ?: 0L), uuid in vm.doneUuids.value,
            )
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

    /** Tick 250ms: solo repinta números + líneas de estado (nunca reconstruye). */
    private fun updateTimers() {
        if (!::rowsBox.isInitialized) return
        val rest = vm.restMs.value
        val running = vm.runningUuid.value
        val done = vm.doneUuids.value
        val byUuid = SessionFlowState.flattened(vm.entrenoGroups.value).associateBy { it.uuid }
        for ((uuid, tv) in timerViews) {
            tv.text = formatMmSsFromMs(rest[uuid] ?: 0L)
        }
        for ((uuid, btn) in headerButtons) {
            val item = byUuid[uuid] ?: continue
            // Con apertura múltiple el tick no toca expandidas (las refresca su
            // propio rebuild); las colapsadas muestran su tiempo acumulado.
            if (uuid !in vm.expandedUuids.value) {
                btn.text = item.summaryLine(formatMmSsFromMs(rest[uuid] ?: 0L), uuid in done)
            }
        }
        for ((uuid, line) in statusLines) {
            val ms = rest[uuid] ?: 0L
            line.text = when {
                running == uuid -> "Descanso corriendo… solo local, nada enviado."
                ms > 0 -> "Descanso ${formatMmSsFromMs(ms)} pausado · solo local, nada enviado."
                else -> "Sin descanso medido."
            }
        }
    }

    private fun summaryOf(session: TrainingSession?): String {
        if (session == null || !session.hasData) return "Sin entrenamiento guardado para este día."
        return session.sets.joinToString("\n") { s ->
            if (s.isHiit()) {
                "${s.setOrden}. ${s.ejercicio} ${numToText(s.velocidadKmh)} km/h · dif ${numToText(s.dificultad)}"
            } else {
                val rm = if (s.rm != null) " (RM ${s.rm})" else ""
                "${s.setOrden}. ${s.ejercicio} ${numToText(s.kg)}×${numToText(s.reps)} RIR ${numToText(s.rir)}$rm"
            }
        }
    }

    // --- Guardar / borrar ----------------------------------------------------------

    private fun confirmSave() {
        val drafts = vm.entrenoDrafts()
        if (drafts.isEmpty()) {
            statusView.asStatus("Error: añade al menos una serie.", StatusKind.ERROR)
            return
        }
        val hadData = vm.state.value.session?.hasData == true
        if (hadData) {
            AlertDialog.Builder(this)
                .setTitle("Reemplazar el día")
                .setMessage("Este día ya tiene series guardadas. Guardar las reemplaza por completo. ¿Continuar?")
                .setPositiveButton("Reemplazar") { _, _ -> vm.save(drafts) }
                .setNegativeButton("Cancelar", null)
                .show()
        } else {
            vm.save(drafts)
        }
    }

    private fun confirmDelete() {
        AlertDialog.Builder(this)
            .setTitle("Eliminar día")
            .setMessage("Se borran todas las series de este día. ¿Continuar?")
            .setPositiveButton("Eliminar") { _, _ -> vm.deleteDay() }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    // --- B1: plantillas / alta de ejercicio ---------------------------------------

    private fun showTemplatesDialog() {
        vm.ensureTemplates()
        val state = vm.state.value
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 16, 24, 16)
        }
        // Guardar el día visible como plantilla (upsert por nombre, como la web).
        val nameInput = EditText(this).apply { hint = "Nombre del entreno" }
        val saveAs = Button(this).apply { text = "Guardar día como plantilla" }
        box.addView(nameInput)
        box.addView(saveAs)
        val dialog = AlertDialog.Builder(this)
            .setTitle("Plantillas (${state.templates.size})")
            .setView(ScrollView(this).apply { addView(box) })
            .setNegativeButton("Cerrar", null)
            .create()
        saveAs.setOnClickListener {
            val nombre = nameInput.text.toString().trim()
            val ejercicios = vm.currentDrafts().map { it.ejercicio }.filter { it.isNotBlank() }
            if (nombre.isBlank()) {
                nameInput.error = "Ponle nombre al entreno."
                return@setOnClickListener
            }
            if (ejercicios.isEmpty()) {
                statusView.asStatus("Error: el día no tiene ejercicios que guardar.", StatusKind.ERROR)
                return@setOnClickListener
            }
            dialog.dismiss()
            vm.saveAsTemplate(nombre, ejercicios)
        }
        if (state.templates.isEmpty()) {
            box.addView(TextView(this).apply { text = "Sin plantillas. Guarda el día actual con un nombre." })
        }
        for (tpl in state.templates) {
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            val label = TextView(this).apply {
                text = "${tpl.nombre} (${tpl.clasificacion}, ${tpl.ejercicios.size})"
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            }
            val apply = Button(this).apply { text = "Aplicar" }
            apply.setOnClickListener {
                dialog.dismiss()
                vm.applyTemplate(tpl.id, tpl.nombre)
            }
            row.addView(label)
            row.addView(apply)
            box.addView(row)
        }
        dialog.show()
    }

    private fun showExerciseDialog() {
        val state = vm.state.value
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 16, 24, 16)
        }
        val nombre = EditText(this).apply { hint = "Ejercicio" }
        val groups = (state.catalog.map { it.grupoMuscular } +
            state.categories.flatMap { it.muscles }).filter { it.isNotBlank() }.distinct().sorted()
        val grupo = AutoCompleteTextView(this).apply {
            asCellInput()
            hint = "Grupo muscular"
            setAdapter(ArrayAdapter(this@TrainingDiaryActivity, android.R.layout.simple_dropdown_item_1line, groups))
            threshold = 1
        }
        box.addView(nombre)
        box.addView(grupo)
        val categoryNames = state.categories.map { it.name }
        val categoriaPicker: android.view.View
        val categoriaInput: EditText?
        val categoriaSpinner: Spinner?
        if (categoryNames.isNotEmpty()) {
            categoriaSpinner = Spinner(this).apply {
                adapter = ArrayAdapter(
                    this@TrainingDiaryActivity,
                    android.R.layout.simple_spinner_dropdown_item,
                    categoryNames,
                )
            }
            categoriaInput = null
            categoriaPicker = categoriaSpinner
        } else {
            // Sin catálogo (sin red y sin caché): texto libre, el servidor valida.
            categoriaInput = EditText(this).apply { hint = "Categoría (EMPUJE…)" }
            categoriaSpinner = null
            categoriaPicker = categoriaInput
        }
        box.addView(categoriaPicker)
        AlertDialog.Builder(this)
            .setTitle("Nuevo ejercicio")
            .setView(ScrollView(this).apply { addView(box) })
            .setPositiveButton("Crear") { _, _ ->
                val categoria = categoriaSpinner?.selectedItem?.toString()
                    ?: categoriaInput?.text.toString().trim()
                vm.createExercise(
                    nombre.text.toString().trim(),
                    grupo.text.toString().trim(),
                    categoria.trim(),
                )
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    // --- B3: cardio -----------------------------------------------------------

    private fun renderCardio(state: DiaryUiState, busy: Boolean) {
        val key = state.fecha to state.cardio
        if (!busy && cardioBuiltFor != key) {
            cardioBuiltFor = key
            cardioBox.removeAllViews()
            if (state.cardio.isEmpty()) {
                cardioBox.addView(TextView(this).apply {
                    text = "Sin sesiones de cardio este día."
                    asSummary()
                })
                return
            }
            for (session in state.cardio) {
                cardioBox.addView(cardioCard(session, busy))
            }
        }
    }

    private fun numInput(hint: String, value: String): EditText = EditText(this).apply {
        this.hint = hint
        setText(value)
        inputType = InputType.TYPE_CLASS_NUMBER or
            InputType.TYPE_NUMBER_FLAG_DECIMAL or
            InputType.TYPE_NUMBER_FLAG_SIGNED
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
    }

    private fun cardioCard(session: CardioSession, busy: Boolean): LinearLayout {
        val title = TextView(this).apply {
            text = "${session.titulo} · ${session.duracionMin} min"
            asSummary()
        }
        val velocidad = numInput("vel. km/h", foodNumToText(session.velocidadKmh))
        val inclinacion = numInput("incl. %", foodNumToText(session.inclinacionPct))
        val notas = EditText(this).apply {
            hint = "Notas"
            setText(session.notas)
        }
        val nums = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(velocidad); addView(inclinacion)
        }
        val save = Button(this).apply {
            text = "Guardar"
            isEnabled = !busy
            setOnClickListener {
                vm.annotateCardio(
                    session.hcId,
                    velocidad.text.toString().trim(),
                    inclinacion.text.toString().trim(),
                    notas.text.toString().trim(),
                )
            }
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 8, 0, 8)
            addView(title)
            addView(nums)
            addView(notas)
            addView(save)
        }
    }

    // --- B2: alimentación -----------------------------------------------------------
    private fun renderFood(state: DiaryUiState, busy: Boolean) {
        if (state.foods.map { it.nombre } != foodNames) {
            foodNames = state.foods.map { it.nombre }
        }
        val day = state.nutrition
        prefillView.text = if (day?.prefilled == true) {
            "Datos del ${day.prefillSource} (heredados, sin guardar)."
        } else {
            ""
        }
        prefillView.visibility = if (day?.prefilled == true) android.view.View.VISIBLE else android.view.View.GONE
        if (!busy && (state.fecha != foodBuiltForFecha || day !== foodBuiltForNutrition || state.nutritionPreviewId != foodBuiltForPreview)) {
            rebuildFoodRows(state)
        }
    }

    private fun rebuildFoodRows(state: DiaryUiState) {
        foodRowsBox.removeAllViews()
        foodRowViews.clear()
        val day = state.nutrition
        val buffered = vm.nutritionDraftBuffer.let { buf -> buf?.takeIf { it.first == state.fecha }?.second }
        val drafts = buffered
            ?: day?.entradas?.map { FoodDraft(it.alimento, foodNumToText(it.cantidadG)) }
                ?.ifEmpty { listOf(FoodDraft("", "")) }
            ?: listOf(FoodDraft("", ""))
        drafts.forEach { addFoodRow(it) }
        if (day != null) {
            pesoInput.setText(foodNumToText(day.parametros.pesoKg))
            factorProtInput.setText(foodNumToText(day.parametros.factorProteina))
            factorGrasaInput.setText(foodNumToText(day.parametros.factorGrasa))
            kcalInput.setText(foodNumToText(day.parametros.kcalObjetivo))
        }
        foodBuiltForFecha = state.fecha
        foodBuiltForNutrition = day
        foodBuiltForPreview = state.nutritionPreviewId
    }

    private fun addFoodRow(draft: FoodDraft) {
        if (foodRowViews.size >= TRAINING_API_MAX_SETS) {
            statusView.asStatus("Máximo $TRAINING_API_MAX_SETS alimentos por día.", StatusKind.ERROR)
            return
        }
        val adapter = ArrayAdapter(this, android.R.layout.simple_dropdown_item_1line, foodNames)
        val alimento = AutoCompleteTextView(this).apply {
            asCellInput()
            hint = "Alimento"
            setText(draft.alimento)
            setAdapter(adapter)
            threshold = 1
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 2f)
        }
        val cantidad = EditText(this).apply {
            hint = "g"
            setText(draft.cantidadG)
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_FLAG_DECIMAL or
                InputType.TYPE_NUMBER_FLAG_SIGNED
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val remove = Button(this).apply { text = "Quitar"; asDanger() }
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 8, 0, 8)
            addView(alimento); addView(cantidad); addView(remove)
        }
        foodRowsBox.addView(card)
        val holders = FoodRowViews(alimento, cantidad)
        foodRowViews.add(holders)
        remove.setOnClickListener {
            foodRowsBox.removeView(card)
            foodRowViews.remove(holders)
            stashFood()
        }
        val watcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun afterTextChanged(s: Editable?) = stashFood()
        }
        alimento.addTextChangedListener(watcher)
        cantidad.addTextChangedListener(watcher)
    }

    private fun collectFoodDrafts(): List<FoodDraft> = foodRowViews.map {
        FoodDraft(it.alimento.text.toString().trim(), it.cantidad.text.toString().trim())
    }

    private fun stashFood() {
        vm.nutritionDraftBuffer = vm.state.value.fecha to collectFoodDrafts()
    }

    private fun foodParams(): Map<String, String> = mapOf(
        "peso_kg" to pesoInput.text.toString(),
        "factor_proteina" to factorProtInput.text.toString(),
        "factor_grasa" to factorGrasaInput.text.toString(),
        "kcal_objetivo" to kcalInput.text.toString(),
    )

    private fun confirmFoodSave() {
        val drafts = collectFoodDrafts().filter { it.alimento.isNotBlank() || it.cantidadG.isNotBlank() }
        if (drafts.isEmpty()) {
            statusView.asStatus("Error: añade al menos un alimento.", StatusKind.ERROR)
            return
        }
        if (vm.state.value.nutrition?.hasData == true) {
            AlertDialog.Builder(this)
                .setTitle("Reemplazar el día")
                .setMessage("Este día ya tiene alimentación guardada. Guardar la reemplaza por completo. ¿Continuar?")
                .setPositiveButton("Reemplazar") { _, _ -> vm.saveNutrition(drafts, foodParams()) }
                .setNegativeButton("Cancelar", null)
                .show()
        } else {
            vm.saveNutrition(drafts, foodParams())
        }
    }

    private fun confirmFoodDelete() {
        AlertDialog.Builder(this)
            .setTitle("Eliminar día")
            .setMessage("Se borra la alimentación de este día (los parámetros se conservan). ¿Continuar?")
            .setPositiveButton("Eliminar") { _, _ -> vm.deleteNutritionDay() }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun foodSummaryOf(state: DiaryUiState): String {
        val day = state.nutrition ?: return "Sin alimentación guardada para este día."
        if (!day.hasData && !day.prefilled) return "Sin alimentación guardada para este día."
        val labels = state.nutrientLabels.associate { it.name to it.label }
        return NUTRIENT_FIELDS.joinToString("\n") { f ->
            val label = labels[f] ?: f
            val got = day.consumido[f] ?: 0.0
            val want = day.objetivo[f] ?: 0.0
            "$label: ${foodNumToText(got)}/${foodNumToText(want)}"
        } + "\nCantidad: ${foodNumToText(day.consumido["cantidad_g"])} g"
    }

    private fun showMealTemplatesDialog() {
        vm.ensureMealTemplates()
        val state = vm.state.value
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 16, 24, 16)
        }
        val nameInput = EditText(this).apply { hint = "Nombre de la plantilla" }
        val saveAs = Button(this).apply { text = "Guardar día como plantilla" }
        box.addView(nameInput)
        box.addView(saveAs)
        val dialog = AlertDialog.Builder(this)
            .setTitle("Plantillas comida (${state.mealTemplates.size})")
            .setView(ScrollView(this).apply { addView(box) })
            .setNegativeButton("Cerrar", null)
            .create()
        saveAs.setOnClickListener {
            val nombre = nameInput.text.toString().trim()
            val entradas = collectFoodDrafts().filter { it.alimento.isNotBlank() }
            if (nombre.isBlank()) {
                nameInput.error = "Ponle nombre a la plantilla."
                return@setOnClickListener
            }
            if (entradas.isEmpty()) {
                statusView.asStatus("Error: el día no tiene alimentos que guardar.", StatusKind.ERROR)
                return@setOnClickListener
            }
            dialog.dismiss()
            vm.saveMealTemplate(nombre, entradas)
        }
        if (state.mealTemplates.isEmpty()) {
            box.addView(TextView(this).apply { text = "Sin plantillas. Guarda el día actual con un nombre." })
        }
        for (tpl in state.mealTemplates) {
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            val label = TextView(this).apply {
                text = "${tpl.nombre} (${tpl.alimentos.size})"
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            }
            val apply = Button(this).apply { text = "Aplicar" }
            apply.setOnClickListener {
                dialog.dismiss()
                vm.applyMealTemplate(tpl.id, tpl.nombre)
            }
            row.addView(label)
            row.addView(apply)
            box.addView(row)
        }
        dialog.show()
    }

    private fun showFoodDialog() {
        val state = vm.state.value
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 16, 24, 16)
        }
        val nombre = EditText(this).apply { hint = "Alimento (por 100 g)" }
        val categoria = EditText(this).apply { hint = "Categoría" }
        box.addView(nombre)
        box.addView(categoria)
        val labels = state.nutrientLabels.associate { it.name to it.label }
        val inputs = NUTRIENT_FIELDS.associateWith { field ->
            EditText(this).apply {
                hint = labels[field] ?: field
                setText("0")
                inputType = InputType.TYPE_CLASS_NUMBER or
                    InputType.TYPE_NUMBER_FLAG_DECIMAL or
                    InputType.TYPE_NUMBER_FLAG_SIGNED
            }.also { box.addView(it) }
        }
        AlertDialog.Builder(this)
            .setTitle("Nuevo alimento")
            .setView(ScrollView(this).apply { addView(box) })
            .setPositiveButton("Crear") { _, _ ->
                val nutrients = NUTRIENT_FIELDS.associateWith { field ->
                    inputs[field]?.text.toString().trim().replace(",", ".").toDoubleOrNull() ?: -1.0
                }
                vm.createFood(
                    nombre.text.toString().trim(),
                    categoria.text.toString().trim(),
                    nutrients,
                )
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    companion object {
        private fun navParams() = LinearLayout.LayoutParams(
            0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f,
        )

        private fun numToText(v: Double?): String {
            if (v == null) return ""
            return if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()
        }

        private fun foodNumToText(v: Double?): String = numToText(v)
    }
}
