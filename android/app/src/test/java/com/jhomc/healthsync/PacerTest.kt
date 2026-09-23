package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pacer puro con REST de cierre (300 ms recortados de la cola de cada fase,
 * nunca añadidos). Patrón constante 4/0/6/0: INHALE[0,3.7] REST[3.7,4]
 * EXHALE[4,9.7] REST[9.7,10] por ciclo (10,0 s exactos = tiempo de patrón).
 * La cuenta atrás abarca núcleo + cierre: la fase "dura" 4,0/6,0 s.
 */
class PacerTest {

    private val constant = BreathingPattern(inhaleS = 4.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)

    @Test
    fun `avanza fases con rests de cierre`() {
        val pacer = Pacer(constant, totalS = 120)
        var tick = pacer.snapshot()
        assertEquals(BreathPhase.INHALE, tick.phase)
        assertEquals(1, tick.cycle)
        assertEquals(0, pacer.completedCycles)
        assertEquals(4000L, tick.phaseRemainingMs)
        tick = pacer.advance(3700)
        assertEquals(BreathPhase.REST, tick.phase)
        assertEquals(BreathPhase.EXHALE, tick.nextPhase)
        assertEquals(300L, tick.phaseRemainingMs)
        tick = pacer.advance(300)
        assertEquals(BreathPhase.EXHALE, tick.phase)
        assertEquals(6000L, tick.phaseRemainingMs)
        assertEquals(1, tick.cycle)
        tick = pacer.advance(5700)
        assertEquals(BreathPhase.REST, tick.phase)
        assertEquals(BreathPhase.INHALE, tick.nextPhase)
        assertEquals(0, pacer.completedCycles)
        tick = pacer.advance(300)
        assertEquals(BreathPhase.INHALE, tick.phase)
        assertEquals(2, tick.cycle)
        assertEquals(1, pacer.completedCycles)
    }

    @Test
    fun `pausar es no avanzar (reanuda con el restante)`() {
        val pacer = Pacer(constant, totalS = 120)
        val before = pacer.advance(1500)
        assertEquals(2500L, before.phaseRemainingMs) // 2200 núcleo + 300 cierre
        val frozen = pacer.snapshot()
        assertEquals(before.phaseRemainingMs, frozen.phaseRemainingMs)
        assertEquals(before.totalElapsedMs, frozen.totalElapsedMs)
        val rest = pacer.advance(2200) // total 3700: entra al REST de cierre
        assertEquals(BreathPhase.REST, rest.phase)
        assertEquals(300L, rest.phaseRemainingMs)
        val exhale = pacer.advance(300) // total 4000: exhala en el borde exacto
        assertEquals(BreathPhase.EXHALE, exhale.phase)
        assertEquals(6000L, exhale.phaseRemainingMs)
    }

    @Test
    fun `deadline interrumpe y marca finished`() {
        val pacer = Pacer(constant, totalS = 12)
        val tick = pacer.advance(20_000)
        assertTrue(tick.finished)
        assertTrue(pacer.finished())
        assertEquals(12_000L, tick.totalElapsedMs)
        assertEquals(1, pacer.completedCycles)
        // Avanzar tras finished no mueve el reloj.
        val again = pacer.advance(5000)
        assertEquals(12_000L, again.totalElapsedMs)
    }

    @Test
    fun `sin timer nunca termina solo`() {
        val pacer = Pacer(constant, totalS = -1)
        val tick = pacer.advance(3600_000)
        assertFalse(tick.finished)
        assertEquals(-1L, tick.totalRemainingMs)
        assertEquals(360, pacer.completedCycles)
        assertEquals(361, tick.cycle)
    }

    @Test
    fun `sesion larga constante cuenta exacto (40 ciclos en 600 s)`() {
        // Sin rampa el ciclo es constante: 15 s × 40 = 600 s justos.
        val long = BreathingPattern(inhaleS = 4.0, holdInS = 2.0, exhaleS = 6.0, holdOutS = 3.0)
        val pacer = Pacer(long, totalS = 600)
        var tick = pacer.snapshot()
        while (!tick.finished) {
            tick = pacer.advance(1000)
        }
        assertEquals(600_000L, tick.totalElapsedMs)
        assertEquals(40, pacer.completedCycles)
    }

    @Test
    fun `delta cero o negativo no avanza`() {
        val pacer = Pacer(constant, totalS = 120)
        val a = pacer.advance(1000)
        val b = pacer.advance(0)
        assertEquals(a.totalElapsedMs, b.totalElapsedMs)
    }

    @Test
    fun `6-0-6-0 son 5 rpm exactas (vector exacto_6_6)`() {
        val six = BreathingPattern(inhaleS = 6.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)
        val pacer = Pacer(six, totalS = 120)
        assertEquals(6000L, pacer.snapshot().phaseRemainingMs)
        // La exhalación arranca en el ms 6000 exacto; el ciclo, en el 12000.
        var tick = pacer.advance(6000)
        assertEquals(BreathPhase.EXHALE, tick.phase)
        assertEquals(6000L, tick.phaseRemainingMs)
        tick = pacer.advance(6000)
        assertEquals(BreathPhase.INHALE, tick.phase)
        assertEquals(2, tick.cycle)
        assertEquals(1, pacer.completedCycles)
        // 120 s → 10 ciclos exactos, 5,0 rpm como el servidor.
        tick = pacer.advance(108_000)
        assertEquals(120_000L, tick.totalElapsedMs)
        assertEquals(10, pacer.completedCycles)
        assertEquals(11, tick.cycle)
    }

    @Test
    fun `5-0-5-0 son 6 rpm exactas (vector exacto_5_5)`() {
        val five = BreathingPattern(inhaleS = 5.0, holdInS = 0.0, exhaleS = 5.0, holdOutS = 0.0)
        val pacer = Pacer(five, totalS = 120)
        val tick = pacer.advance(120_000)
        assertEquals(120_000L, tick.totalElapsedMs)
        assertEquals(12, pacer.completedCycles)
    }

    @Test
    fun `la cuenta atras abarca nucleo mas cierre (6,0 a 0,0)`() {
        val six = BreathingPattern(inhaleS = 6.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)
        val pacer = Pacer(six, totalS = 120)
        assertEquals(6000L, pacer.snapshot().phaseRemainingMs)
        assertEquals(5000L, pacer.advance(1000).phaseRemainingMs)
        val rest = pacer.advance(4700) // total 5700: entra al REST de cierre
        assertEquals(BreathPhase.REST, rest.phase)
        assertEquals(300L, rest.phaseRemainingMs)
    }

    @Test
    fun `rest adaptativo en fases minimas (0,5 s)`() {
        val tiny = BreathingPattern(0.5, 0.0, 0.5, 0.0)
        val pacer = Pacer(tiny, totalS = 10)
        // INH[0,250] R[250,500] EXH[500,750] R[750,1000]: ciclo de 1,000 s.
        var tick = pacer.advance(250)
        assertEquals(BreathPhase.REST, tick.phase)
        assertEquals(250L, tick.phaseRemainingMs)
        tick = pacer.advance(250)
        assertEquals(BreathPhase.EXHALE, tick.phase)
        tick = pacer.advance(500)
        assertEquals(BreathPhase.INHALE, tick.phase)
        assertEquals(1, pacer.completedCycles)
    }
}
