package com.jhomc.healthsync

/**
 * Reglas de entrada del pacer (misma fuente para los diálogos y los tests).
 * Los rangos replican al servidor (src/breathing_service.py): inhala/exhala
 * 0.5–60 s, sostén 0–60 s, duración 30 s–2 h (o Libre).
 */
object BreathingValidation {

    /** Rango válido para una clave de fase (segundos). */
    fun phaseRange(key: String): ClosedRange<Double> = when (key) {
        "inhale", "exhale" -> 0.5..60.0
        else -> 0.0..60.0
    }

    /** Combina segundos + décimas; null si fuera de rango. */
    fun phaseValue(key: String, seconds: Int, tenths: Int): Double? {
        if (seconds !in 0..60 || tenths !in 0..9) return null
        val value = seconds + tenths / 10.0
        return if (value in phaseRange(key)) value else null
    }

    /** Duración total válida (`null` = Libre). */
    fun durationValid(totalS: Int?): Boolean =
        totalS == null || totalS in 30..7200

    /** Minutos+segundos → total o null si inválido (Libre se maneja aparte). */
    fun durationValue(minutes: Int, seconds: Int): Int? {
        if (minutes !in 0..120 || seconds !in 0..59) return null
        val total = minutes * 60 + seconds
        return if (durationValid(total)) total else null
    }
}
