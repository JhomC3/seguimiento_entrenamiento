package com.jhomc.healthsync

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jhomc.healthsync.data.RestIntervalEntity
import com.jhomc.healthsync.data.RestDao
import com.jhomc.healthsync.data.SecureTargetStore
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class DiaryUiState(
    val fecha: String = LocalDate.now().toString(),
    val vista: String = "entrenamiento",
    val loading: Boolean = true,
    val session: TrainingSession? = null,
    val stale: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val saving: Boolean = false,
    val catalog: List<CatalogExercise> = emptyList(),
    val categories: List<CatalogCategory> = emptyList(),
    val templates: List<TrainingTemplate> = emptyList(),
    /** Crece con cada preview aplicado: la Activity reconstruye filas con él. */
    val previewId: Int = 0,
    // --- B2: nutrición ---
    val nutrition: NutritionDay? = null,
    val foods: List<FoodItem> = emptyList(),
    val nutrientLabels: List<NutrientLabel> = emptyList(),
    val mealTemplates: List<MealTemplate> = emptyList(),
    val nutritionPreviewId: Int = 0,
    // --- Rueda de sugerencia ---
    val suggestion: Suggestion? = null,
    // --- B3: cardio ---
    val cardio: List<CardioSession> = emptyList(),
    // --- B4: offline + dots ---
    val pending: Int = 0,
    val dots: Set<String> = emptySet(),
) {
    fun title(): String = runCatching {
        LocalDate.parse(fecha).format(DateTimeFormatter.ofPattern("dd/MM/yy"))
    }.getOrDefault(fecha)
}

/**
 * Estado del diario con el mismo patrón que SyncService.progress: la Activity
 * observa [state] y pinta; este ViewModel sobrevive a la rotación (la
 * MainActivity sin ViewModel pierde el panel al girar; aquí no).
 * Red siempre en IO; la escritura es online-only en v1 (ver TrainingRepository).
 */
class TrainingDiaryViewModel(application: Application) : AndroidViewModel(application) {

    private val store = SecureTargetStore(application)
    private val repository: TrainingRepository by lazy {
        val db = HealthDatabaseBuilder.get(application)
        TrainingRepository(db.trainingCacheDao(), db.offlineDao())
    }

    private val _state = MutableStateFlow(DiaryUiState())
    val state: StateFlow<DiaryUiState> = _state.asStateFlow()

    /**
     * Borrador sin guardar por fecha (lo rellena la Activity en cada tecla).
     * Sobrevive a la rotación y a los paseos entre días; se descarta al
     * guardar/borrar con éxito (entonces manda el estado del servidor).
     */
    var draftBuffer: Pair<String, List<TrainingSetDraft>>? = null

    // --- Modo entreno (Fase 1, local-first, sin backend) ----------------------
    // Relojes inyectables para tests (defecto = relojes reales).
    internal var clockWall: () -> Long = { System.currentTimeMillis() }
    internal var clockElapsed: () -> Long = { SystemClock.elapsedRealtime() }
    internal var restDaoOverride: RestDao? = null

    private val restTimer = RestTimer()
    private var tickerJob: Job? = null
    private var entrenoIds: List<String> = emptyList()
    private var entrenoIdsFecha: String? = null
    private var orphanSweepDone = false

    private val _modoEntreno = MutableStateFlow(false)
    val modoEntreno: StateFlow<Boolean> = _modoEntreno.asStateFlow()
    private val _entrenoGroups = MutableStateFlow<List<EntrenoGroup>>(emptyList())
    val entrenoGroups: StateFlow<List<EntrenoGroup>> = _entrenoGroups.asStateFlow()
    private val _expandedUuid = MutableStateFlow<String?>(null)
    val expandedUuid: StateFlow<String?> = _expandedUuid.asStateFlow()
    private val _doneUuids = MutableStateFlow<Set<String>>(emptySet())
    val doneUuids: StateFlow<Set<String>> = _doneUuids.asStateFlow()
    private val _restMs = MutableStateFlow<Map<String, Long>>(emptyMap())
    val restMs: StateFlow<Map<String, Long>> = _restMs.asStateFlow()
    private val _runningUuid = MutableStateFlow<String?>(null)
    val runningUuid: StateFlow<String?> = _runningUuid.asStateFlow()

    private fun restDao(): RestDao =
        restDaoOverride ?: HealthDatabaseBuilder.get(getApplication()).restDao()

    init {
        load(LocalDate.now().toString())
        viewModelScope.launch(Dispatchers.IO) {
            // Barrido único de huérfanos: abiertos de sesiones anteriores no se
            // reanudan; se marcan ABANDONADO con el tick actual.
            if (!orphanSweepDone) {
                orphanSweepDone = true
                runCatching { restDao().abandonAllOpen(clockWall(), clockElapsed()) }
            }
        }
    }

    /** Borradores actuales (misma fuente que rebuildRows de la Activity). */
    fun currentDrafts(): List<TrainingSetDraft> {
        val fecha = _state.value.fecha
        val buffered = draftBuffer?.takeIf { it.first == fecha }?.second
        return buffered
            ?: _state.value.session?.sets?.map {
                TrainingSetDraft(
                    it.ejercicio, numText(it.kg), numText(it.reps),
                    numText(it.rir), numText(it.descansoSeg),
                    numText(it.velocidadKmh), numText(it.dificultad),
                )
            }?.ifEmpty { listOf(TrainingSetDraft("", "", "", "", "")) }
            ?: listOf(TrainingSetDraft("", "", "", "", ""))
    }

    fun setModoEntreno(enabled: Boolean) {
        if (_modoEntreno.value == enabled) return
        _modoEntreno.value = enabled
        if (enabled) {
            ensureEntrenoBuilt()
            startTicker()
            viewModelScope.launch(Dispatchers.IO) {
                // Semilla de acumulados desde intervalos CERRADOS (sin bloquear).
                val fecha = _state.value.fecha
                val closed = runCatching { restDao().forFecha(fecha) }.getOrDefault(emptyList())
                    .filter { it.estado == "CERRADO" && it.endElapsedMs != null }
                for (c in closed) {
                    val dur = (c.endElapsedMs!! - c.startElapsedMs).coerceAtLeast(0)
                    restTimer.seedAccum(c.clientSetUuid, dur)
                }
                refreshRestMs()
            }
        } else {
            tickerJob?.cancel()
            tickerJob = null
        }
    }

    /** Reconstruye grupos preservando UUIDs por índice; resetea expand/done si cambia el día. */
    fun ensureEntrenoBuilt() {
        val fecha = _state.value.fecha
        if (entrenoIdsFecha != fecha) {
            entrenoIds = emptyList()
            entrenoIdsFecha = fecha
            _doneUuids.value = emptySet()
            _expandedUuid.value = null
            restTimer.clearAccum(emptySet())
        }
        val drafts = currentDrafts()
        val (groups, outIds) = SessionFlowState.build(drafts, entrenoIds)
        entrenoIds = outIds
        restTimer.clearAccum(outIds.toSet())
        _entrenoGroups.value = groups
        // Si lo expandido desapareció (borrado en Editor), colapsa.
        val flat = SessionFlowState.flattened(groups).map { it.uuid }.toSet()
        if (_expandedUuid.value !in flat) {
            _expandedUuid.value = SessionFlowState.nextPending(groups, _doneUuids.value, null)?.uuid
        }
        refreshRestMs()
    }

    fun expandUuid(uuid: String?) {
        _expandedUuid.value = uuid
    }

    fun toggleDone(uuid: String) {
        _doneUuids.value = SessionFlowState.toggleDone(_doneUuids.value, uuid)
        persistProgressive()
    }

    /**
     * Botón principal: marca hecha (idempotente: solo añade), colapsa,
     * auto-expande la siguiente pendiente y auto-arranca su descanso.
     */
    fun completeSet(uuid: String) {
        if (uuid !in _doneUuids.value) _doneUuids.value = _doneUuids.value + uuid
        persistProgressive()
        val next = SessionFlowState.nextPending(_entrenoGroups.value, _doneUuids.value, uuid)
        _expandedUuid.value = next?.uuid
        if (next != null) timerStart(next.uuid)
    }

    /** Borradores no vacíos listos para el Guardar final único (con confirm). */
    fun entrenoDrafts(): List<TrainingSetDraft> = currentDrafts().filter { !it.isBlank() }

    fun entrenoDelta(uuid: String, field: String, delta: Double) {
        val fecha = _state.value.fecha
        val drafts = currentDrafts().toMutableList()
        val index = entrenoIds.indexOf(uuid)
        if (index !in drafts.indices) return
        val cur = drafts[index]
        fun shift(raw: String, step: Double): String {
            val base = raw.trim().replace(",", ".").toDoubleOrNull() ?: 0.0
            val next = (base + step).coerceAtLeast(0.0)
            return if (next % 1.0 == 0.0) next.toLong().toString() else next.toString()
        }
        drafts[index] = when (field) {
            "kg" -> cur.copy(kg = shift(cur.kg, delta))
            "reps" -> cur.copy(reps = shift(cur.reps, delta))
            "rir" -> cur.copy(rir = shift(cur.rir, delta))
            "vel" -> cur.copy(velocidadKmh = shift(cur.velocidadKmh, delta))
            "dif" -> cur.copy(dificultad = shift(cur.dificultad, delta))
            else -> return
        }
        draftBuffer = fecha to drafts
        // Solo stash local aquí (sin enqueue: evita ráfagas al rate-limit).
        val (groups, outIds) = SessionFlowState.build(drafts, entrenoIds)
        entrenoIds = outIds
        _entrenoGroups.value = groups
    }

    fun timerStart(uuid: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val wall = clockWall()
            val elapsed = clockElapsed()
            // Invariante single-running: cierra lo anterior primero.
            restTimer.pendingClose()?.let { toClose ->
                runCatching { restDao().close(toClose.intervalId, wall, elapsed) }
                restTimer.onClosed(elapsed)
            }
            if (restTimer.runningUuid() == uuid) {
                refreshRestMs()
                return@launch
            }
            val item = SessionFlowState.flattened(_entrenoGroups.value).find { it.uuid == uuid }
            val id = runCatching {
                restDao().insert(
                    RestIntervalEntity(
                        fecha = _state.value.fecha,
                        ejercicio = item?.ejercicio ?: "",
                        clientSetUuid = uuid,
                        setOrdenAparente = item?.aparenteOrden ?: 0,
                        startWallMs = wall,
                        startElapsedMs = elapsed,
                        createdAtEpochMs = wall,
                    ),
                )
            }.getOrDefault(-1L)
            if (id > 0) restTimer.onOpened(id, uuid, wall, elapsed)
            _runningUuid.value = restTimer.runningUuid()
            refreshRestMs()
        }
    }

    fun timerPause(uuid: String) {
        viewModelScope.launch(Dispatchers.IO) {
            if (restTimer.runningUuid() != uuid) return@launch
            val elapsed = clockElapsed()
            restTimer.pendingClose()?.let { toClose ->
                runCatching { restDao().close(toClose.intervalId, clockWall(), elapsed) }
                restTimer.onClosed(elapsed)
            }
            _runningUuid.value = restTimer.runningUuid()
            refreshRestMs()
        }
    }

    fun timerReset(uuid: String) {
        // Reset discreto de display: cierra lo que corra y olvida el acumulado
        // en memoria. Las filas Room se conservan (auditoría del dato FC).
        viewModelScope.launch(Dispatchers.IO) {
            if (restTimer.runningUuid() == uuid) {
                val elapsed = clockElapsed()
                restTimer.pendingClose()?.let { toClose ->
                    runCatching { restDao().close(toClose.intervalId, clockWall(), elapsed) }
                    restTimer.onClosed(elapsed)
                }
            }
            restTimer.resetDisplay(uuid)
            _runningUuid.value = restTimer.runningUuid()
            refreshRestMs()
        }
    }

    private fun startTicker() {
        tickerJob?.cancel()
        tickerJob = viewModelScope.launch {
            while (isActive) {
                delay(250)
                if (_modoEntreno.value) refreshRestMs()
            }
        }
    }

    private fun refreshRestMs() {
        val now = try { clockElapsed() } catch (_: Exception) { 0L }
        val ids = SessionFlowState.flattened(_entrenoGroups.value).map { it.uuid }
        _restMs.value = ids.associateWith { restTimer.elapsedFor(it, now) }
        _runningUuid.value = restTimer.runningUuid()
    }

    /**
     * Progresivo local + cola sin drenar en caliente: stash ya está en
     * draftBuffer; aquí solo enqueue (colapsa a 1 op/día por PK). Un único
     * POST explícito al final = 1 backup + 1 entrada undo (sin ruido).
     */
    private fun persistProgressive() {
        val fecha = _state.value.fecha
        val sets = currentDrafts().filter { !it.isBlank() }
        if (sets.isEmpty()) return
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { repository.enqueueSessionSave(fecha, sets) }
            val pending = runCatching { repository.pendingCount() }.getOrDefault(0)
            _state.value = _state.value.copy(pending = pending)
        }
    }

    fun load(fecha: String) {
        _state.value = _state.value.copy(fecha = fecha, loading = true, error = null, notice = null)
        viewModelScope.launch { loadInternal(fecha) }
    }

    fun setVista(vista: String) {
        if (vista != "entrenamiento" && vista != "alimentacion") return
        if (_state.value.vista == vista) return
        _state.value = _state.value.copy(vista = vista, loading = true, error = null, notice = null)
        viewModelScope.launch { loadInternal(_state.value.fecha) }
    }

    fun shiftDay(deltaDays: Long) {
        val next = runCatching { LocalDate.parse(_state.value.fecha).plusDays(deltaDays).toString() }
            .getOrDefault(LocalDate.now().toString())
        load(next)
    }

    fun goToday() = load(LocalDate.now().toString())

    fun save(drafts: List<TrainingSetDraft>) {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.saveSession(apiBase, token, fecha, drafts) }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    draftBuffer = null
                    _state.value.copy(
                        saving = false,
                        session = res.value,
                        stale = false,
                        suggestion = null,
                        notice = "Entrenamiento guardado (${res.value.sets.size} series).",
                    )
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> {
                    withContext(Dispatchers.IO) { repository.enqueueSessionSave(fecha, drafts) }
                    val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
                    _state.value.copy(
                        saving = false,
                        pending = pending,
                        notice = "Sin LAN: guardado en cola (se enviará al reconectar).",
                    )
                }
            }
        }
    }

    fun deleteDay() {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.deleteSession(apiBase, token, fecha) }
            if (res is TrainingResult.Ok) {
                draftBuffer = null
                _state.value = _state.value.copy(
                    saving = false,
                    session = TrainingSession(fecha, _state.value.session?.semana ?: 0, _state.value.session?.dia ?: "", false, emptyList()),
                    stale = false,
                    suggestion = null,
                    notice = "Entreno eliminado.",
                )
                return@launch
            }
            _state.value = when (res) {
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                else -> {
                    withContext(Dispatchers.IO) { repository.enqueueSessionDelete(fecha) }
                    val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
                    _state.value.copy(
                        saving = false,
                        pending = pending,
                        notice = "Sin LAN: borrado en cola (se enviará al reconectar).",
                    )
                }
            }
        }
    }

    private suspend fun loadInternal(fecha: String) {
        val creds = withContext(Dispatchers.IO) { credentials() }
        if (creds == null) {
            _state.value = _state.value.copy(loading = false, error = "Sin destino configurado (build release sin pairing).")
            return
        }
        val (apiBase2, token2) = creds
        // Drenar la cola offline primero (oportunista, como health_outbox).
        val drained = withContext(Dispatchers.IO) {
            runCatching { repository.drainOutbox(apiBase2, token2) }.getOrDefault(0)
        }
        val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
        val dots = withContext(Dispatchers.IO) {
            val vista = if (_state.value.vista == "alimentacion") "alimentacion" else "entrenamiento"
            when (val d = repository.clientFechas(apiBase2, token2, vista)) {
                is TrainingResult.Ok -> d.value
                else -> _state.value.dots
            }
        }
        _state.value = _state.value.copy(pending = pending, dots = dots)
        if (drained > 0 && _state.value.notice == null && _state.value.error == null) {
            _state.value = _state.value.copy(notice = "$drained cambio(s) pendiente(s) enviados.")
        }
        // Recién drenado: el conteo ya es 0.
        val freshPending = if (drained > 0) 0 else pending
        if (_state.value.vista == "alimentacion") {
            loadNutritionInternal(fecha, creds)
            return
        }
        val view = withContext(Dispatchers.IO) { repository.loadSession(apiBase2, token2, fecha) }
        // Catálogo en la misma carga (pequeño); si falla, el editor sigue con texto libre.
        val catalog = withContext(Dispatchers.IO) {
            when (val c = repository.loadCatalog(apiBase2, token2)) {
                is TrainingResult.Ok -> c.value
                else -> null
            }
        }
        _state.value = _state.value.copy(
            loading = false,
            session = view.session,
            stale = view.stale,
            error = view.error,
            pending = freshPending,
            dots = dots,
            catalog = catalog?.exercises ?: _state.value.catalog,
            categories = catalog?.categories ?: _state.value.categories,
            suggestion = null,
        )
        // Día vacío sin error: auto-relleno con la rueda (sin guardar).
        if (view.error == null && (view.session == null || !view.session.hasData)) {
            maybeSuggest(fecha, creds)
        }
        refreshCardio(fecha, creds)
    }

    // --- B3: cardio -----------------------------------------------------------------

    private suspend fun refreshCardio(fecha: String, creds: Pair<String, String>) {
        val (apiBase, token) = creds
        val res = withContext(Dispatchers.IO) { repository.loadCardioDay(apiBase, token, fecha) }
        if (res is TrainingResult.Ok) {
            _state.value = _state.value.copy(cardio = res.value)
        }
        // Sin red o sin sesiones: sección vacía (el cardio es informativo).
    }

    fun annotateCardio(hcId: String, velocidadKmh: String, inclinacionPct: String, notas: String) {
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val res = withContext(Dispatchers.IO) {
                repository.annotateCardio(creds.first, creds.second, hcId, velocidadKmh, inclinacionPct, notas)
            }
            if (res is TrainingResult.Ok) {
                refreshCardio(_state.value.fecha, creds)
                _state.value = _state.value.copy(
                    saving = false,
                    notice = if (res.value) "Anotación eliminada." else "Anotación guardada.",
                )
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(saving = false, error = res.detail)
            } else {
                _state.value = _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    // --- B1: plantillas, alta de ejercicio, undo ----------------------------------

    fun ensureTemplates(force: Boolean = false) {
        if (_state.value.templates.isNotEmpty() && !force) return
        viewModelScope.launch {
            val creds = credentials() ?: return@launch
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.loadTemplates(apiBase, token) }
            if (res is TrainingResult.Ok) {
                _state.value = _state.value.copy(templates = res.value)
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(error = res.detail)
            }
        }
    }

    /** Preview sin escribir: rellena el editor; el Guardar posterior persiste. */
    fun applyTemplate(plantillaId: Int, nombre: String) {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.applyTemplate(apiBase, token, plantillaId, fecha) }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    draftBuffer = fecha to res.value.sets.map {
                        TrainingSetDraft(it.ejercicio, numText(it.kg), numText(it.reps), numText(it.rir), numText(it.descansoSeg), numText(it.velocidadKmh), numText(it.dificultad))
                    }
                    _state.value.copy(
                        saving = false,
                        previewId = _state.value.previewId + 1,
                        notice = "Entreno '$nombre' aplicado: revisa y guarda.",
                    )
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    /** Guarda el día visible como entreno (upsert por nombre, como la web). */
    fun saveAsTemplate(nombre: String, ejercicios: List<String>) {
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.saveTemplate(apiBase, token, nombre, ejercicios) }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    val updated = res.value
                    ensureTemplates(force = true)
                    _state.value.copy(saving = false, notice = "Entreno '${updated.nombre}' guardado.")
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    fun createExercise(ejercicio: String, grupoMuscular: String, categoria: String) {
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.createExercise(apiBase, token, ejercicio, grupoMuscular, categoria)
            }
            if (res is TrainingResult.Ok) {
                // El catálogo cambió: recarga para el autocompletado.
                val fecha = _state.value.fecha
                loadInternal(fecha)
                _state.value = _state.value.copy(saving = false, notice = "Ejercicio '$ejercicio' creado.")
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(saving = false, error = res.detail)
            } else {
                _state.value = _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    /** Deshace la última acción global (botón visible; la web es Ctrl+Z). */
    fun undo() {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.undo(apiBase, token, fecha) }
            if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(saving = false, error = res.detail)
                return@launch
            }
            if (res is TrainingResult.NetworkError) {
                _state.value = _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
                return@launch
            }
            val result = (res as TrainingResult.Ok).value
            draftBuffer = null
            nutritionDraftBuffer = null
            if (result.kind == "entrenos") ensureTemplates(force = true)
            loadInternal(fecha)
            val msg = when (result.kind) {
                "empty" -> "Nada que deshacer."
                else -> "Acción deshecha (${result.kind})."
            }
            _state.value = _state.value.copy(saving = false, notice = msg)
        }
    }

    // --- B2: nutrición ------------------------------------------------------------

    var nutritionDraftBuffer: Pair<String, List<FoodDraft>>? = null

    private suspend fun loadNutritionInternal(fecha: String, creds: Pair<String, String>) {
        val (apiBase, token) = creds
        val result = withContext(Dispatchers.IO) { repository.loadNutritionDayCached(apiBase, token, fecha) }
        val foods = withContext(Dispatchers.IO) {
            when (val f = repository.loadFoods(apiBase, token)) {
                is TrainingResult.Ok -> f.value
                else -> null
            }
        }
        val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
        when (result) {
            is TrainingRepository.CachedDay.Fresh -> _state.value = _state.value.copy(
                loading = false,
                nutrition = result.day,
                stale = false,
                error = null,
                pending = pending,
                foods = foods?.items ?: _state.value.foods,
                nutrientLabels = foods?.nutrientLabels ?: _state.value.nutrientLabels,
            )
            is TrainingRepository.CachedDay.Stale -> _state.value = _state.value.copy(
                loading = false,
                nutrition = result.day,
                stale = true,
                error = null,
                pending = pending,
                notice = _state.value.notice
                    ?: "Sin conexión: última copia guardada.",
                foods = foods?.items ?: _state.value.foods,
                nutrientLabels = foods?.nutrientLabels ?: _state.value.nutrientLabels,
            )
            is TrainingRepository.CachedDay.Failed -> _state.value = _state.value.copy(
                loading = false,
                nutrition = null,
                error = result.detail,
                pending = pending,
            )
        }
    }

    // --- Rueda de sugerencia (auto-relleno en día vacío) --------------------------

    private suspend fun maybeSuggest(fecha: String, creds: Pair<String, String>) {
        val (apiBase, token) = creds
        val res = withContext(Dispatchers.IO) { repository.loadSuggestion(apiBase, token, fecha) }
        if (res !is TrainingResult.Ok) return // Sin red: día en blanco como antes.
        val suggestion = res.value
        when (suggestion.tipo) {
            "rutina" -> {
                draftBuffer = fecha to suggestion.sets.map {
                    TrainingSetDraft(it.ejercicio, numText(it.kg), numText(it.reps), numText(it.rir), numText(it.descansoSeg), numText(it.velocidadKmh), numText(it.dificultad))
                }
                _state.value = _state.value.copy(
                    suggestion = suggestion,
                    previewId = _state.value.previewId + 1,
                )
            }
            "descanso" -> _state.value = _state.value.copy(suggestion = suggestion)
            else -> _state.value = _state.value.copy(suggestion = null)
        }
    }

    private fun parseParams(raw: Map<String, String>): NutritionParams? {
        fun num(key: String): Double? {
            val t = (raw[key] ?: "").trim().replace(",", ".")
            if (t.isEmpty()) return null
            return t.toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0 }
        }
        val peso = num("peso_kg") ?: return null
        if (peso == 0.0) return null
        return NutritionParams(
            pesoKg = peso,
            factorProteina = num("factor_proteina") ?: return null,
            factorGrasa = num("factor_grasa") ?: return null,
            kcalObjetivo = num("kcal_objetivo") ?: return null,
        )
    }

    fun saveNutrition(drafts: List<FoodDraft>, rawParams: Map<String, String>) {
        val fecha = _state.value.fecha
        val params = parseParams(rawParams)
        if (params == null) {
            _state.value = _state.value.copy(error = "Parámetros inválidos (peso > 0, números ≥ 0).")
            return
        }
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.saveNutritionDay(apiBase, token, fecha, drafts, params)
            }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    nutritionDraftBuffer = null
                    _state.value.copy(
                        saving = false,
                        nutrition = res.value,
                        stale = false,
                        notice = "Día guardado (${res.value.entradas.size} alimentos).",
                    )
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> {
                    withContext(Dispatchers.IO) { repository.enqueueDiarySave(fecha, drafts, params) }
                    val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
                    _state.value.copy(
                        saving = false,
                        pending = pending,
                        notice = "Sin LAN: guardado en cola (se enviará al reconectar).",
                    )
                }
            }
        }
    }

    fun deleteNutritionDay() {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.deleteNutritionDay(apiBase, token, fecha) }
            if (res is TrainingResult.Ok) {
                nutritionDraftBuffer = null
                loadNutritionInternal(fecha, creds)
                _state.value = _state.value.copy(saving = false, notice = "Día eliminado.")
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(saving = false, error = res.detail)
            } else {
                withContext(Dispatchers.IO) { repository.enqueueDiaryDelete(fecha) }
                val pending = withContext(Dispatchers.IO) { repository.pendingCount() }
                _state.value = _state.value.copy(
                    saving = false,
                    pending = pending,
                    notice = "Sin LAN: borrado en cola (se enviará al reconectar).",
                )
            }
        }
    }

    fun ensureFoods(force: Boolean = false) {
        if (_state.value.foods.isNotEmpty() && !force) return
        viewModelScope.launch {
            val creds = credentials() ?: return@launch
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.loadFoods(apiBase, token) }
            if (res is TrainingResult.Ok) {
                _state.value = _state.value.copy(
                    foods = res.value.items, nutrientLabels = res.value.nutrientLabels,
                )
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(error = res.detail)
            }
        }
    }

    fun ensureMealTemplates(force: Boolean = false) {
        if (_state.value.mealTemplates.isNotEmpty() && !force) return
        viewModelScope.launch {
            val creds = credentials() ?: return@launch
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) { repository.loadMealTemplates(apiBase, token) }
            if (res is TrainingResult.Ok) {
                _state.value = _state.value.copy(mealTemplates = res.value)
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(error = res.detail)
            }
        }
    }

    fun applyMealTemplate(plantillaId: Int, nombre: String) {
        val fecha = _state.value.fecha
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.applyMealTemplate(apiBase, token, plantillaId, fecha)
            }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    nutritionDraftBuffer = fecha to res.value.map {
                        FoodDraft(it.alimento, foodNumText(it.cantidadG))
                    }
                    _state.value.copy(
                        saving = false,
                        nutritionPreviewId = _state.value.nutritionPreviewId + 1,
                        notice = "Plantilla '$nombre' aplicada: revisa y guarda.",
                    )
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    fun saveMealTemplate(nombre: String, entradas: List<FoodDraft>) {
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.saveMealTemplate(apiBase, token, nombre, entradas)
            }
            _state.value = when (res) {
                is TrainingResult.Ok -> {
                    ensureMealTemplates(force = true)
                    _state.value.copy(saving = false, notice = "Plantilla '${res.value.nombre}' guardada.")
                }
                is TrainingResult.ApiError -> _state.value.copy(saving = false, error = res.detail)
                is TrainingResult.NetworkError -> _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }

    fun createFood(nombre: String, categoria: String, nutrients: Map<String, Double>) {
        _state.value = _state.value.copy(saving = true, error = null, notice = null)
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                _state.value = _state.value.copy(saving = false, error = "Sin destino configurado (build release sin pairing).")
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.createFood(apiBase, token, nombre, categoria, nutrients)
            }
            if (res is TrainingResult.Ok) {
                ensureFoods(force = true)
                _state.value = _state.value.copy(saving = false, notice = "Alimento '$nombre' creado.")
            } else if (res is TrainingResult.ApiError) {
                _state.value = _state.value.copy(saving = false, error = res.detail)
            } else {
                _state.value = _state.value.copy(saving = false, error = "Sin conexión: necesita LAN.")
            }
        }
    }
    /** (apiBase explícita, token) o null sin destino. Nunca registra el token. */
    private suspend fun credentials(): Pair<String, String>? {
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
}

private fun numText(v: Double?): String {
    if (v == null) return ""
    return if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()
}

private fun foodNumText(v: Double?): String = numText(v)
