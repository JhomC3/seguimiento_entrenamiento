package com.jhomc.healthsync

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Motor puro del pacer: paridad exacta con src/breathing_service.py.
 * Patrón constante: el ciclo no cambia y los vectores congelados
 * (docs/architecture/breathing-vectors.json) fijan `simulate`.
 */
class BreathingEngineTest {

    private val constant = BreathingPattern(inhaleS = 4.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)
    private val withHolds = BreathingPattern(inhaleS = 4.0, holdInS = 2.0, exhaleS = 6.0, holdOutS = 3.0)

    @Test
    fun `ciclo constante no cambia con t`() {
        val engine = BreathingEngine(constant)
        assertEquals(10.0, engine.cycleSeconds(), 0.0)
    }

    @Test
    fun `ciclo con holds suma las cuatro fases`() {
        val engine = BreathingEngine(withHolds)
        assertEquals(15.0, engine.cycleSeconds(), 0.0)
    }

    @Test
    fun `vector constante 120s display igual que API`() {
        // Aceptación de paridad BPM: 120 s 4-0-6-0 → mismo número en el
        // display y en la API (docs/architecture/breathing-vectors.json).
        val engine = BreathingEngine(constant)
        val (ciclos, bpm) = engine.simulate(120)
        assertEquals(12, ciclos)
        assertEquals(6.0, bpm, 0.0)
        assertEquals(6.0, engine.avgBpm(120), 0.0)
        // El tick final redondea los ms activos como el servidor.
        assertEquals(120, secsFromMs(119_600))
        assertEquals(6.0, engine.avgBpm(secsFromMs(119_600).toInt()), 0.0)
        // Sin ciclos completos aún, el display muestra 0 (la API no existe).
        assertEquals(0, engine.simulate(9).first)
        assertEquals(0.0, engine.avgBpm(9), 0.0)
    }

    @Test
    fun `secsFromMs es round half-even de Python`() {
        assertEquals(119, secsFromMs(119_499))
        assertEquals(120, secsFromMs(119_501))
        assertEquals(120, secsFromMs(119_500)) // 119 impar → sube al par
        assertEquals(118, secsFromMs(118_500)) // 118 par → se queda
        assertEquals(0, secsFromMs(0))
    }

    @Test
    fun `vector constante 12 ciclos en 120s`() {
        val engine = BreathingEngine(constant)
        val sched = engine.schedule(120)
        assertEquals(12, engine.cycleCount(sched))
    }

    @Test
    fun `vector exacto 6-6 120s 10 ciclos 5 rpm`() {
        // docs/architecture/breathing-vectors.json: exacto_6_6.
        val engine = BreathingEngine(BreathingPattern(6.0, 0.0, 6.0, 0.0))
        val (ciclos, bpm) = engine.simulate(120)
        assertEquals(10, ciclos)
        assertEquals(5.0, bpm, 0.0)
    }

    @Test
    fun `vector exacto 5-5 120s 12 ciclos 6 rpm`() {
        // docs/architecture/breathing-vectors.json: exacto_5_5.
        val engine = BreathingEngine(BreathingPattern(5.0, 0.0, 5.0, 0.0))
        val (ciclos, bpm) = engine.simulate(120)
        assertEquals(12, ciclos)
        assertEquals(6.0, bpm, 0.0)
    }

    @Test
    fun `ms exactos en fases fraccionarias (4,6 s son 4600 ms)`() {
        val engine = BreathingEngine(BreathingPattern(4.6, 0.0, 2.3, 0.0))
        val steps = engine.cycleSteps()
        assertEquals(4600L, steps.first { it.phase == BreathPhase.INHALE }.durationMs)
        assertEquals(2300L, steps.first { it.phase == BreathPhase.EXHALE }.durationMs)
    }

    @Test
    fun `solo ciclos completos y fases positivas`() {
        val engine = BreathingEngine(constant)
        val sched = engine.schedule(15)
        assertEquals(1, engine.cycleCount(sched))
        assertTrue(sched.all { it.durationMs > 0 })
        // hold 0 no genera paso.
        assertTrue(sched.none { it.phase == BreathPhase.HOLD_IN || it.phase == BreathPhase.HOLD_OUT })
    }

    @Test
    fun `round1 half-up sobre decimal corto`() {
        val engine = BreathingEngine(constant)
        assertEquals(4.7, engine.round1(4.666666666666667), 0.0)
        assertEquals(2.5, engine.round1(2.45), 0.0)
    }

    @Test
    fun `pattern json roundtrip`() {
        val back = BreathingPattern.fromJson(constant.toJson())
        assertEquals(constant, back)
        val holdsBack = BreathingPattern.fromJson(withHolds.toJson())
        assertEquals(withHolds, holdsBack)
    }

    @Test
    fun `fromJson tolera ausentes e ignora rampa vieja`() {
        val p = BreathingPattern.fromJson(JSONObject().put("inhale_s", 4.0).put("exhale_s", 6.0))
        assertEquals(0.0, p.holdInS, 0.0)
        val old = BreathingPattern.fromJson(
            JSONObject().put("inhale_s", 4.0).put("exhale_s", 6.0)
                .put("ramp_sec", 480).put("end_inhale_s", 6.0),
        )
        assertEquals(4.0, old.inhaleS, 0.0)
        assertEquals(6.0, old.exhaleS, 0.0)
    }
}
