package com.jhomc.healthsync

/**
 * Caminador puro de la sesión (sin Android, sin corrutinas, sin reloj).
 *
 * El llamante (servicio) avanza el tiempo con [advance]; pausar es no llamar
 * (el reloj se congela y reanudar continúa con el restante exacto). Así la
 * pausa/reanudación queda cubierta por tests JVM sin Robolectric.
 *
 * Los ciclos se consumen por grupos (como el servidor): [completedCycles]
 * cuenta respiraciones completas y coincide con `ciclos_completados` del
 * servidor; [Tick.cycle] es la respiración en curso (display).
 * Con timer, la sesión termina al agotar el total (el ciclo en curso se
 * interrumpe). Sin timer (`totalS <= 0`) solo termina con stop explícito.
 */
class Pacer(val pattern: BreathingPattern, val totalS: Int) {

    data class Tick(
        val phase: BreathPhase,
        /** 0..1 transcurrido de la fase (círculo; en REST se congela fuera). */
        val fraction: Float,
        val phaseRemainingMs: Long,
        val totalElapsedMs: Long,
        val totalRemainingMs: Long,
        /** Respiración en curso (display). */
        val cycle: Int,
        val finished: Boolean,
        /** Fase siguiente no-REST (para mostrarla durante el REST). */
        val nextPhase: BreathPhase,
    )

    private val engine = BreathingEngine(pattern)
    private var queue: ArrayDeque<PhaseStep> = ArrayDeque(engine.cycleSteps().withRests())
    private var phaseElapsedMs: Long = 0
    private var totalElapsedMs: Long = 0
    var completedCycles: Int = 0
        private set
    private var done: Boolean = false

    fun finished(): Boolean = done

    fun snapshot(): Tick = tick()

    /** Avanza `deltaMs` (puede cruzar fases y ciclos) y devuelve el estado. */
    fun advance(deltaMs: Long): Tick {
        if (!done && deltaMs > 0) {
            var rest = deltaMs
            while (rest > 0 && !done) {
                val current = queue.first()
                val stepLeft = current.durationMs - phaseElapsedMs
                val totalLeft = if (totalS > 0) totalS * 1000L - totalElapsedMs else Long.MAX_VALUE
                val hop = minOf(rest, stepLeft, totalLeft)
                phaseElapsedMs += hop
                totalElapsedMs += hop
                rest -= hop
                // El ciclo que termina justo con el timer SÍ cuenta: la
                // frontera exacta es respiración completa (como `simulate`).
                if (phaseElapsedMs >= current.durationMs) {
                    queue.removeFirst()
                    phaseElapsedMs = 0
                    if (queue.isEmpty()) {
                        completedCycles++
                        queue = ArrayDeque(engine.cycleSteps().withRests())
                    }
                }
                if (totalS > 0 && totalElapsedMs >= totalS * 1000L) {
                    done = true
                }
            }
        }
        return tick()
    }

    private fun tick(): Tick {
        val current = queue.firstOrNull()
        val frac = if (current != null && current.durationMs > 0) {
            (phaseElapsedMs.toFloat() / current.durationMs).coerceIn(0f, 1f)
        } else {
            1f
        }
        val next = queue.drop(1).firstOrNull { it.phase != BreathPhase.REST }?.phase
            ?: current?.phase?.takeIf { it != BreathPhase.REST }
            ?: BreathPhase.INHALE
        return Tick(
            phase = current?.phase ?: BreathPhase.INHALE,
            fraction = frac,
            phaseRemainingMs = if (current != null) {
                val left = (current.durationMs - phaseElapsedMs).coerceAtLeast(0)
                // La cuenta atrás abarca núcleo + REST de cierre: la fase
                // "dura" su tiempo de patrón exacto (6,0 → 0,0).
                if (current.phase != BreathPhase.REST && queue.getOrNull(1)?.phase == BreathPhase.REST) {
                    left + queue[1].durationMs
                } else {
                    left
                }
            } else {
                0
            },
            totalElapsedMs = totalElapsedMs,
            totalRemainingMs = if (totalS > 0) {
                (totalS * 1000L - totalElapsedMs).coerceAtLeast(0)
            } else {
                -1
            },
            cycle = completedCycles + 1,
            finished = done,
            nextPhase = next,
        )
    }
}
