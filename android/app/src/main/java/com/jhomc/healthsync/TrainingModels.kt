package com.jhomc.healthsync

/**
 * Diario de entrenamiento (API v1, training-api-contract.md §2).
 * Los números llegan como Double o null, tal cual en SQLite; el RM lo
 * recalcula siempre el servidor (el cliente solo lo muestra).
 */
data class TrainingSet(
    val setOrden: Int,
    val ejercicio: String,
    val kg: Double?,
    val reps: Double?,
    val rir: Double?,
    val descansoSeg: Double?,
    val rm: Double?,
    val velocidadKmh: Double? = null,
    val dificultad: Double? = null,
) {
    /** HIIT nunca lleva kg/reps/rir; lleva velocidad + dificultad. */
    fun isHiit(): Boolean = ejercicio.trim().equals("HIIT", ignoreCase = true)
}

data class TrainingSession(
    val fecha: String, // ISO YYYY-MM-DD
    val semana: Int,
    val dia: String,
    val hasData: Boolean,
    val sets: List<TrainingSet>,
)

/** Fila del editor: lo que el usuario teclea antes de guardar. */
data class TrainingSetDraft(
    val ejercicio: String,
    val kg: String,
    val reps: String,
    val rir: String,
    val descansoSeg: String,
    val velocidadKmh: String = "",
    val dificultad: String = "",
) {
    fun isHiit(): Boolean = ejercicio.trim().equals("HIIT", ignoreCase = true)

    fun isBlank(): Boolean =
        ejercicio.isBlank() && kg.isBlank() && reps.isBlank() && rir.isBlank() &&
            velocidadKmh.isBlank() && dificultad.isBlank()
}

data class CatalogExercise(
    val ejercicio: String,
    val grupoMuscular: String,
    val categoria: String,
)

data class CatalogCategory(
    val name: String,
    val muscles: List<String>,
)

data class CatalogData(
    val exercises: List<CatalogExercise>,
    val categories: List<CatalogCategory>,
)

data class TrainingTemplate(
    val id: Int,
    val nombre: String,
    val clasificacion: String,
    val ejercicios: List<String>,
)

data class UndoPeek(
    val kind: String, // empty|sesion|entrenos|alimentacion|splits
    val fechaIso: String?,
)

data class UndoResult(
    val kind: String,
    val fechaIso: String?,
    val hasData: Boolean?,
)

/** Fila sugerida por la rueda (pesos de la última vez comparable). */
data class SuggestedSet(
    val ejercicio: String,
    val kg: Double?,
    val reps: Double?,
    val rir: Double?,
    val descansoSeg: Double?,
    val fuenteFecha: String?,
    val velocidadKmh: Double? = null,
    val dificultad: Double? = null,
)

/** Rutina sugerida: tipo rutina|descanso|nada (día con datos o sin propuesta). */
data class Suggestion(
    val tipo: String,
    val fecha: String,
    val explicacion: String,
    val splitId: Int?,
    val slotDia: String?,
    val ejercicios: List<String>,
    val sets: List<SuggestedSet>,
    val pendienteDesde: String?,
)

/** Sesión de cardio del día (Health Connect) con su anotación manual. */
data class CardioSession(
    val hcId: String,
    val titulo: String,
    val duracionMin: Double,
    val velocidadKmh: Double?,
    val inclinacionPct: Double?,
    val notas: String,
)

// --- Modo entreno (Fase 1, solo Android, sin backend) ------------------------

/** Pasos de steppers acordados: kg ±1 (larga ±5). */
const val KG_STEP = 1.0
const val KG_STEP_LONG = 5.0
const val REPS_STEP = 1.0
const val RIR_STEP = 0.1
const val VEL_STEP = 0.5
const val DIF_STEP = 0.5

/** Estado de descanso por serie para la UI (derivado de rest_intervals). */
enum class RestState { IDLE, RUNNING, PAUSED }

fun formatMmSs(totalSeconds: Long): String {
    val s = totalSeconds.coerceAtLeast(0)
    return "%02d:%02d".format(s / 60, s % 60)
}

fun formatMmSsFromMs(ms: Long): String = formatMmSs(ms / 1000)

/** Fila del editor unificado (borrador + uuid local estable por índice). */
data class EntrenoRow(val uuid: String, val draft: TrainingSetDraft)
