package com.jhomc.healthsync

import com.jhomc.healthsync.data.NutritionCacheEntity
import com.jhomc.healthsync.data.OfflineDao
import com.jhomc.healthsync.data.PendingWriteEntity
import com.jhomc.healthsync.data.TrainingCacheDao
import com.jhomc.healthsync.data.TrainingCacheEntity
import com.jhomc.healthsync.data.TrainingCacheMetaEntity
import org.json.JSONArray
import org.json.JSONObject

/**
 * Vista de una sesión para la UI: la sesión (fresca o en caché) más el
 * estado de red. En v1 la escritura es solo online; sin LAN el guardado
 * devuelve error visible en lugar de encolar (la cola offline es v2).
 */
data class SessionView(
    val session: TrainingSession?,
    val stale: Boolean = false,
    val error: String? = null,
)

class TrainingRepository(
    private val cache: TrainingCacheDao,
    private val offline: OfflineDao,
    private val client: TrainingApiClient = TrainingApiClient(),
    private val nowMs: () -> Long = { System.currentTimeMillis() },
) {

    suspend fun loadSession(apiBase: String, token: String, fecha: String): SessionView {
        return when (val res = client.getSession(apiBase, token, fecha)) {
            is TrainingResult.Ok -> {
                persist(res.value)
                SessionView(session = res.value)
            }
            is TrainingResult.ApiError -> {
                val hit = cached(fecha)
                SessionView(session = hit, stale = hit != null, error = res.detail)
            }
            is TrainingResult.NetworkError -> {
                val hit = cached(fecha)
                if (hit != null) {
                    SessionView(session = hit, stale = true, error = "Sin conexión: última copia guardada.")
                } else {
                    SessionView(session = null, error = "Sin conexión con el servidor.")
                }
            }
        }
    }

    /** GET crudo sin persistir (para reconciliar borrador local vs servidor). */
    suspend fun fetchSession(apiBase: String, token: String, fecha: String): TrainingResult<TrainingSession> =
        client.getSession(apiBase, token, fecha)

    /** Última copia local del día (caché; null si nunca se vio con red). */
    suspend fun cachedSession(fecha: String): TrainingSession? = cached(fecha)

    /** Descarta la op pendiente de un dominio+fecha (reemplazo silencioso). */
    suspend fun dropPending(domain: String, fecha: String) {
        offline.ack(domain, fecha)
    }

    suspend fun saveSession(
        apiBase: String,
        token: String,
        fecha: String,
        sets: List<TrainingSetDraft>,
    ): TrainingResult<TrainingSession> {
        return when (val res = client.saveSession(apiBase, token, fecha, sets)) {
            is TrainingResult.Ok -> {
                persist(res.value)
                res
            }
            is TrainingResult.ApiError -> res
            is TrainingResult.NetworkError -> res
        }
    }

    suspend fun deleteSession(apiBase: String, token: String, fecha: String): TrainingResult<Unit> {
        return when (val res = client.deleteSession(apiBase, token, fecha)) {
            is TrainingResult.Ok -> {
                cache.clearDay(fecha, nowMs())
                res
            }
            is TrainingResult.ApiError -> res
            is TrainingResult.NetworkError -> res
        }
    }

    suspend fun loadCatalog(apiBase: String, token: String): TrainingResult<CatalogData> =
        client.getCatalog(apiBase, token)

    // --- B1: plantillas, alta de ejercicio, undo (online-only como el resto) ---

    suspend fun loadTemplates(apiBase: String, token: String): TrainingResult<List<TrainingTemplate>> =
        client.getTemplates(apiBase, token)

    suspend fun applyTemplate(
        apiBase: String,
        token: String,
        plantillaId: Int,
        fecha: String,
    ): TrainingResult<TrainingSession> = client.applyTemplate(apiBase, token, plantillaId, fecha)

    suspend fun saveTemplate(
        apiBase: String,
        token: String,
        nombre: String,
        ejercicios: List<String>,
    ): TrainingResult<TrainingTemplate> = client.saveTemplate(apiBase, token, nombre, ejercicios)

    suspend fun createExercise(
        apiBase: String,
        token: String,
        ejercicio: String,
        grupoMuscular: String,
        categoria: String,
    ): TrainingResult<Unit> = client.createExercise(apiBase, token, ejercicio, grupoMuscular, categoria)

    suspend fun undo(apiBase: String, token: String, fecha: String): TrainingResult<UndoResult> =
        client.undo(apiBase, token, fecha)

    suspend fun loadSuggestion(
        apiBase: String,
        token: String,
        fecha: String,
    ): TrainingResult<Suggestion> = client.getSuggestion(apiBase, token, fecha)

    suspend fun loadExerciseLast(
        apiBase: String,
        token: String,
        ejercicio: String,
        fecha: String,
    ): TrainingResult<ExerciseLast> = client.getExerciseLast(apiBase, token, ejercicio, fecha)

    // --- B3: cardio (online-only como el resto en B3) ---

    suspend fun loadCardioDay(
        apiBase: String,
        token: String,
        fecha: String,
    ): TrainingResult<List<CardioSession>> = client.getCardioDay(apiBase, token, fecha)

    suspend fun annotateCardio(
        apiBase: String,
        token: String,
        hcId: String,
        velocidadKmh: String,
        inclinacionPct: String,
        notas: String,
    ): TrainingResult<Boolean> =
        client.annotateCardio(apiBase, token, hcId, velocidadKmh, inclinacionPct, notas)

    // --- B2: nutrición (online-only en B2; caché unificada en B4) ---

    suspend fun loadNutritionDay(
        apiBase: String,
        token: String,
        fecha: String,
    ): TrainingResult<NutritionDay> = client.getNutritionDay(apiBase, token, fecha)

    suspend fun saveNutritionDay(
        apiBase: String,
        token: String,
        fecha: String,
        entradas: List<FoodDraft>,
        params: NutritionParams?,
    ): TrainingResult<NutritionDay> = client.saveNutritionDay(apiBase, token, fecha, entradas, params)

    suspend fun deleteNutritionDay(
        apiBase: String,
        token: String,
        fecha: String,
    ): TrainingResult<Unit> = client.deleteNutritionDay(apiBase, token, fecha)

    suspend fun loadFoods(apiBase: String, token: String): TrainingResult<FoodsData> =
        client.getFoods(apiBase, token)

    suspend fun createFood(
        apiBase: String,
        token: String,
        nombre: String,
        categoria: String,
        nutrients: Map<String, Double>,
    ): TrainingResult<Unit> = client.createFood(apiBase, token, nombre, categoria, nutrients)

    suspend fun loadMealTemplates(apiBase: String, token: String): TrainingResult<List<MealTemplate>> =
        client.getMealTemplates(apiBase, token)

    suspend fun applyMealTemplate(
        apiBase: String,
        token: String,
        plantillaId: Int,
        fecha: String,
    ): TrainingResult<List<FoodEntry>> = client.applyMealTemplate(apiBase, token, plantillaId, fecha)

    suspend fun saveMealTemplate(
        apiBase: String,
        token: String,
        nombre: String,
        entradas: List<FoodDraft>,
    ): TrainingResult<MealTemplate> = client.saveMealTemplate(apiBase, token, nombre, entradas)

    // --- B4: caché de nutrición + outbox offline ------------------------------------

    suspend fun clientFechas(apiBase: String, token: String, vista: String): TrainingResult<Set<String>> =
        client.getFechas(apiBase, token, vista)

    /** Resultado de lectura nutricional con caché: fresca, rancia o fallo. */
    sealed class CachedDay {
        data class Fresh(val day: NutritionDay) : CachedDay()
        data class Stale(val day: NutritionDay) : CachedDay()
        data class Failed(val detail: String) : CachedDay()
    }

    suspend fun loadNutritionDayCached(
        apiBase: String,
        token: String,
        fecha: String,
    ): CachedDay {
        return when (val res = client.getNutritionDay(apiBase, token, fecha)) {
            is TrainingResult.Ok -> {
                persistNutrition(fecha, res.value)
                CachedDay.Fresh(res.value)
            }
            is TrainingResult.ApiError -> {
                val hit = cachedNutrition(fecha)
                if (hit != null) CachedDay.Stale(hit) else CachedDay.Failed(res.detail)
            }
            is TrainingResult.NetworkError -> {
                val hit = cachedNutrition(fecha)
                if (hit != null) CachedDay.Stale(hit)
                else CachedDay.Failed("Sin conexión: última copia no disponible.")
            }
        }
    }

    suspend fun pendingCount(): Int = offline.pendingCount()

    suspend fun enqueueSessionSave(fecha: String, sets: List<TrainingSetDraft>) {
        val payload = JSONObject().put("fecha", fecha).put(
            "sets",
            JSONArray().apply {
                for (s in sets) {
                    put(
                        JSONObject().put("ejercicio", s.ejercicio)
                            .put("kg", numOrRaw(s.kg)).put("reps", numOrRaw(s.reps))
                            .put("rir", numOrRaw(s.rir)).put("descanso_seg", numOrRaw(s.descansoSeg))
                            .put("velocidad_kmh", numOrRaw(s.velocidadKmh))
                            .put("dificultad", numOrRaw(s.dificultad)),
                    )
                }
            },
        )
        offline.enqueue(PendingWriteEntity("sesion", fecha, "SAVE", payload.toString(), nowMs()))
    }

    suspend fun enqueueSessionDelete(fecha: String) {
        offline.enqueue(
            PendingWriteEntity("sesion", fecha, "DELETE", JSONObject().put("fecha", fecha).toString(), nowMs()),
        )
        cache.clearDay(fecha, nowMs())
    }

    suspend fun enqueueDiarySave(fecha: String, entradas: List<FoodDraft>, params: NutritionParams) {
        val payload = JSONObject().put("fecha", fecha).put(
            "entradas",
            JSONArray().apply {
                for (e in entradas) {
                    put(JSONObject().put("alimento", e.alimento).put("cantidad_g", numOrRaw(e.cantidadG)))
                }
            },
        ).put("peso_kg", params.pesoKg).put("factor_proteina", params.factorProteina)
            .put("factor_grasa", params.factorGrasa).put("kcal_objetivo", params.kcalObjetivo)
        offline.enqueue(PendingWriteEntity("diario", fecha, "SAVE", payload.toString(), nowMs()))
    }

    suspend fun enqueueDiaryDelete(fecha: String) {
        offline.enqueue(
            PendingWriteEntity("diario", fecha, "DELETE", JSONObject().put("fecha", fecha).toString(), nowMs()),
        )
        offline.clearNutrition(fecha)
    }

    /**
     * Drena la cola en orden. Como health_outbox: lo último por día gana
     * (ya colapsado al encolar). Solo `Ok` cuenta como enviada.
     *
     * Regla honesta de descarte: el 401 (autorización) NUNCA descarta —la op
     * se conserva y se avisa— porque borrarla sería perder datos del usuario
     * por un token caducado. 400/404/409/413 sí descartan (rechazo definitivo
     * del servidor). Fallo transitorio o 429 paran conservando el resto.
     * [onAcked] se invoca por cada op confirmada o descartada (para limpiar
     * el borrador local de esa fecha).
     */
    /** true si el último drenado se paró por 401 (cola intacta, revisar pairing). */
    var drainAuthBlocked: Boolean = false
        private set

    suspend fun drainOutbox(
        apiBase: String,
        token: String,
        onAcked: suspend (PendingWriteEntity) -> Unit = {},
        onNutritionFresh: suspend (fecha: String, day: NutritionDay?) -> Unit = { _, _ -> },
    ): Int {
        drainAuthBlocked = false
        var delivered = 0
        for (pending in offline.pendingAll()) {
            val path = when (pending.domain) {
                "sesion" -> TRAINING_API_SESSION_PATH
                else -> NUTRITION_API_DAY_PATH
            }
            val outcome = if (pending.op == "DELETE") {
                client.deleteRaw(apiBase, token, "$path?fecha=${pending.fecha}")
            } else {
                client.postRaw(apiBase, token, path, JSONObject(pending.payloadJson))
            }
            when (outcome) {
                is TrainingResult.Ok -> {
                    offline.ack(pending.domain, pending.fecha)
                    onAcked(pending)
                    delivered++
                    refreshAfterDrain(apiBase, token, pending, onNutritionFresh)
                }
                is TrainingResult.ApiError -> {
                    if (outcome.status == 401) {
                        drainAuthBlocked = true
                        return delivered
                    }
                    offline.ack(pending.domain, pending.fecha)
                    onAcked(pending)
                    // Descarte definitivo de un borrado también limpia HC vía callback.
                    if (pending.domain == "diario" && pending.op == "DELETE") {
                        onNutritionFresh(pending.fecha, null)
                    }
                }
                is TrainingResult.NetworkError -> return delivered
            }
        }
        return delivered
    }

    private suspend fun refreshAfterDrain(
        apiBase: String,
        token: String,
        pending: PendingWriteEntity,
        onNutritionFresh: suspend (fecha: String, day: NutritionDay?) -> Unit = { _, _ -> },
    ) {
        // Tras entregar, la caché refleja el servidor (no el borrador).
        if (pending.domain == "sesion" && pending.op == "SAVE") {
            val fresh = client.getSession(apiBase, token, pending.fecha)
            if (fresh is TrainingResult.Ok) persist(fresh.value)
        } else if (pending.domain == "diario" && pending.op == "SAVE") {
            val fresh = client.getNutritionDay(apiBase, token, pending.fecha)
            if (fresh is TrainingResult.Ok) {
                persistNutrition(pending.fecha, fresh.value)
                onNutritionFresh(pending.fecha, fresh.value)
            }
        } else if (pending.op == "DELETE" && pending.domain == "diario") {
            offline.clearNutrition(pending.fecha)
            onNutritionFresh(pending.fecha, null)
        }
    }

    private suspend fun persistNutrition(fecha: String, day: NutritionDay) {
        offline.putNutrition(NutritionCacheEntity(fecha, nutritionToJson(day).toString(), nowMs()))
    }

    private suspend fun cachedNutrition(fecha: String): NutritionDay? {
        val blob = offline.nutritionFor(fecha) ?: return null
        return runCatching {
            when (val parsed = client.parseNutritionDay(JSONObject(blob.payloadJson))) {
                is TrainingResult.Ok -> parsed.value
                else -> null
            }
        }.getOrNull()
    }

    private fun nutritionToJson(day: NutritionDay): JSONObject {
        fun entry(e: FoodEntry): JSONObject = JSONObject()
            .put("orden", e.orden).put("alimento", e.alimento)
            .put("cantidad_g", e.cantidadG)
            .putAllNutrients(e.nutrients)
        return JSONObject()
            .put("schema_version", TRAINING_API_SCHEMA_VERSION)
            .put("fecha", day.fecha)
            .put("has_data", day.hasData)
            .put("prefilled", day.prefilled)
            .put("prefill_source", day.prefillSource)
            .put("entradas", JSONArray().apply { for (e in day.entradas) put(entry(e)) })
            .put("consumido", JSONObject(day.consumido as Map<*, *>))
            .put("objetivo", JSONObject(day.objetivo as Map<*, *>))
            .put(
                "parametros",
                JSONObject().put("peso_kg", day.parametros.pesoKg)
                    .put("factor_proteina", day.parametros.factorProteina)
                    .put("factor_grasa", day.parametros.factorGrasa)
                    .put("kcal_objetivo", day.parametros.kcalObjetivo),
            )
    }

    private fun JSONObject.putAllNutrients(nutrients: Map<String, Double?>): JSONObject {
        for ((k, v) in nutrients) {
            if (v == null) put(k, JSONObject.NULL) else put(k, v)
        }
        return this
    }

    private suspend fun cached(fecha: String): TrainingSession? {
        val meta = cache.metaFor(fecha) ?: return null
        val rows = cache.rowsFor(fecha)
        if (!meta.hasData) {
            return TrainingSession(fecha, meta.semana, meta.dia, false, emptyList())
        }
        if (rows.isEmpty()) return null
        return TrainingSession(
            fecha = meta.fecha,
            semana = meta.semana,
            dia = meta.dia,
            hasData = true,
            sets = rows.map {
                TrainingSet(it.setOrden, it.ejercicio, it.kg, it.reps, it.rir, it.descansoSeg, it.rm, it.velocidadKmh, it.dificultad)
            },
        )
    }

    private suspend fun persist(session: TrainingSession) {
        cache.replaceDay(
            TrainingCacheMetaEntity(session.fecha, session.semana, session.dia, session.hasData, nowMs()),
            session.sets.map {
                TrainingCacheEntity(
                    fecha = session.fecha,
                    setOrden = it.setOrden,
                    ejercicio = it.ejercicio,
                    kg = it.kg,
                    reps = it.reps,
                    rir = it.rir,
                    descansoSeg = it.descansoSeg,
                    rm = it.rm,
                    velocidadKmh = it.velocidadKmh,
                    dificultad = it.dificultad,
                )
            },
        )
    }
}
