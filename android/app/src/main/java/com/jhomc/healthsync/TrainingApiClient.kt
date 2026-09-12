package com.jhomc.healthsync

import java.io.IOException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

const val TRAINING_API_SCHEMA_VERSION = 1
const val TRAINING_API_SESSION_PATH = "/api/v1/sesion"
const val TRAINING_API_EXERCISES_PATH = "/api/v1/ejercicios"
const val TRAINING_API_TEMPLATES_PATH = "/api/v1/plantillas"
const val TRAINING_API_TEMPLATE_APPLY_PATH = "/api/v1/plantilla/aplicar"
const val TRAINING_API_TEMPLATE_SAVE_PATH = "/api/v1/plantilla/guardar"
const val TRAINING_API_EXERCISE_CREATE_PATH = "/api/v1/ejercicio"
const val TRAINING_API_UNDO_PATH = "/api/v1/undo"
const val TRAINING_API_UNDO_PEEK_PATH = "/api/v1/undo/peek"
const val NUTRITION_API_DAY_PATH = "/api/v1/diario"
const val NUTRITION_API_FOODS_PATH = "/api/v1/alimentos"
const val NUTRITION_API_FOOD_CREATE_PATH = "/api/v1/alimento"
const val NUTRITION_API_MEAL_TEMPLATES_PATH = "/api/v1/plantillas-comida"
const val NUTRITION_API_MEAL_APPLY_PATH = "/api/v1/plantilla-comida/aplicar"
const val NUTRITION_API_MEAL_SAVE_PATH = "/api/v1/plantilla-comida/guardar"
const val SUGGESTION_API_PATH = "/api/v1/sugerencia"
const val CARDIO_API_DAY_PATH = "/api/v1/cardio"
const val CARDIO_API_ANNOTATE_PATH = "/api/v1/cardio/anotacion"
const val DATES_API_PATH = "/api/v1/fechas"
const val TRAINING_API_MAX_SETS = 100

sealed class TrainingResult<out T> {
    data class Ok<T>(val value: T) : TrainingResult<T>()
    /** Error permanente: 400/401/404/409/413 o contrato inesperado (no reintentar igual). */
    data class ApiError(val status: Int, val detail: String) : TrainingResult<Nothing>()
    /** Error transitorio: red caída o 5xx (reintentable, tira de caché). */
    data class NetworkError(val detail: String) : TrainingResult<Nothing>()
}

/**
 * Cliente JSON de la API v1 del diario (training-api-contract.md).
 * Autentica con el mismo X-Sync-Token que Health Connect y nunca lo registra
 * en logs. El allowHttp=true cubre la LAN debug (http://192.168.x); release
 * exige HTTPS (misma política que HealthSyncClient).
 */
class TrainingApiClient(
    private val http: OkHttpClient = defaultClient(),
) {

    fun getSession(apiBase: String, token: String, fecha: String): TrainingResult<TrainingSession> =
        get("$apiBase$TRAINING_API_SESSION_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseSession(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun getCatalog(apiBase: String, token: String): TrainingResult<CatalogData> =
        get("$apiBase$TRAINING_API_EXERCISES_PATH", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseCatalog(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun saveSession(
        apiBase: String,
        token: String,
        fecha: String,
        sets: List<TrainingSetDraft>,
    ): TrainingResult<TrainingSession> {
        if (sets.isEmpty() || sets.size > TRAINING_API_MAX_SETS) {
            return TrainingResult.ApiError(-1, "La sesión lleva de 1 a $TRAINING_API_MAX_SETS series.")
        }
        val body = JSONObject()
            .put("fecha", fecha)
            .put("sets", JSONArray().apply {
                for (s in sets) {
                    put(JSONObject()
                        .put("ejercicio", s.ejercicio)
                        .put("kg", numOrRaw(s.kg))
                        .put("reps", numOrRaw(s.reps))
                        .put("rir", numOrRaw(s.rir))
                        .put("descanso_seg", numOrRaw(s.descansoSeg))
                        .put("velocidad_kmh", numOrRaw(s.velocidadKmh))
                        .put("dificultad", numOrRaw(s.dificultad)))
                }
            })
        return when (val raw = post("$apiBase$TRAINING_API_SESSION_PATH", token, body)) {
            is TrainingResult.Ok -> parseSession(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun deleteSession(apiBase: String, token: String, fecha: String): TrainingResult<Unit> =
        delete("$apiBase$TRAINING_API_SESSION_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> TrainingResult.Ok(Unit)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    // --- B1: plantillas, alta de ejercicio, undo --------------------------------

    fun getTemplates(apiBase: String, token: String): TrainingResult<List<TrainingTemplate>> =
        get("$apiBase$TRAINING_API_TEMPLATES_PATH", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseTemplates(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    /** Preview de un entreno sobre una fecha, sin escribir (como la web). */
    fun applyTemplate(
        apiBase: String,
        token: String,
        plantillaId: Int,
        fecha: String,
    ): TrainingResult<TrainingSession> {
        val body = JSONObject().put("plantilla_id", plantillaId).put("fecha", fecha)
        return when (val raw = post("$apiBase$TRAINING_API_TEMPLATE_APPLY_PATH", token, body)) {
            is TrainingResult.Ok -> parsePreview(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun saveTemplate(
        apiBase: String,
        token: String,
        nombre: String,
        ejercicios: List<String>,
    ): TrainingResult<TrainingTemplate> {
        val body = JSONObject()
            .put("nombre", nombre)
            .put("ejercicios", JSONArray(ejercicios))
        return when (val raw = post("$apiBase$TRAINING_API_TEMPLATE_SAVE_PATH", token, body)) {
            is TrainingResult.Ok -> parseSavedTemplate(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun createExercise(
        apiBase: String,
        token: String,
        ejercicio: String,
        grupoMuscular: String,
        categoria: String,
    ): TrainingResult<Unit> {
        val body = JSONObject()
            .put("ejercicio", ejercicio)
            .put("grupo_muscular", grupoMuscular)
            .put("categoria", categoria)
        return when (val raw = post("$apiBase$TRAINING_API_EXERCISE_CREATE_PATH", token, body)) {
            is TrainingResult.Ok -> TrainingResult.Ok(Unit)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun undoPeek(apiBase: String, token: String): TrainingResult<UndoPeek> =
        get("$apiBase$TRAINING_API_UNDO_PEEK_PATH", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseUndoPeek(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun undo(apiBase: String, token: String, fecha: String): TrainingResult<UndoResult> {
        val body = JSONObject().put("fecha", fecha)
        return when (val raw = post("$apiBase$TRAINING_API_UNDO_PATH", token, body)) {
            is TrainingResult.Ok -> parseUndoResult(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    /** Rutina sugerida del día (rueda split+historial, sin escribir). */
    fun getSuggestion(apiBase: String, token: String, fecha: String): TrainingResult<Suggestion> =
        get("$apiBase$SUGGESTION_API_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseSuggestion(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    // --- B3: cardio ---------------------------------------------------------------

    fun getCardioDay(apiBase: String, token: String, fecha: String): TrainingResult<List<CardioSession>> =
        get("$apiBase$CARDIO_API_DAY_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseCardioDay(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    /** Anota una sesión (todo vacío = borrar). Devuelve true si se borró. */
    fun annotateCardio(
        apiBase: String,
        token: String,
        hcId: String,
        velocidadKmh: String,
        inclinacionPct: String,
        notas: String,
    ): TrainingResult<Boolean> {
        val body = JSONObject()
            .put("hc_id", hcId)
            .put("velocidad_kmh", numOrRaw(velocidadKmh))
            .put("inclinacion_pct", numOrRaw(inclinacionPct))
            .put("notas", notas)
        return when (val raw = post("$apiBase$CARDIO_API_ANNOTATE_PATH", token, body)) {
            is TrainingResult.Ok -> runCatching {
                TrainingResult.Ok(raw.value.getBoolean("deleted"))
            }.getOrElse { TrainingResult.ApiError(-1, "Respuesta malformada del servidor.") }
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    private fun parseCardioDay(json: JSONObject): TrainingResult<List<CardioSession>> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val items = json.optJSONArray("sesiones")?.let { raw ->
                (0 until raw.length()).map { i ->
                    val s = raw.getJSONObject(i)
                    CardioSession(
                        hcId = s.getString("hc_id"),
                        titulo = s.optString("titulo", "Sesión de ejercicio"),
                        duracionMin = s.optDouble("duracion_min", 0.0),
                        velocidadKmh = s.optDoubleOrNull("velocidad_kmh"),
                        inclinacionPct = s.optDoubleOrNull("inclinacion_pct"),
                        notas = s.optString("notas", ""),
                    )
                }
            } ?: emptyList()
            TrainingResult.Ok(items)
        }.getOrElse { TrainingResult.ApiError(-1, "Cardio malformado del servidor.") }
    }

    // --- B4: fechas con datos (dots) + reemisión de payloads encolados ---------

    fun getFechas(apiBase: String, token: String, vista: String): TrainingResult<Set<String>> =
        get("$apiBase$DATES_API_PATH?vista=$vista", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> runCatching {
                    checkVersion(raw.value)?.let { return it }
                    val arr = raw.value.optJSONArray("fechas")
                    TrainingResult.Ok(
                        (0 until (arr?.length() ?: 0)).map { i -> arr!!.getString(i) }.toSet(),
                    )
                }.getOrElse { TrainingResult.ApiError(-1, "Fechas malformadas del servidor.") }
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    /** Reemite un payload de la cola tal cual se encoló (ya validado en origen). */
    fun postRaw(apiBase: String, token: String, path: String, payload: JSONObject): TrainingResult<JSONObject> =
        execute(
            Request.Builder()
                .url("$apiBase$path")
                .addHeader("X-Sync-Token", token)
                .addHeader("Content-Type", "application/json; charset=utf-8")
                .post(payload.toString().toRequestBody(JSON_MEDIA_TYPE))
                .build(),
        )

    fun deleteRaw(apiBase: String, token: String, path: String): TrainingResult<JSONObject> =
        execute(
            Request.Builder()
                .url("$apiBase$path")
                .addHeader("X-Sync-Token", token)
                .delete()
                .build(),
        )

    private fun parseSuggestion(json: JSONObject): TrainingResult<Suggestion> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val sets = json.optJSONArray("sets")?.let { raw ->
                (0 until raw.length()).map { i ->
                    val s = raw.getJSONObject(i)
                    SuggestedSet(
                        ejercicio = s.optString("ejercicio", ""),
                        kg = s.optDoubleOrNull("kg"),
                        reps = s.optDoubleOrNull("reps"),
                        rir = s.optDoubleOrNull("rir"),
                        descansoSeg = s.optDoubleOrNull("descanso_seg"),
                        fuenteFecha = s.optString("fuente_fecha", "").ifBlank { null },
                        velocidadKmh = s.optDoubleOrNull("velocidad_kmh"),
                        dificultad = s.optDoubleOrNull("dificultad"),
                    )
                }
            } ?: emptyList()
            TrainingResult.Ok(
                Suggestion(
                    tipo = json.optString("tipo", "nada"),
                    fecha = json.optString("fecha", ""),
                    explicacion = json.optString("explicacion", ""),
                    splitId = if (json.isNull("split_id")) null else json.optInt("split_id"),
                    slotDia = json.optString("slot_dia", "").ifBlank { null },
                    ejercicios = json.optJSONArray("ejercicios")?.let { arr ->
                        (0 until arr.length()).map { j -> arr.getString(j) }
                    } ?: emptyList(),
                    sets = sets,
                    pendienteDesde = json.optString("pendiente_desde", "").ifBlank { null },
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Sugerencia malformada del servidor.") }
    }

    // --- HTTP -----------------------------------------------------------------

    private fun authed(url: String, token: String, builder: Request.Builder): Request =
        builder.url(url)
            .addHeader("X-Sync-Token", token)
            .addHeader("Content-Type", "application/json; charset=utf-8")
            .build()

    private fun get(url: String, token: String): TrainingResult<JSONObject> {
        val request = authed(url, token, Request.Builder().get())
        return execute(request)
    }

    private fun post(url: String, token: String, body: JSONObject): TrainingResult<JSONObject> {
        val request = authed(url, token, Request.Builder().post(body.toString().toRequestBody(JSON_MEDIA_TYPE)))
        return execute(request)
    }

    private fun delete(url: String, token: String): TrainingResult<JSONObject> {
        val request = authed(url, token, Request.Builder().delete())
        return execute(request)
    }

    private fun execute(request: Request): TrainingResult<JSONObject> {
        return try {
            http.newCall(request).execute().use { response ->
                val body = response.body?.string()
                when {
                    response.isSuccessful -> {
                        if (body == null) TrainingResult.NetworkError("respuesta vacía")
                        else runCatching { TrainingResult.Ok(JSONObject(body)) }
                            .getOrElse { TrainingResult.NetworkError("respuesta malformada") }
                    }
                    response.code == 400 || response.code == 401 || response.code == 404 ||
                        response.code == 409 || response.code == 413 ->
                        TrainingResult.ApiError(response.code, detailOf(body))
                    else -> TrainingResult.NetworkError("HTTP ${response.code}")
                }
            }
        } catch (e: IOException) {
            TrainingResult.NetworkError(e.message ?: "red no disponible")
        }
    }

    // --- Parsing (contrato §2; desconocidos se ignoran, versión mayor se rechaza) ---

    private fun checkVersion(json: JSONObject): TrainingResult.ApiError? {
        val version = json.optInt("schema_version", -1)
        if (version != TRAINING_API_SCHEMA_VERSION) {
            return TrainingResult.ApiError(-1, "Servidor con schema_version=$version (app: v$TRAINING_API_SCHEMA_VERSION). Actualiza la app.")
        }
        return null
    }

    private fun parseTrainingSet(s: JSONObject, index: Int): TrainingSet = TrainingSet(
        setOrden = s.optInt("set_orden", index + 1),
        ejercicio = s.optString("ejercicio", ""),
        kg = s.optDoubleOrNull("kg"),
        reps = s.optDoubleOrNull("reps"),
        rir = s.optDoubleOrNull("rir"),
        descansoSeg = s.optDoubleOrNull("descanso_seg"),
        rm = s.optDoubleOrNull("rm"),
        velocidadKmh = s.optDoubleOrNull("velocidad_kmh"),
        dificultad = s.optDoubleOrNull("dificultad"),
    )

    private fun parseSession(json: JSONObject): TrainingResult<TrainingSession> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val sets = json.getJSONArray("sets").let { raw ->
                (0 until raw.length()).map { i -> parseTrainingSet(raw.getJSONObject(i), i) }
            }
            TrainingResult.Ok(
                TrainingSession(
                    fecha = json.getString("fecha"),
                    semana = json.optInt("semana", 0),
                    dia = json.optString("dia", ""),
                    hasData = json.optBoolean("has_data", sets.isNotEmpty()),
                    sets = sets,
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Sesión malformada del servidor.") }
    }

    private fun parseCatalog(json: JSONObject): TrainingResult<CatalogData> {
        return runCatching {
            checkVersion(json)
            val items = json.getJSONArray("ejercicios").let { raw ->
                (0 until raw.length()).map { i ->
                    val e = raw.getJSONObject(i)
                    CatalogExercise(
                        ejercicio = e.getString("ejercicio"),
                        grupoMuscular = e.optString("grupo_muscular", ""),
                        categoria = e.optString("categoria", ""),
                    )
                }
            }
            // meta aditiva (v1.1): los APK viejos la ignoran.
            val categories = json.optJSONObject("meta")?.optJSONArray("categorias")?.let { raw ->
                (0 until raw.length()).map { i ->
                    val c = raw.getJSONObject(i)
                    CatalogCategory(
                        name = c.getString("name"),
                        muscles = c.optJSONArray("muscles")?.let { m ->
                            (0 until m.length()).map { j -> m.getString(j) }
                        } ?: emptyList(),
                    )
                }
            } ?: emptyList()
            TrainingResult.Ok(CatalogData(items, categories))
        }.getOrElse { TrainingResult.ApiError(-1, "Catálogo malformado del servidor.") }
    }

        private fun parseTemplates(json: JSONObject): TrainingResult<List<TrainingTemplate>> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val items = json.getJSONArray("plantillas").let { raw ->
                (0 until raw.length()).map { i ->
                    val p = raw.getJSONObject(i)
                    TrainingTemplate(
                        id = p.getInt("id"),
                        nombre = p.getString("nombre"),
                        clasificacion = p.optString("clasificacion", ""),
                        ejercicios = p.optJSONArray("ejercicios")?.let { arr ->
                            (0 until arr.length()).map { j -> arr.getString(j) }
                        } ?: emptyList(),
                    )
                }
            }
            TrainingResult.Ok(items)
        }.getOrElse { TrainingResult.ApiError(-1, "Plantillas malformadas del servidor.") }
    }

    /** El preview de aplicar comparte forma con la sesión (sets con RM). */
    private fun parsePreview(json: JSONObject): TrainingResult<TrainingSession> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val sets = json.getJSONArray("sets").let { raw ->
                (0 until raw.length()).map { i -> parseTrainingSet(raw.getJSONObject(i), i) }
            }
            TrainingResult.Ok(
                TrainingSession(
                    fecha = json.getString("fecha"),
                    semana = json.optInt("semana", 0),
                    dia = json.optString("dia", ""),
                    hasData = sets.isNotEmpty(),
                    sets = sets,
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Preview malformado del servidor.") }
    }

    private fun parseSavedTemplate(json: JSONObject): TrainingResult<TrainingTemplate> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val p = json.getJSONObject("plantilla")
            TrainingResult.Ok(
                TrainingTemplate(
                    id = p.getInt("id"),
                    nombre = p.getString("nombre"),
                    clasificacion = p.optString("clasificacion", ""),
                    ejercicios = p.optJSONArray("ejercicios")?.let { arr ->
                        (0 until arr.length()).map { j -> arr.getString(j) }
                    } ?: emptyList(),
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Respuesta malformada del servidor.") }
    }

    private fun parseUndoPeek(json: JSONObject): TrainingResult<UndoPeek> {
        return runCatching {
            checkVersion(json)?.let { return it }
            TrainingResult.Ok(
                UndoPeek(
                    kind = json.getString("kind"),
                    fechaIso = json.optString("fecha_iso", "").ifBlank { null },
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Respuesta malformada del servidor.") }
    }

    private fun parseUndoResult(json: JSONObject): TrainingResult<UndoResult> {
        return runCatching {
            checkVersion(json)?.let { return it }
            TrainingResult.Ok(
                UndoResult(
                    kind = json.getString("kind"),
                    fechaIso = json.optString("fecha_iso", "").ifBlank { null },
                    hasData = if (json.isNull("has_data")) null else json.optBoolean("has_data"),
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Respuesta malformada del servidor.") }
    }

    // --- B2: nutrición ------------------------------------------------------------

    fun getNutritionDay(apiBase: String, token: String, fecha: String): TrainingResult<NutritionDay> =
        get("$apiBase$NUTRITION_API_DAY_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseNutritionDay(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun saveNutritionDay(
        apiBase: String,
        token: String,
        fecha: String,
        entradas: List<FoodDraft>,
        params: NutritionParams?,
    ): TrainingResult<NutritionDay> {
        if (entradas.isEmpty() || entradas.size > TRAINING_API_MAX_SETS) {
            return TrainingResult.ApiError(-1, "El día lleva de 1 a $TRAINING_API_MAX_SETS alimentos.")
        }
        val body = JSONObject()
            .put("fecha", fecha)
            .put("entradas", JSONArray().apply {
                for (e in entradas) {
                    put(JSONObject()
                        .put("alimento", e.alimento)
                        .put("cantidad_g", numOrRaw(e.cantidadG)))
                }
            })
        if (params != null) {
            body.put("peso_kg", params.pesoKg)
                .put("factor_proteina", params.factorProteina)
                .put("factor_grasa", params.factorGrasa)
                .put("kcal_objetivo", params.kcalObjetivo)
        }
        return when (val raw = post("$apiBase$NUTRITION_API_DAY_PATH", token, body)) {
            is TrainingResult.Ok -> parseNutritionDay(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun deleteNutritionDay(apiBase: String, token: String, fecha: String): TrainingResult<Unit> =
        delete("$apiBase$NUTRITION_API_DAY_PATH?fecha=$fecha", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> TrainingResult.Ok(Unit)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun getFoods(apiBase: String, token: String): TrainingResult<FoodsData> =
        get("$apiBase$NUTRITION_API_FOODS_PATH", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseFoods(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun createFood(
        apiBase: String,
        token: String,
        nombre: String,
        categoria: String,
        nutrients: Map<String, Double>,
    ): TrainingResult<Unit> {
        val body = JSONObject().put("nombre", nombre).put("categoria", categoria)
        for (field in NUTRIENT_FIELDS) body.put(field, nutrients[field] ?: 0.0)
        return when (val raw = post("$apiBase$NUTRITION_API_FOOD_CREATE_PATH", token, body)) {
            is TrainingResult.Ok -> TrainingResult.Ok(Unit)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun getMealTemplates(apiBase: String, token: String): TrainingResult<List<MealTemplate>> =
        get("$apiBase$NUTRITION_API_MEAL_TEMPLATES_PATH", token).let { raw ->
            when (raw) {
                is TrainingResult.Ok -> parseMealTemplates(raw.value)
                is TrainingResult.ApiError -> raw
                is TrainingResult.NetworkError -> raw
            }
        }

    fun applyMealTemplate(
        apiBase: String,
        token: String,
        plantillaId: Int,
        fecha: String,
    ): TrainingResult<List<FoodEntry>> {
        val body = JSONObject().put("plantilla_id", plantillaId).put("fecha", fecha)
        return when (val raw = post("$apiBase$NUTRITION_API_MEAL_APPLY_PATH", token, body)) {
            is TrainingResult.Ok -> parseMealPreview(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    fun saveMealTemplate(
        apiBase: String,
        token: String,
        nombre: String,
        entradas: List<FoodDraft>,
    ): TrainingResult<MealTemplate> {
        val body = JSONObject()
            .put("nombre", nombre)
            .put("entradas", JSONArray().apply {
                for (e in entradas) {
                    put(JSONObject()
                        .put("alimento", e.alimento)
                        .put("cantidad_g", numOrRaw(e.cantidadG)))
                }
            })
        return when (val raw = post("$apiBase$NUTRITION_API_MEAL_SAVE_PATH", token, body)) {
            is TrainingResult.Ok -> parseSavedMealTemplate(raw.value)
            is TrainingResult.ApiError -> raw
            is TrainingResult.NetworkError -> raw
        }
    }

    private fun parseNutrientMap(json: JSONObject): Map<String, Double?> =
        NUTRIENT_FIELDS.associateWith { json.optDoubleOrNull(it) }

    private fun parseFoodEntry(s: JSONObject, index: Int): FoodEntry = FoodEntry(
        orden = s.optInt("orden", index + 1),
        alimento = s.optString("alimento", ""),
        cantidadG = s.optDoubleOrNull("cantidad_g"),
        nutrients = parseNutrientMap(s),
    )

    internal fun parseNutritionDay(json: JSONObject): TrainingResult<NutritionDay> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val params = json.getJSONObject("parametros")
            TrainingResult.Ok(
                NutritionDay(
                    fecha = json.getString("fecha"),
                    hasData = json.optBoolean("has_data", false),
                    prefilled = json.optBoolean("prefilled", false),
                    prefillSource = json.optString("prefill_source", "").ifBlank { null },
                    entradas = json.optJSONArray("entradas")?.let { raw ->
                        (0 until raw.length()).map { i -> parseFoodEntry(raw.getJSONObject(i), i) }
                    } ?: emptyList(),
                    consumido = json.getJSONObject("consumido").let { o ->
                        (NUTRIENT_FIELDS + "cantidad_g").associateWith { o.optDouble(it, 0.0) }
                    },
                    objetivo = json.getJSONObject("objetivo").let { o ->
                        NUTRIENT_FIELDS.associateWith { o.optDouble(it, 0.0) }
                    },
                    parametros = NutritionParams(
                        pesoKg = params.optDouble("peso_kg", 70.0),
                        factorProteina = params.optDouble("factor_proteina", 1.5),
                        factorGrasa = params.optDouble("factor_grasa", 1.1),
                        kcalObjetivo = params.optDouble("kcal_objetivo", 2300.0),
                    ),
                ),
            )
        }.getOrElse { TrainingResult.ApiError(-1, "Día nutricional malformado del servidor.") }
    }

    private fun parseFoods(json: JSONObject): TrainingResult<FoodsData> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val items = json.getJSONArray("alimentos").let { raw ->
                (0 until raw.length()).map { i ->
                    val a = raw.getJSONObject(i)
                    FoodItem(
                        nombre = a.getString("nombre"),
                        categoria = a.optString("categoria", ""),
                        nutrients = parseNutrientMap(a),
                    )
                }
            }
            val labels = json.optJSONObject("meta")?.optJSONArray("nutrientes")?.let { raw ->
                (0 until raw.length()).map { i ->
                    val n = raw.getJSONObject(i)
                    NutrientLabel(n.getString("name"), n.optString("label", n.getString("name")))
                }
            } ?: NUTRIENT_FIELDS.map { NutrientLabel(it, it) }
            TrainingResult.Ok(FoodsData(items, labels))
        }.getOrElse { TrainingResult.ApiError(-1, "Catálogo malformado del servidor.") }
    }

    private fun parseMealTemplates(json: JSONObject): TrainingResult<List<MealTemplate>> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val items = json.getJSONArray("plantillas").let { raw ->
                (0 until raw.length()).map { i ->
                    val p = raw.getJSONObject(i)
                    MealTemplate(
                        id = p.getInt("id"),
                        nombre = p.getString("nombre"),
                        alimentos = p.optJSONArray("alimentos")?.let { arr ->
                            (0 until arr.length()).map { j ->
                                val a = arr.getJSONObject(j)
                                FoodDraft(a.optString("alimento", ""), a.opt("cantidad_g")?.toString() ?: "")
                            }
                        } ?: emptyList(),
                    )
                }
            }
            TrainingResult.Ok(items)
        }.getOrElse { TrainingResult.ApiError(-1, "Plantillas malformadas del servidor.") }
    }

    private fun parseMealPreview(json: JSONObject): TrainingResult<List<FoodEntry>> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val rows = json.getJSONArray("entradas").let { raw ->
                (0 until raw.length()).map { i -> parseFoodEntry(raw.getJSONObject(i), i) }
            }
            TrainingResult.Ok(rows)
        }.getOrElse { TrainingResult.ApiError(-1, "Preview malformado del servidor.") }
    }

    private fun parseSavedMealTemplate(json: JSONObject): TrainingResult<MealTemplate> {
        return runCatching {
            checkVersion(json)?.let { return it }
            val p = json.getJSONObject("plantilla")
            TrainingResult.Ok(MealTemplate(p.getInt("id"), p.getString("nombre"), emptyList()))
        }.getOrElse { TrainingResult.ApiError(-1, "Respuesta malformada del servidor.") }
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        // Timeouts cortos: el diario pinta desde el móvil y la red es
        // segundo plano (fail-fast). Solo lo usa TrainingRepository.
        private fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()

        /**
         * Base explícita de la API: el override de build (DEFAULT_API_BASE)
         * gana; si está vacío se recorta el sufijo exacto de sync de la URL
         * guardada. Cualquier otra URL es error (nunca adivinar paths).
         */
        fun resolveApiBase(syncUrl: String, apiBaseOverride: String = ""): Result<String> {
            if (apiBaseOverride.isNotBlank()) return Result.success(apiBaseOverride.trimEnd('/'))
            val trimmed = syncUrl.trimEnd('/')
            val suffix = "/sync/health-connect"
            if (trimmed.endsWith(suffix)) {
                val base = trimmed.removeSuffix(suffix)
                if (base.isNotEmpty()) return Result.success(base)
            }
            return Result.failure(IllegalArgumentException("Sin base de API (ni DEFAULT_API_BASE ni URL de sync válida)"))
        }

        fun apiBaseFor(syncUrl: String, apiBaseOverride: String = ""): String? =
            resolveApiBase(syncUrl, apiBaseOverride).getOrNull()
    }
}

/** JSONObject.getDouble falla con null; esto devuelve null en null/ausente/no-numérico. */
private fun JSONObject.optDoubleOrNull(key: String): Double? {
    if (isNull(key)) return null
    return runCatching { getDouble(key) }.getOrNull()
}

private fun detailOf(body: String?): String {
    if (body == null) return "error del servidor"
    return runCatching { JSONObject(body).optString("detail", "error del servidor") }
        .getOrDefault("error del servidor")
        .ifBlank { "error del servidor" }
}

/** Envía número como número (para que el servidor valide rango real). */
internal fun numOrRaw(raw: String): Any {
    val t = raw.trim()
    if (t.isEmpty()) return ""
    return t.toDoubleOrNull() ?: t
}
