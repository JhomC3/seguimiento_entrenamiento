package com.jhomc.healthsync

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin

/**
 * Sonidos finitos por fase (sin Android).
 *
 * Un ciclo = una lista de buffers de duración exacta ([PhaseBuffer]) que se
 * reutiliza idéntica cada ciclo (sin rampa no hay nada que evolucione). El
 * estado del sintetizador (legato, ruido rosa, tañidos) fluye continuo
 * DURANTE la generación del ciclo, así que las junturas entre buffers no
 * chascan por construcción. Cada fase sonora lleva sus fundidos incluidos
 * (~250 ms asentarse/retomar alrededor del silencio de cierre).
 *
 * El llamante (servicio) escribe los buffers por trozos siguiendo el reloj
 * de pared; pausar = dejar de escribir + vaciar el altavoz (instantáneo).
 * Sin adelantos, sin hilos, sin puntos de retorno, sin rebobinado.
 *
 * - GLIDE: seno con glide legato (inhala 220→294 Hz, exhala 294→220 Hz,
 *   sostén 174.6 Hz) + 2º armónico tenue.
 * - CUENCO: tañido por fase (inhala 220, exhala 174.6, sostén 146.8 Hz,
 *   fundamental + 2 armónicos con caída); el tañido nuevo ahoga al anterior.
 * - AIRE: ruido rosa filtrado que respira (crece/mengua/tenue).
 */
class SessionTone(
    val style: SoundStyle,
    val pattern: BreathingPattern,
    seed: Long = System.nanoTime(),
) {

    companion object {
        /** Tasa de este aparato (la nativa lo deja mudo: no tocar). */
        const val SAMPLE_RATE = 22050
        /** Fundido de salida hacia el REST de cierre (la pausa se "asienta"). */
        const val REST_FADE_OUT_MS = 250.0
        /** Fundido de entrada desde el REST (la fase "retoma", no aparece). */
        const val REST_FADE_IN_MS = 250.0
        /** Ataque global de sesión (nadie quiere un chasquido al empezar). */
        const val SESSION_ATTACK_MS = 2000L
        /** Ahogo del tañido anterior al entrar fase (cuenco): nota nueva corta. */
        const val CHOKE_TAU_S = 0.010
    }

    /** Un sonido de fase listo para escribir (se reutiliza cada ciclo). */
    data class PhaseBuffer(val phase: BreathPhase, val durMs: Long, val pcm: ShortArray)

    private val engine = BreathingEngine(pattern)

    /** Xorshift64* propio: determinismo total con la semilla. */
    private var rngState: Long = seed or 1L

    private fun nextUnit(): Double {
        var x = rngState
        x = x xor (x shl 13)
        x = x xor (x ushr 7)
        x = x xor (x shl 17)
        rngState = x
        return ((x ushr 11).toDouble() / (1L shl 53).toDouble()) * 2.0 - 1.0
    }

    // Estado continuo de síntesis (vive durante la generación de un ciclo).
    private var tSamples: Long = 0
    private var phaseAcc: Double = 0.0
    private var freqSm: Double = startFreq()
    private var gainSm: Double = 0.0
    private val pink = DoubleArray(7)
    private var lowpass: Double = 0.0
    private var noiseOut: Double = 0.0
    private val strikes = mutableListOf<Strike>()

    data class Strike(
        val baseHz: Double,
        val t0Samples: Long,
        val attackMs: Long,
        val tauMs: Double,
        val gain: Double,
        /** Muestra en que un tañido posterior lo ahogó (null = vigente). */
        var chokedAtSamples: Long? = null,
    )

    private fun startFreq(): Double = when (style) {
        SoundStyle.GLIDE -> 220.0
        else -> 174.6
    }

    /**
     * Un ciclo completo en buffers de duración exacta. Determinista por
     * (estilo, patrón, semilla, ataque): se puede llamar cuantas veces sea y
     * el estado se reinicia al empezar. Con `withAttack`, los primeros 2 s
     * entran suave (igual que siempre: nadie quiere un chasquido al empezar).
     */
    fun cycleBuffers(withAttack: Boolean = false): List<PhaseBuffer> {
        resetState()
        val steps = engine.cycleSteps().withRests()
        return steps.mapIndexed { i, s ->
            val prev = steps[(i - 1 + steps.size) % steps.size].phase
            renderStep(s.phase, s.durationMs, prevWasRest = prev == BreathPhase.REST, attack = withAttack)
        }
    }

    private fun resetState() {
        tSamples = 0
        phaseAcc = 0.0
        freqSm = startFreq()
        gainSm = 0.0
        pink.fill(0.0)
        lowpass = 0.0
        noiseOut = 0.0
        strikes.clear()
    }

    private fun renderStep(
        phase: BreathPhase,
        durMs: Long,
        prevWasRest: Boolean,
        releaseMs: Long? = null,
        attack: Boolean = false,
    ): PhaseBuffer {
        val n = (durMs * SAMPLE_RATE / 1000.0).toLong().coerceAtLeast(1).toInt()
        if (phase == BreathPhase.REST) {
            // El cuenco tañe al entrar al silencio (igual que siempre) y ese
            // repique cruza a la fase siguiente; el ruido rosa se congela.
            if (style == SoundStyle.CUENCO) strikeRest()
            tSamples += n
            return PhaseBuffer(phase, durMs, ShortArray(n))
        }
        if (style == SoundStyle.CUENCO) strike(phase, durMs)
        val fadeIn = if (prevWasRest) {
            minOf(REST_FADE_IN_MS, durMs / 2.0).coerceAtLeast(1.0)
        } else {
            0.0
        }
        val fadeOut = releaseMs?.toDouble()?.coerceAtLeast(1.0)
            ?: minOf(REST_FADE_OUT_MS, durMs / 2.0).coerceAtLeast(1.0)
        val pcm = ShortArray(n)
        val dt = 1.0 / SAMPLE_RATE
        for (i in 0 until n) {
            val pos = i.toDouble() / n
            var edge = 1.0
            val doneMs = i * 1000.0 / SAMPLE_RATE
            val leftMs = (n - i) * 1000.0 / SAMPLE_RATE
            if (doneMs < fadeIn) edge = minOf(edge, smooth((doneMs / fadeIn).toFloat()).toDouble())
            if (leftMs < fadeOut) edge = minOf(edge, smooth((leftMs / fadeOut).toFloat()).toDouble())
            // Ataque global de sesión (primeros 2 s): entra suave, igual que siempre.
            if (attack) {
                val clockMs = (tSamples + i) * 1000.0 / SAMPLE_RATE
                if (clockMs < SESSION_ATTACK_MS) {
                    edge *= smooth((clockMs / SESSION_ATTACK_MS).toFloat()).toDouble()
                }
            }
            pcm[i] = synthSample(phase, pos, dt, edge)
            tSamples++
        }
        return PhaseBuffer(phase, durMs, pcm)
    }

    /** Tañido al entrar al REST (146.8 Hz tenue que cruza a la fase siguiente). */
    private fun strikeRest() {
        for (old in strikes) {
            if (old.chokedAtSamples == null) old.chokedAtSamples = tSamples
        }
        strikes.add(Strike(146.83, tSamples, 80L, 300.0, 0.5))
        if (strikes.size > 8) strikes.removeFirst()
    }

    private fun strike(phase: BreathPhase, durMs: Long) {
        val base = when (phase) {
            BreathPhase.INHALE -> 220.0
            BreathPhase.EXHALE -> 174.61
            else -> 146.83
        }
        // Nota nueva corta la anterior: las vigentes se ahogan en ~30 ms.
        for (old in strikes) {
            if (old.chokedAtSamples == null) old.chokedAtSamples = tSamples
        }
        val dur = durMs.coerceAtLeast(300L)
        // Inhala florece tarde (crescendo: el pico cae donde la envolvente
        // está alta); exhala nace arriba y cae (ataque rápido, como siempre).
        val attackFrac = if (phase == BreathPhase.INHALE) 0.45 else 0.12
        // La caída dura la fase completa (sin tope): la que dibuja el
        // triángulo /\/\ es la envolvente, no la caída propia. El ahogo
        // entre fases y la cola del REST siguen igual.
        strikes.add(
            Strike(base, tSamples, (dur * attackFrac).toLong().coerceAtLeast(80L), dur.toDouble(), baseGainFor(phase)),
        )
        if (strikes.size > 8) strikes.removeFirst()
    }

    /**
     * Ganancia del tañido: el inhala compensa (1.2) para que su pico —tardío
     * por el ataque lento— iguale al de exhala (0.5, pico temprano con
     * envolvente alta). Sostenes tenues, como siempre.
     */
    internal fun baseGainFor(phase: BreathPhase): Double = when (phase) {
        BreathPhase.HOLD_IN, BreathPhase.HOLD_OUT -> 0.3
        BreathPhase.INHALE -> 1.2
        else -> 0.5
    }

    private fun smooth(t: Float): Float {
        val x = t.coerceIn(0f, 1f)
        return x * x * (3 - 2 * x)
    }

    /**
     * Envolvente común (la de AIRE, congelada): inhala crece 0.15→0.85,
     * exhala mengua 0.85→0.15, sostenes tenues 0.20. GLIDE y CUENCO la usan
     * normalizada a media 1.0 (`swell·2`); `airSample` no la llama (su
     * código queda intacto y suena byte-idéntico).
     */
    private fun swellFor(phase: BreathPhase, pos: Double): Double = when (phase) {
        BreathPhase.INHALE -> 0.15 + 0.70 * pos
        BreathPhase.EXHALE -> 0.85 - 0.70 * pos
        else -> 0.20
    }

    private fun synthSample(phase: BreathPhase, pos: Double, dt: Double, edge: Double = 1.0): Short {
        stepNoise()
        val sample = when (style) {
            SoundStyle.GLIDE -> glideSample(phase, pos, dt)
            SoundStyle.CUENCO -> bowlSample(phase, pos)
            SoundStyle.AIRE -> airSample(phase, pos, dt)
        }
        return (Short.MAX_VALUE * sample * edge).toInt()
            .coerceIn(Short.MIN_VALUE.toInt() + 1, Short.MAX_VALUE.toInt()).toShort()
    }

    private fun glideSample(phase: BreathPhase, pos: Double, dt: Double): Double {
        val freqTarget = when (phase) {
            BreathPhase.INHALE -> 220.0 + (294.0 - 220.0) * pos
            BreathPhase.EXHALE -> 294.0 + (220.0 - 294.0) * pos
            else -> 174.6
        }
        val gainTarget = if (phase == BreathPhase.INHALE || phase == BreathPhase.EXHALE) {
            // Misma respiración que AIRE (media 1.0: el nivel medio no cambia).
            0.55 * swellFor(phase, pos) * 2.0
        } else {
            0.35
        }
        freqSm += (freqTarget - freqSm) * (1 - exp(-dt / 0.08))
        gainSm += (gainTarget - gainSm) * (1 - exp(-dt / 0.10))
        phaseAcc += 2 * PI * freqSm * dt
        return gainSm * (sin(phaseAcc) + 0.15 * sin(2 * phaseAcc))
    }

    private fun bowlSample(phase: BreathPhase, pos: Double): Double {
        var s = 0.0
        val iter = strikes.iterator()
        while (iter.hasNext()) {
            val st = iter.next()
            val ageSamples = tSamples - st.t0Samples
            if (ageSamples < 0) continue
            val ageMs = ageSamples * 1000.0 / SAMPLE_RATE
            var env = smooth((ageMs / st.attackMs).toFloat()) * exp(-ageMs / st.tauMs)
            // Ahogado por un tañido posterior: muere en ~30 ms, sin clic.
            st.chokedAtSamples?.let { chokedAt ->
                val chokedMs = (tSamples - chokedAt) * 1000.0 / SAMPLE_RATE
                if (chokedMs >= 0) env *= exp(-chokedMs / (CHOKE_TAU_S * 1000.0))
            }
            if (env < 0.002 && ageMs > st.attackMs) {
                iter.remove()
                continue
            }
            // Fase en muestras exactas (ms enteros darían saltos de ~80°).
            val ph = 2 * PI * st.baseHz * ageSamples / SAMPLE_RATE
            s += st.gain * env * (sin(ph) + 0.35 * sin(2 * ph) + 0.15 * sin(3 * ph)) / 1.5
        }
        // Misma respiración que AIRE en fases activas (media 1.0: el nivel
        // medio no cambia); sostenes y REST intactos. Tañidos, caídas y
        // ahogos sin tocar.
        return if (phase == BreathPhase.INHALE || phase == BreathPhase.EXHALE) {
            s * swellFor(phase, pos) * 2.0
        } else {
            s
        }
    }

    private fun airSample(phase: BreathPhase, pos: Double, dt: Double): Double {
        lowpass += 0.05 * (noiseOut - lowpass)
        val swellTarget = when (phase) {
            BreathPhase.INHALE -> 0.15 + 0.70 * pos
            BreathPhase.EXHALE -> 0.85 - 0.70 * pos
            else -> 0.20
        }
        gainSm += (swellTarget - gainSm) * (1 - exp(-dt / 0.30))
        return 0.5 * gainSm * lowpass * 2.0
    }

    /** Un paso de ruido rosa (fuente compartida: aire + chiff). */    private fun stepNoise(): Double {
        val white = nextUnit()
        pink[0] = 0.99886 * pink[0] + white * 0.0555179
        pink[1] = 0.99332 * pink[1] + white * 0.0750759
        pink[2] = 0.96900 * pink[2] + white * 0.1538520
        pink[3] = 0.86650 * pink[3] + white * 0.3104856
        pink[4] = 0.55000 * pink[4] + white * 0.5329522
        pink[5] = -0.7616 * pink[5] - white * 0.0168980
        noiseOut = (pink[0] + pink[1] + pink[2] + pink[3] + pink[4] + pink[5] + pink[6] + white * 0.5362) * 0.11
        pink[6] = white * 0.115926
        return noiseOut
    }
}
