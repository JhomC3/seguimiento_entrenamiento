package com.jhomc.healthsync

import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.roundToLong

/**
 * Motor puro del pacer (sin Android): construye la agenda de fases.
 *
 * Paridad exacta con el servidor: cada fase se redondea a 0.1 s half-up
 * sobre la representación decimal corta del double (igual que
 * `Decimal(str(x))` en Python). Sin rampa: el ciclo es constante y el
 * intervalo elegido se cumple exacto. El vector congelado
 * (docs/architecture/breathing-vectors.json) fija ambas implementaciones
 * en [BreathingEngineTest].
 */
class BreathingEngine(val pattern: BreathingPattern) {

    /** 0.1 s half-up sobre el decimal corto (paridad con Decimal(str(x))). */
    fun round1(value: Double): Double =
        BigDecimal(value.toString()).setScale(1, RoundingMode.HALF_UP).toDouble()

    /** Duración (s) del ciclo (constante: sin rampa). */
    fun cycleSeconds(): Double =
        round1(pattern.inhaleS) + round1(pattern.holdInS) +
            round1(pattern.exhaleS) + round1(pattern.holdOutS)

    /** Pasos de un ciclo (0 si alguna fase es 0). */
    fun cycleSteps(): List<PhaseStep> {
        // round1 devuelve décimas exactas: el redondeo (no el truncado)
        // da los ms enteros exactos (4,6 s → 4600, no 4599).
        fun ms(v: Double): Long = (round1(v) * 1000).roundToLong()
        return listOf(
            PhaseStep(BreathPhase.INHALE, ms(pattern.inhaleS)),
            PhaseStep(BreathPhase.HOLD_IN, ms(pattern.holdInS)),
            PhaseStep(BreathPhase.EXHALE, ms(pattern.exhaleS)),
            PhaseStep(BreathPhase.HOLD_OUT, ms(pattern.holdOutS)),
        ).filter { it.durationMs > 0 }
    }

    /** BPM medio de una sesión de `totalSec` s (display = API con mismos inputs). */
    fun avgBpm(totalSec: Int): Double = simulate(totalSec).second

    /**
     * Port fiel de `simulate(pattern, duracion_real_sec)` del servidor
     * (src/breathing_service.py): cuenta solo ciclos completos que caben en
     * `totalSec` de tiempo de patrón y devuelve `(ciclos, bpm)` con
     * `round(60*ciclos/elapsed, 1)` — half-even sobre el valor binario
     * exacto, igual que el `round()` de Python. El vector congelado de
     * 120 s 4-0-6-0 → (12, 6.0) fija la paridad display ↔ API.
     */
    fun simulate(totalSec: Int): Pair<Int, Double> {
        val cycle = cycleSeconds()
        var ciclos = 0
        var elapsed = 0.0
        while (true) {
            if (cycle <= 0 || elapsed + cycle > totalSec + 1e-9) break
            elapsed += cycle
            ciclos++
        }
        val bpm = if (ciclos == 0) 0.0 else roundPy1(60.0 * ciclos / elapsed)
        return ciclos to bpm
    }

    /** `round(x, 1)` de Python: half-even sobre el binario exacto de `x`. */
    private fun roundPy1(value: Double): Double =
        BigDecimal(value).setScale(1, RoundingMode.HALF_EVEN).toDouble()

    /**
     * Agenda finita que cabe en `totalSec` (solo ciclos completos, como el
     * servidor). `ciclos` = nº de pasos INHALE.
     */
    fun schedule(totalSec: Int): List<PhaseStep> {
        val out = mutableListOf<PhaseStep>()
        var t = 0.0
        val cycle = cycleSeconds()
        while (true) {
            if (cycle <= 0 || t + cycle > totalSec + 1e-9) break
            out += cycleSteps()
            t += cycle
        }
        return out
    }

    fun cycleCount(schedule: List<PhaseStep>): Int = schedule.count { it.phase == BreathPhase.INHALE }
}

/**
 * `round(ms / 1000.0)` de Python: segundos enteros con half-even en los .5.
 * Los ms activos de la sesión se convierten así a los mismos segundos enteros
 * que el servidor calcula con `round((end_ms - start_ms) / 1000)`; con la
 * misma fórmula, display y API devuelven el mismo BPM.
 */
fun secsFromMs(ms: Long): Long {
    val floor = ms / 1000
    val rem = ms % 1000
    return when {
        rem < 500 -> floor
        rem > 500 -> floor + 1
        else -> if (floor % 2 == 0L) floor else floor + 1
    }
}
