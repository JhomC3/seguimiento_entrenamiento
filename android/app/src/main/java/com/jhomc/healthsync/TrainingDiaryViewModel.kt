package com.jhomc.healthsync

import android.app.Application
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.PowerManager
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jhomc.healthsync.data.DraftRow
import com.jhomc.healthsync.data.EntrenoDraftDao
import com.jhomc.healthsync.data.EntrenoDraftEntity
import com.jhomc.healthsync.data.RestIntervalEntity
import com.jhomc.healthsync.data.RestDao
import com.jhomc.healthsync.data.SecureTargetStore
import com.jhomc.healthsync.data.canonicalRowsHash
import com.jhomc.healthsync.data.doneJson
import com.jhomc.healthsync.data.parseDone
import com.jhomc.healthsync.data.parsePayload
import com.jhomc.healthsync.data.payloadJson
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Pii de descanso: seno puro a esta frecuencia durante 1.5 s (una vez por marca). */
private const val BEEP_FREQ_HZ = 1200.0
private const val BEEP_DURATION_MS = 1500L

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
    internal var draftsDaoOverride: EntrenoDraftDao? = null
    /** Fila local del día en caché de memoria (la DB es la fuente real). */
    private var localRowCache: Pair<String, EntrenoDraftEntity?>? = null


    private val restTimer = RestTimer()
    private var tickerJob: Job? = null
    private var entrenoIds: List<String> = emptyList()
    private var entrenoIdsFecha: String? = null
    private var orphanSweepDone = false

    private val _entrenoGroups = MutableStateFlow<List<EntrenoGroup>>(emptyList())
    val entrenoGroups: StateFlow<List<EntrenoGroup>> = _entrenoGroups.asStateFlow()
    /** Apertura múltiple: cada cabecera alterna solo la suya. */
    private val _expandedUuids = MutableStateFlow<Set<String>>(emptySet())
    val expandedUuids: StateFlow<Set<String>> = _expandedUuids.asStateFlow()
    /** Todas las filas incl. blancos (el editor unificado las pinta todas). */
    private val _entrenoRows = MutableStateFlow<List<EntrenoRow>>(emptyList())
    val entrenoRows: StateFlow<List<EntrenoRow>> = _entrenoRows.asStateFlow()
    /**
     * Versión estructural: solo cambia con add/remove/día/transición
     * blanco↔visible/cambio de nombre o HIIT. Los steppers NO la tocan
     * (la Activity actualiza el valor in-place, sin reconstruir ni saltos).
     */
    private val _structureVersion = MutableStateFlow(0)
    val structureVersion: StateFlow<Int> = _structureVersion.asStateFlow()
    private val _doneUuids = MutableStateFlow<Set<String>>(emptySet())
    val doneUuids: StateFlow<Set<String>> = _doneUuids.asStateFlow()
    private val _restMs = MutableStateFlow<Map<String, Long>>(emptyMap())
    val restMs: StateFlow<Map<String, Long>> = _restMs.asStateFlow()
    private val _runningUuid = MutableStateFlow<String?>(null)
    val runningUuid: StateFlow<String?> = _runningUuid.asStateFlow()
    /** Series con descanso pausado (el parcial anotado queda; no sobrevive al atrás). */
    private val _pausedUuids = MutableStateFlow<Set<String>>(emptySet())
    val pausedUuids: StateFlow<Set<String>> = _pausedUuids.asStateFlow()
    /** Piip de descanso: pista generada vaga + cursor por intervalo (sin refires). */
    private var beepTrack: AudioTrack? = null
    private var beepCursorFor: Long? = null
    private var beepCursorMs: Long = 0L
    /**
     * Wake lock parcial: CPU despierta mientras corre un descanso para que el
     * ticker (piips 2:00/3:00) sea puntual con pantalla bloqueada. Sin él,
     * Doze difiere los ticks. Solo vive durante descansos (segundos-minutos);
     * el SO lo suelta solo si muere el proceso.
     */
    private var restWakeLock: PowerManager.WakeLock? = null

    override fun onCleared() {
        runCatching { beepTrack?.release() }
        beepTrack = null
        runCatching { restWakeLock?.let { if (it.isHeld) it.release() } }
        restWakeLock = null
        super.onCleared()
    }

    /** Sincroniza el wake lock con el estado real (único punto de llamada). */
    private fun syncWakeLock() {
        if (restTimer.runningUuid() == null) {
            restWakeLock?.let { if (it.isHeld) runCatching { it.release() } }
            return
        }
        val lock = restWakeLock ?: runCatching {
            (getApplication<Application>().getSystemService(android.content.Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HealthSync:rest")
                .apply { setReferenceCounted(false) }
                .also { restWakeLock = it }
        }.getOrNull() ?: return
        if (!lock.isHeld) runCatching { lock.acquire() }
    }

    private fun restDao(): RestDao =
        restDaoOverride ?: HealthDatabaseBuilder.get(getApplication()).restDao()

    private fun draftsDao(): EntrenoDraftDao =
        draftsDaoOverride ?: HealthDatabaseBuilder.get(getApplication()).entrenoDraftDao()

    init {
        // Ticker vago: corre siempre pero solo emite con descanso en curso.
        startTicker()
        viewModelScope.launch(Dispatchers.IO) {
            // Barrido único: huérfanos de OTROS días se abandonan; el ABIERTO
            // de hoy se reanuda (volver con atrás o muerte de proceso el
            // mismo día no pierde el descanso en curso).
            if (!orphanSweepDone) {
                orphanSweepDone = true
                sweepAndResume()
            }
            withContext(Dispatchers.Main) { load(LocalDate.now().toString()) }
        }
    }

    /**
     * Abandona abiertos de otros días y reanuda el de hoy (como mucho hay
     * uno por single-running; si hubiera varios, conserva el último y los
     * anteriores se cierran como historia honesta). El reloj elapsed incluye
     * la ausencia: al volver sigue donde iba.
     */
    private suspend fun sweepAndResume() {
        val wall = clockWall()
        val elapsed = clockElapsed()
        val dao = restDao()
        val today = LocalDate.now().toString()
        runCatching { dao.abandonOpenExcept(today, wall, elapsed) }
        val open = runCatching { dao.openForFecha(today) }.getOrDefault(emptyList())
        open.dropLast(1).forEach { runCatching { dao.close(it.id, wall, elapsed) } }
        open.lastOrNull()?.let { resume ->
            restTimer.onOpened(resume.id, resume.clientSetUuid, resume.startWallMs, resume.startElapsedMs)
            _runningUuid.value = resume.clientSetUuid
        }
        refreshRestMs()
    }

    /** Borradores actuales (misma fuente que rebuildRows de la Activity). */
    fun currentDrafts(): List<TrainingSetDraft> {
        val fecha = _state.value.fecha
        val buffered = draftBuffer?.takeIf { it.first == fecha }?.second
        return buffered
            ?: _state.value.session?.let { SessionFlowState.draftsFromSession(it.sets) }
                ?.ifEmpty { listOf(TrainingSetDraft("", "", "", "", "")) }
            ?: listOf(TrainingSetDraft("", "", "", "", ""))
    }

    /** Semilla de acumulados desde intervalos CERRADOS (llamar al abrir el día). */
    fun seedRestAccum() {
        viewModelScope.launch(Dispatchers.IO) {
            val fecha = _state.value.fecha
            val rows = runCatching { restDao().forFecha(fecha) }.getOrDefault(emptyList())
            val closed = rows.filter { it.estado == "CERRADO" && it.endElapsedMs != null }
            for (c in closed) {
                val dur = (c.endElapsedMs!! - c.startElapsedMs).coerceAtLeast(0)
                restTimer.seedAccum(c.clientSetUuid, dur)
            }
            // Pausa persistente derivada: pendiente con cerrados y sin running
            // estaba pausada al morir el proceso → el tap reanuda desde el
            // acumulado en vez de arrancar de cero (ver derivePaused).
            _pausedUuids.value = SessionFlowState.derivePaused(
                closed.map { it.clientSetUuid },
                _doneUuids.value,
                restTimer.runningUuid(),
                entrenoIds,
            )
            refreshRestMs()
        }
    }

    /** Escritura por teclado (diálogo sobre el valor): actualiza sin reconstruir. */
    fun setEntrenoValue(uuid: String, field: String, text: String) {
        val fecha = _state.value.fecha
        val drafts = currentDrafts().toMutableList()
        val index = entrenoIds.indexOf(uuid)
        if (index !in drafts.indices) return
        val cur = drafts[index]
        val v = text.trim()
        drafts[index] = when (field) {
            "kg" -> cur.copy(kg = v)
            "reps" -> cur.copy(reps = v)
            "rir" -> cur.copy(rir = v)
            "vel" -> cur.copy(velocidadKmh = v)
            "dif" -> cur.copy(dificultad = v)
            else -> return
        }
        draftBuffer = fecha to drafts
        rebuildEntrenoLists()
        persistLocal()
    }

    /**
     * Libreta del bolsillo: persiste borradores+✓ del día en Room en el acto.
     * Sobrevive a la muerte del proceso, a la falta de red y a reinicios.
     * La base_hash se fija al crear la fila (contenido del servidor entonces)
     * y nunca se reescribe en updates: es el punto de comparación para
     * detectar ediciones web por debajo.
     */
    private fun persistLocal() {
        val fecha = _state.value.fecha
        val drafts = currentDrafts()
        val ids = entrenoIds.takeIf { it.size == drafts.size }
            ?: List(drafts.size) { UUID.randomUUID().toString() }
        if (ids !== entrenoIds) entrenoIds = ids
        val rows = drafts.mapIndexed { i, d ->
            DraftRow(ids[i], d.ejercicio, d.kg, d.reps, d.rir, d.descansoSeg, d.velocidadKmh, d.dificultad)
        }
        val done = _doneUuids.value
        viewModelScope.launch(Dispatchers.IO + NonCancellable) {
            val dao = draftsDao()
            val existing = runCatching { dao.forFecha(fecha) }.getOrNull()
            val base = existing?.baseHash ?: serverBaseHash()
            val entry = EntrenoDraftEntity(fecha, payloadJson(rows), doneJson(done), base, clockWall())
            runCatching { dao.put(entry) }
            localRowCache = fecha to entry
        }
    }

    /** Hash del contenido actual del servidor (base para detectar web-edits). */
    private fun serverBaseHash(): String {
        val sets = _state.value.session?.sets ?: return canonicalRowsHash(emptyList())
        return canonicalRowsHash(sets.map { DraftRow("", it.ejercicio, numText(it.kg), numText(it.reps), numText(it.rir), numText(it.descansoSeg), numText(it.velocidadKmh), numText(it.dificultad)) })
    }

    private fun clearLocalRow(fecha: String) {
        localRowCache = fecha to null
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { draftsDao().clear(fecha) }
        }
    }

    private suspend fun clearLocalRowSync(fecha: String) {
        localRowCache = fecha to null
        runCatching { draftsDao().clear(fecha) }
    }

    /**
     * Reconcilia borrador local vs servidor ANTES de drenar (el drenado ciego
     * pisaría ediciones web). Sin avisos ni botones, por decisión de diseño:
     * si el GET fresco difiere de la base del borrador, la web editó por
     * debajo → reemplazo silencioso (manda lo web, se suelta la op encolada).
     * Si coincide o no hay red, no se toca nada y el drenado sigue su curso.
     */
    private suspend fun reconcileDay(apiBase: String, token: String, fecha: String) {
        val local = runCatching { draftsDao().forFecha(fecha) }.getOrNull() ?: return
        val fresh = repository.fetchSession(apiBase, token, fecha)
        if (fresh !is TrainingResult.Ok) return
        val freshRows = fresh.value.sets.map {
            DraftRow("", it.ejercicio, numText(it.kg), numText(it.reps), numText(it.rir), numText(it.descansoSeg), numText(it.velocidadKmh), numText(it.dificultad))
        }
        if (canonicalRowsHash(freshRows) == local.baseHash) return
        // La web trae algo más nuevo: suelta borrador + cola y quédate lo web.
        runCatching { draftsDao().clear(fecha) }
        runCatching { repository.dropPending("sesion", fecha) }
        localRowCache = fecha to null
        if (_state.value.fecha == fecha && draftBuffer?.first == fecha) {
            draftBuffer = null
            _doneUuids.value = emptySet()
        }
    }

    /** Reconstruye grupos+filas preservando UUIDs por índice. */
    fun ensureEntrenoBuilt() {
        val fecha = _state.value.fecha
        val dayChanged = entrenoIdsFecha != fecha
        if (dayChanged) {
            // La memoria manda en el mismo proceso (siempre lo más nuevo);
            // la fila local solo resucita tras muerte del proceso.
            val buffered = draftBuffer?.takeIf { it.first == fecha }?.second
            val row = if (buffered == null) {
                localRowCache?.takeIf { it.first == fecha }?.second
            } else {
                null
            }
            if (row != null) {
                val rows = parsePayload(row.payloadJson)
                draftBuffer = fecha to rows.map {
                    TrainingSetDraft(it.ejercicio, it.kg, it.reps, it.rir, it.descansoSeg, it.velocidadKmh, it.dificultad)
                }
                entrenoIds = rows.map { it.uuid }
                _doneUuids.value = parseDone(row.doneJson)
            } else if (buffered == null) {
                entrenoIds = emptyList()
                _doneUuids.value = emptySet()
            }
            entrenoIdsFecha = fecha
            _expandedUuids.value = emptySet()
            restTimer.clearAccum(emptySet())
            seedRestAccum()
        }
        rebuildEntrenoLists()
        val flat = SessionFlowState.flattened(_entrenoGroups.value).map { it.uuid }.toSet()
        _expandedUuids.value = _expandedUuids.value.intersect(flat)
        if (dayChanged && _expandedUuids.value.isEmpty()) {
            // Primer pintado del día: si hay descanso corriendo (vuelta con
            // atrás), se abre su dueño para dejar el dial a la vista; si no,
            // la primera pendiente. Los colapsos manuales posteriores se
            // respetan (no se reabre solo).
            val focus = restTimer.runningUuid()?.takeIf { it in flat }
                ?: SessionFlowState.nextPending(_entrenoGroups.value, _doneUuids.value, null)?.uuid
            focus?.let { _expandedUuids.value = setOf(it) }
        }
        refreshRestMs()
    }

    /** Reconstruye grupos y filas sin tocar expand/done/versión. */
    private fun rebuildEntrenoLists() {
        val drafts = currentDrafts()
        val (groups, outIds) = SessionFlowState.build(drafts, entrenoIds)
        entrenoIds = outIds
        restTimer.clearAccum(outIds.toSet())
        _entrenoGroups.value = groups
        _entrenoRows.value = drafts.mapIndexed { i, d -> EntrenoRow(outIds[i], d) }
    }

    /** Cada cabecera alterna solo la suya (apertura múltiple). */
    fun toggleExpand(uuid: String) {
        _expandedUuids.value = SessionFlowState.toggleExpanded(_expandedUuids.value, uuid)
    }

    // --- Flujo por serie: check + dial (pausa/reanuda/reset) --------------------
    // El descanso pertenece a la SERIE SIGUIENTE: nace en el ✓ de la anterior
    // (late en su tarjeta abierta, visible) y muere en su propio ✓, que lo
    // anota como descanso_seg (check-to-check, incluye el trabajo). La primera
    // serie no tiene descanso previo; la última no abre otro al guardarse.
    // Semántica de cronómetro: cada cierre anota a su dueño; el tramo pausado
    // se excluye del anotado; reanudar acumula encima (N intervalos por serie).

    /**
     * Check: guarda la serie (local + cola), la colapsa, auto-expande la
     * siguiente y le arranca su descanso. En la última pendiente no se abre
     * descanso (post-entreno sin sentido: el reloj no queda corriendo).
     */
    fun guardar(uuid: String) {
        viewModelScope.launch(Dispatchers.IO) {
            if (restTimer.runningUuid() != null) closeRunning()
            _pausedUuids.value = _pausedUuids.value - uuid
            val effect = SessionFlowState.WorkoutFlow.guardar(uuid, _doneUuids.value, _entrenoGroups.value)
            _doneUuids.value = _doneUuids.value + effect.saved
            persistProgressive()
            _expandedUuids.value = _expandedUuids.value - effect.saved
            if (effect.nextToExpand != null) {
                _expandedUuids.value = _expandedUuids.value + effect.nextToExpand
            }
            if (effect.startRest) {
                openRest(effect.nextToExpand!!, fresh = true)
            } else {
                _state.value = _state.value.copy(notice = "Entreno completo.")
            }
        }
    }

    /**
     * Toque en el dial (play/pausa): pausa lo que corre, reanuda lo pausado,
     * arranca el descanso de una pendiente en reposo (así un cronómetro
     * reseteado vuelve a andar). En serie hecha o con otro corriendo no hace
     * nada (jamás tumba timer ajeno).
     */
    fun onDialTap(uuid: String) {
        viewModelScope.launch(Dispatchers.IO) {
            when (val d = SessionFlowState.WorkoutFlow.resolveDialTap(
                restTimer.runningUuid(), _pausedUuids.value, uuid, uuid in _doneUuids.value,
            )) {
                is SessionFlowState.WorkoutFlow.DialTapDecision.Nothing -> Unit
                is SessionFlowState.WorkoutFlow.DialTapDecision.Pause -> {
                    closeRunning()
                    _pausedUuids.value = _pausedUuids.value + d.uuid
                    _state.value = _state.value.copy(notice = "Descanso en pausa.")
                }
                is SessionFlowState.WorkoutFlow.DialTapDecision.Resume -> {
                    if (d.closeOther != null) closeRunning()
                    _pausedUuids.value = _pausedUuids.value - d.uuid
                    openRest(d.uuid)
                    _state.value = _state.value.copy(notice = "Descanso reanudado.")
                }
                is SessionFlowState.WorkoutFlow.DialTapDecision.Start -> {
                    openRest(d.uuid, fresh = true)
                    _state.value = _state.value.copy(notice = "Descanso iniciado.")
                }
            }
        }
    }

    /**
     * Hold 3 s en el dial: reinicia el cronómetro en curso, pausado o ya
     * completado de esa serie (00:00, limpia su descanso anotado). Si estaba
     * completada, vuelve a pendiente y se abre para verla en cero. En reposo
     * sin nada que reiniciar no hace nada. Los intervalos descartados quedan
     * ABANDONADO (historia para la futura curva de FC, excluidos del cómputo:
     * el reset no resucita al reabrir).
     */
    fun resetRest(uuid: String) {
        val running = restTimer.runningUuid()
        val done = uuid in _doneUuids.value
        if (running != uuid && uuid !in _pausedUuids.value && !done) return
        viewModelScope.launch(Dispatchers.IO) {
            val wall = clockWall()
            val elapsed = clockElapsed()
            runCatching { restDao().abandonForSet(uuid, wall, elapsed) }
            restTimer.abandonRunning(uuid)
            restTimer.clearAccumFor(uuid)
            _pausedUuids.value = _pausedUuids.value - uuid
            _doneUuids.value = _doneUuids.value - uuid
            val fecha = _state.value.fecha
            val drafts = currentDrafts().toMutableList()
            val index = entrenoIds.indexOf(uuid)
            if (index in drafts.indices && drafts[index].descansoSeg.isNotBlank()) {
                drafts[index] = drafts[index].copy(descansoSeg = "")
                draftBuffer = fecha to drafts
                rebuildEntrenoLists()
            }
            persistLocal()
            val sets = currentDrafts().filter { !it.isBlank() }
            if (sets.isNotEmpty()) {
                runCatching { repository.enqueueSessionSave(fecha, sets) }
                _state.value = _state.value.copy(
                    pending = runCatching { repository.pendingCount() }.getOrDefault(0),
                )
            }
            _expandedUuids.value = _expandedUuids.value + uuid
            refreshRestMs()
        }
    }

    /**
     * Reinicio del entreno: todos los descansos a 00:00, series desmarcadas y
     * primera pendiente abierta. Los pesos/reps se conservan; el historial de
     * intervalos queda ABANDONADO (no se borra). Con confirmación en la UI.
     */
    fun resetEntreno() {
        viewModelScope.launch(Dispatchers.IO) {
            val fecha = _state.value.fecha
            val wall = clockWall()
            val elapsed = clockElapsed()
            runCatching { restDao().abandonForFecha(fecha, wall, elapsed) }
            restTimer.resetAll()
            _pausedUuids.value = emptySet()
            _doneUuids.value = emptySet()
            val drafts = currentDrafts().map {
                if (it.descansoSeg.isBlank()) it else it.copy(descansoSeg = "")
            }
            draftBuffer = fecha to drafts
            rebuildEntrenoLists()
            persistProgressive()
            _expandedUuids.value = emptySet()
            SessionFlowState.nextPending(_entrenoGroups.value, emptySet(), null)?.uuid?.let {
                _expandedUuids.value = setOf(it)
            }
            refreshRestMs()
        }
    }

    /**
     * Abre el descanso a nombre de la serie dada (limpia su pausa si la tenía).
     * Con [fresh] el contador arranca de 0 (✓-avance y tap-Start: la siguiente
     * siempre late desde cero aunque tuviera historial); sin fresh acumula
     * encima (reanudar tras pausa). El borrador se sobrescribe al guardar.
     */
    private suspend fun openRest(ownerUuid: String, fresh: Boolean = false) {
        _pausedUuids.value = _pausedUuids.value - ownerUuid
        if (fresh) restTimer.clearAccumFor(ownerUuid)
        val item = SessionFlowState.flattened(_entrenoGroups.value).find { it.uuid == ownerUuid }
        val wall = clockWall()
        val elapsed = clockElapsed()
        val id = runCatching {
            restDao().insert(
                RestIntervalEntity(
                    fecha = _state.value.fecha,
                    ejercicio = item?.ejercicio ?: "",
                    clientSetUuid = ownerUuid,
                    setOrdenAparente = item?.aparenteOrden ?: 0,
                    startWallMs = wall,
                    startElapsedMs = elapsed,
                    createdAtEpochMs = wall,
                ),
            )
        }.getOrDefault(-1L)
        if (id > 0) restTimer.onOpened(id, ownerUuid, wall, elapsed)
        _runningUuid.value = restTimer.runningUuid()
        refreshRestMs()
    }

    fun entrenoDelta(uuid: String, field: String, delta: Double) {
        val fecha = _state.value.fecha
        val drafts = currentDrafts().toMutableList()
        val index = entrenoIds.indexOf(uuid)
        if (index !in drafts.indices) return
        val cur = drafts[index]
        fun shift(raw: String, step: Double): String {
            val base = raw.trim().replace(",", ".").toDoubleOrNull() ?: 0.0
            // Redondeo a 1 decimal: con pasos de 0.1 el binario acumula error.
            val next = (kotlin.math.round((base + step) * 10) / 10.0).coerceAtLeast(0.0)
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
        // Libreta local en el acto (sin enqueue: evita ráfagas al rate-limit).
        // Sin bump estructural: la Activity actualiza el valor in-place.
        rebuildEntrenoLists()
        persistLocal()
    }

    /**
     * Cierra el descanso en curso (si lo hay) con su hora real y anota el
     * total acumulado en el campo descanso de esa serie: un dato más, como
     * kg/reps/RIR (libreta local + cola para auto-subida). Cada cierre anota
     * a su dueño (pausa, guardado o reanudación ajena). Sin timer previo no
     * toca nada. Devuelve el uuid afectado o null.
     */
    private suspend fun closeRunning(): String? {
        val toClose = restTimer.pendingClose() ?: return null
        val endWall = clockWall()
        val endElapsed = clockElapsed()
        runCatching { restDao().close(toClose.intervalId, endWall, endElapsed) }
        val (uuid, _) = restTimer.onClosed(endElapsed) ?: return null
        annotateDescanso(uuid)
        _runningUuid.value = restTimer.runningUuid()
        refreshRestMs()
        return uuid
    }

    /** Anota el acumulado en descanso_seg (1 decimal) + libreta + cola. */
    private suspend fun annotateDescanso(uuid: String) {
        val totalMs = SessionFlowState.flattened(_entrenoGroups.value)
            .find { it.uuid == uuid }
            ?.let { restTimer.elapsedFor(uuid, clockElapsed()) }
            ?: return
        val secs = SessionFlowState.descansoSecsFor(totalMs)
        val text = SessionFlowState.descansoText(secs)
        val fecha = _state.value.fecha
        val drafts = currentDrafts().toMutableList()
        val index = entrenoIds.indexOf(uuid)
        if (index in drafts.indices) {
            drafts[index] = drafts[index].copy(descansoSeg = text)
            draftBuffer = fecha to drafts
            rebuildEntrenoLists()
        }
        persistLocal()
        // Auto-subida: olvidar Guardar ya no pierde nada en ningún lado.
        val sets = currentDrafts().filter { !it.isBlank() }
        if (sets.isNotEmpty()) {
            runCatching { repository.enqueueSessionSave(fecha, sets) }
            _state.value = _state.value.copy(
                pending = runCatching { repository.pendingCount() }.getOrDefault(0),
            )
        }
    }

    /** Ticker vago: gira siempre pero solo emite con descanso en curso. */
    private fun startTicker() {
        tickerJob?.cancel()
        tickerJob = viewModelScope.launch {
            while (isActive) {
                delay(250)
                if (restTimer.runningUuid() != null) refreshRestMs()
            }
        }
    }

    private fun refreshRestMs() {
        val now = try { clockElapsed() } catch (_: Exception) { 0L }
        val ids = SessionFlowState.flattened(_entrenoGroups.value).map { it.uuid }
        _restMs.value = ids.associateWith { restTimer.elapsedFor(it, now) }
        val running = restTimer.runningUuid()
        _runningUuid.value = running
        // Wake lock atado al running: puntualidad con pantalla bloqueada.
        syncWakeLock()
        // Piip por flanco en 2:00 y 3:00 (una vez por descanso, canal alarma:
        // suena en silencio; pausado no avanza, reseteado limpia el cursor).
        if (running != null) {
            val intervalId = restTimer.runningIntervalId()
            val elapsed = restTimer.elapsedFor(running, now)
            if (intervalId != null && beepCursorFor == intervalId) {
                if (SessionFlowState.crossedThresholds(beepCursorMs, elapsed, REST_BEEP_AT_SEC).isNotEmpty()) {
                    beep()
                }
            }
            beepCursorFor = intervalId
            beepCursorMs = elapsed
        } else {
            beepCursorFor = null
        }
    }

    /** Mismo pii en 2:00 y 3:00 (decisión de producto): seno puro 1.5 s. */
    private fun beep() {
        val track = beepTrack ?: runCatching { buildBeepTrack()?.also { beepTrack = it } }.getOrNull() ?: return
        runCatching {
            track.stop()
            track.reloadStaticData()
            track.play()
        }
    }

    /**
     * Pii generado (seno puro, idéntico en todos los teléfonos: los
     * ToneGenerator varían por marca). PCM 16-bit mono precomputado en
     * STREAM_ALARM: suena con el teléfono en silencio (manda ese volumen).
     */
    private fun buildBeepTrack(): AudioTrack? {
        val sampleRate = 22050
        val frames = (sampleRate * BEEP_DURATION_MS / 1000).toInt()
        val fade = (sampleRate * 50 / 1000).coerceAtMost(frames / 2)
        val pcm = ShortArray(frames) { i ->
            val env = (minOf(i, frames - 1 - i, fade).toFloat() / fade).coerceIn(0f, 1f)
            (Short.MAX_VALUE * env * kotlin.math.sin(2 * Math.PI * BEEP_FREQ_HZ * i / sampleRate)).toInt().toShort()
        }
        return runCatching {
            AudioTrack(
                AudioManager.STREAM_ALARM, sampleRate, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT, pcm.size * 2, AudioTrack.MODE_STATIC,
            ).apply { write(pcm, 0, pcm.size) }
        }.getOrNull()
    }

    /**
     * Doble persistencia en cada ✓: libreta local (sobrevive a todo) + cola
     * de envío sin drenar en caliente (colapsa a 1 op/día por PK). Un único
     * POST explícito al final = 1 backup + 1 entrada undo (sin ruido).
     */
    private fun persistProgressive() {
        persistLocal()
        val fecha = _state.value.fecha
        val sets = currentDrafts().filter { !it.isBlank() }
        if (sets.isEmpty()) return
        viewModelScope.launch(Dispatchers.IO + NonCancellable) {
            runCatching { repository.enqueueSessionSave(fecha, sets) }
            val pending = runCatching { repository.pendingCount() }.getOrDefault(0)
            _state.value = _state.value.copy(pending = pending)
        }
    }

    /** Una sola carga a la vez: navegar cancela la anterior (sin apilamientos). */
    private var loadJob: Job? = null

    /** Atrapa todo menos cancelación (runCatching la tragaría y rompería el Job). */
    private suspend fun <T> safeIo(block: suspend () -> T): T? = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (_: Exception) {
        null
    }

    fun load(fecha: String) {
        launchLoad(fecha, null)
    }

    fun setVista(vista: String) {
        if (vista != "entrenamiento" && vista != "alimentacion") return
        if (_state.value.vista == vista) return
        launchLoad(_state.value.fecha, vista)
    }

    private fun launchLoad(fecha: String, vista: String?) {
        loadJob?.cancel()
        _state.value = _state.value.copy(
            fecha = fecha,
            vista = vista ?: _state.value.vista,
            loading = true,
            error = null,
            notice = null,
        )
        loadJob = viewModelScope.launch {
            // Fase 1: pintar al instante desde el móvil (caché + libreta).
            paintLocal(fecha)
            // Fase 2: red en segundo plano (drena + refresca o falla en silencio).
            loadInternal(fecha)
        }
    }

    fun shiftDay(deltaDays: Long) {
        val next = runCatching { LocalDate.parse(_state.value.fecha).plusDays(deltaDays).toString() }
            .getOrDefault(LocalDate.now().toString())
        load(next)
    }

    fun goToday() = load(LocalDate.now().toString())

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
                clearLocalRow(fecha)
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

    /** Fecha con aviso offline propio (para limpiarlo al recuperar red). */
    private var offlineNoticeFor: String? = null

    /**
     * Fase 1: pintar al instante desde el móvil, sin esperar red. Con copia:
     * se muestra marcada como última copia; sin copia: aviso amable inmediato.
     * Nunca spinner bloqueante por red.
     */
    private suspend fun paintLocal(fecha: String) {
        localRowCache = fecha to withContext(Dispatchers.IO) {
            safeIo { draftsDao().forFecha(fecha) }
        }
        if (_state.value.vista == "alimentacion") {
            _state.value = _state.value.copy(loading = false, error = null)
            return
        }
        val cached = withContext(Dispatchers.IO) { safeIo { repository.cachedSession(fecha) } }
        offlineNoticeFor = if (cached == null) fecha else null
        _state.value = _state.value.copy(
            loading = false,
            session = cached,
            stale = cached != null,
            error = null,
            notice = if (cached == null) "Sin conexión y sin copia de este día." else null,
        )
    }

    private suspend fun loadInternal(fecha: String) {
        val creds = withContext(Dispatchers.IO) { safeIo { credentials() } }
        if (creds == null) {
            _state.value = _state.value.copy(loading = false, error = "Sin destino configurado (build release sin pairing).")
            return
        }
        val (apiBase2, token2) = creds
        // Si hay borrador y el servidor trae algo distinto de su base, la web
        // editó por debajo: reemplazo silencioso (manda lo web, sin avisos).
        withContext(Dispatchers.IO) {
            ensureActive()
            reconcileDay(apiBase2, token2, fecha)
        }
        // Drenar la cola offline (oportunista, como health_outbox). Cada op
        // entregada o descartada limpia su fila de borrador: ya es servidor.
        val drained = withContext(Dispatchers.IO) {
            ensureActive()
            safeIo {
                repository.drainOutbox(apiBase2, token2) { acked ->
                    if (acked.domain == "sesion") clearLocalRowSync(acked.fecha)
                }
            } ?: 0
        }
        val authBlocked = repository.drainAuthBlocked
        val pending = withContext(Dispatchers.IO) { safeIo { repository.pendingCount() } ?: 0 }
        if (_state.value.vista == "alimentacion") {
            loadNutritionInternal(fecha, creds)
            return
        }
        val view = withContext(Dispatchers.IO) { repository.loadSession(apiBase2, token2, fecha) }
        _state.value = _state.value.copy(
            loading = false,
            session = view.session,
            stale = view.stale,
            error = view.error,
            pending = pending,
            suggestion = null,
            // Con red de vuelta, el aviso offline propio ya no pinta nada.
            notice = if (view.error == null && offlineNoticeFor == fecha) null else _state.value.notice,
        )
        if (view.error == null) offlineNoticeFor = null
        // 401 en el drenado: la cola sigue intacta; avisarlo pesa más que un
        // error de lectura (que ya vendría en view.error si lo hubiera).
        if (authBlocked && _state.value.error == null) {
            _state.value = _state.value.copy(
                error = "Sin autorización: revisa el pairing. Tus datos siguen en el móvil.",
            )
        }
        // Día vacío sin error y sin libreta local: auto-relleno con la rueda
        // (sin guardar). Con borrador nunca se sugiere (lo sombrearía).
        if (view.error == null && (view.session == null || !view.session.hasData) &&
            localRowCache?.second == null
        ) {
            maybeSuggest(fecha, creds)
        }
        // Dots en segundo plano, best-effort: jamás bloquean el pintado.
        val dots = withContext(Dispatchers.IO) {
            val vista = if (_state.value.vista == "alimentacion") "alimentacion" else "entrenamiento"
            when (val d = safeIo { repository.clientFechas(apiBase2, token2, vista) }) {
                is TrainingResult.Ok -> d.value
                else -> _state.value.dots
            }
        }
        _state.value = _state.value.copy(pending = pending, dots = dots)
        if (drained > 0 && _state.value.notice == null && _state.value.error == null) {
            _state.value = _state.value.copy(notice = "$drained cambio(s) enviados al servidor.")
        }
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

    /** Deshace la última acción global (sin botón visible; red de emergencia). */
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
            clearLocalRow(fecha)
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

    // --- Autofill por ejercicio (paridad con la web) --------------------------
    // Al elegir ejercicio trae sus últimos valores (serie i → última serie i;
    // si hay menos historial, replica la última). Siempre sobrescribe la fila.
    // Sin red o sin historial: null (la fila queda en blanco, como la web).

    fun fetchLastSeries(ejercicio: String, pos: Int, onDone: (TrainingSetDraft?) -> Unit) {
        val fecha = _state.value.fecha
        val name = ejercicio.trim()
        if (name.isEmpty() || pos < 1) {
            onDone(null)
            return
        }
        viewModelScope.launch {
            val creds = credentials()
            if (creds == null) {
                onDone(null)
                return@launch
            }
            val (apiBase, token) = creds
            val res = withContext(Dispatchers.IO) {
                repository.loadExerciseLast(apiBase, token, name, fecha)
            }
            if (res !is TrainingResult.Ok || res.value.series.isEmpty()) {
                onDone(null)
                return@launch
            }
            val series = res.value.series
            val pick = series[minOf(pos, series.size) - 1]
            onDone(
                TrainingSetDraft(
                    name,
                    numText(pick.kg),
                    numText(pick.reps),
                    numText(pick.rir),
                    numText(pick.descansoSeg),
                    numText(pick.velocidadKmh),
                    numText(pick.dificultad),
                ),
            )
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
