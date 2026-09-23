package com.jhomc.healthsync

import org.json.JSONObject

/** Fase del ciclo (vocabulario de Paced Breathing, en inglés a propósito). */
enum class BreathPhase(val label: String) {
    INHALE("Inhale"),
    HOLD_IN("Hold"),
    EXHALE("Exhale"),
    HOLD_OUT("Hold"),
    /** Silencio entre fases (marca el cambio; no es ciclo ni tiene métrica). */
    REST("···"),
}

/**
 * Silencio entre fases: marca el cambio recortado de la COLA de la fase
 * anterior (no la extiende). El ciclo total ≡ tiempo de patrón exacto: el
 * intervalo elegido se cumple al milisegundo, siempre (6/0/6/0 → 12.000 ms
 * = 5,0 rpm; 5/0/5/0 → 10.000 ms = 6,0 rpm). En fases cortas el REST se
 * adapta para no comerse la fase (`min(300, fase/2)`).
 */
const val REST_MS = 300L

/**
 * Parte cada paso en [núcleo + REST de cierre] (misma línea de tiempo en
 * Pacer y tono). La frontera de fase cae en el tiempo de patrón exacto y el
 * total del ciclo no se mueve: el móvil respira lo mismo que calcula el
 * servidor (`simulate`), sin el ±1 de antes.
 */
fun List<PhaseStep>.withRests(): List<PhaseStep> =
    flatMap {
        val rest = minOf(REST_MS, it.durationMs / 2)
        if (rest <= 0L) {
            listOf(it)
        } else {
            listOf(
                it.copy(durationMs = it.durationMs - rest),
                PhaseStep(BreathPhase.REST, rest),
            )
        }
    }

/** Estilo del cue sonoro (elegible en Ajustes, Aire por defecto). */
enum class SoundStyle(val label: String) {
    AIRE("Aire"),
    CUENCO("Cuenco"),
    GLIDE("Glide"),
}

/**
 * Patrón de 4 fases fijas (segundos). Sin rampa: el intervalo elegido se
 * cumple exacto de principio a fin (la rampa se eliminó a petición del
 * usuario; las claves `ramp_sec`/`end_*` entrantes se ignoran).
 */
data class BreathingPattern(
    val inhaleS: Double,
    val holdInS: Double,
    val exhaleS: Double,
    val holdOutS: Double,
) {
    fun cycleSeconds(): Double = inhaleS + holdInS + exhaleS + holdOutS

    fun toJson(): JSONObject = JSONObject()
        .put("inhale_s", inhaleS)
        .put("hold_in_s", holdInS)
        .put("exhale_s", exhaleS)
        .put("hold_out_s", holdOutS)

    companion object {
        fun fromJson(o: JSONObject): BreathingPattern = BreathingPattern(
            inhaleS = o.getDouble("inhale_s"),
            holdInS = o.optDouble("hold_in_s", 0.0),
            exhaleS = o.getDouble("exhale_s"),
            holdOutS = o.optDouble("hold_out_s", 0.0),
        )
    }
}

/** Un paso del pacer: fase + duración ya redondeada. */
data class PhaseStep(val phase: BreathPhase, val durationMs: Long)

/** Sesión terminada, lista para persistir y enviar. */
data class FinishedBreathing(
    val clientSessionId: String,
    val startMs: Long,
    val endMs: Long,
    val tzOffsetMin: Int,
    val plannedS: Int?,
    val pattern: BreathingPattern,
    val completed: Boolean,
)

/** Resultado del POST (métricas del servidor). */
data class BreathingSaveResult(
    val clientSessionId: String,
    val fecha: String,
    val ciclos: Int,
    val bpm: Double,
    val realS: Int,
    val saved: Boolean,
)
