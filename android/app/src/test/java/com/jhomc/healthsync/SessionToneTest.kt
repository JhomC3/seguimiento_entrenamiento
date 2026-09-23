package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Sonidos finitos por fase: duraciones exactas en muestras, silencios de
 * cierre exactos, fundidos incluidos (sin chasquido), determinismo y gesto
 * de cada estilo. Sin Android (semilla fija).
 */
class SessionToneTest {

    private val pattern = BreathingPattern(inhaleS = 4.0, holdInS = 2.0, exhaleS = 6.0, holdOutS = 3.0)
    private val noHold = BreathingPattern(inhaleS = 4.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)
    private val six = BreathingPattern(inhaleS = 6.0, holdInS = 0.0, exhaleS = 6.0, holdOutS = 0.0)

    private val sr = SessionTone.SAMPLE_RATE

    private fun maxAbs(pcm: ShortArray, from: Int, to: Int): Int {
        var m = 0
        for (i in from.coerceAtLeast(0) until to.coerceAtMost(pcm.size)) {
            val a = kotlin.math.abs(pcm[i].toInt())
            if (a > m) m = a
        }
        return m
    }

    private fun rms(pcm: ShortArray, from: Int, to: Int): Double {
        val a = from.coerceAtLeast(0)
        val b = to.coerceAtMost(pcm.size)
        if (b <= a) return 0.0
        var sum = 0.0
        for (i in a until b) sum += pcm[i] * pcm[i].toDouble()
        return sum / (b - a)
    }

    private fun rmsSec(pcm: ShortArray, aSec: Double, bSec: Double): Double =
        rms(pcm, (aSec * sr).toInt(), (bSec * sr).toInt())

    private fun concatArrays(parts: List<ShortArray>): ShortArray {
        val total = parts.sumOf { it.size }
        val out = ShortArray(total)
        var pos = 0
        for (b in parts) {
            b.copyInto(out, pos)
            pos += b.size
        }
        return out
    }

    private fun concat(buffers: List<SessionTone.PhaseBuffer>): ShortArray =
        concatArrays(buffers.map { it.pcm })

    /** Ciclos repetidos hasta cubrir `secs` segundos. */
    private fun render(style: SoundStyle, pattern: BreathingPattern, seed: Long, secs: Int): ShortArray {
        val tone = SessionTone(style, pattern, seed)
        val cycle = tone.cycleBuffers().map { it.pcm }
        val need = secs * sr
        val out = mutableListOf<ShortArray>()
        var n = 0
        while (n < need) {
            for (b in cycle) {
                out += b
                n += b.size
                if (n >= need) break
            }
        }
        return concatArrays(out)
    }

    @Test
    fun `ciclo 6-6 cuatro buffers de duracion exacta`() {
        val buffers = SessionTone(SoundStyle.GLIDE, six, seed = 43L).cycleBuffers()
        assertEquals(
            listOf(BreathPhase.INHALE, BreathPhase.REST, BreathPhase.EXHALE, BreathPhase.REST),
            buffers.map { it.phase },
        )
        assertEquals(listOf(5700L, 300L, 5700L, 300L), buffers.map { it.durMs })
        // En muestras exactas a 22050 Hz: 5700 ms = 125685, 300 ms = 6615.
        assertEquals(listOf(125685, 6615, 125685, 6615), buffers.map { it.pcm.size })
        assertEquals(12 * sr, buffers.sumOf { it.pcm.size })
    }

    @Test
    fun `rests son ceros exactos en los tres estilos`() {
        for (style in SoundStyle.entries) {
            val buffers = SessionTone(style, six, seed = 41L).cycleBuffers()
            for (b in buffers.filter { it.phase == BreathPhase.REST }) {
                assertTrue("$style rest no silencioso", b.pcm.all { it == 0.toShort() })
            }
        }
    }

    @Test
    fun `determinista con misma semilla`() {
        val a = SessionTone(SoundStyle.AIRE, pattern, seed = 3L).cycleBuffers()
        val b = SessionTone(SoundStyle.AIRE, pattern, seed = 3L).cycleBuffers()
        assertEquals(a.size, b.size)
        for (i in a.indices) {
            assertTrue(a[i].pcm.indices.all { a[i].pcm[it] == b[i].pcm[it] })
        }
    }

    @Test
    fun `fundidos incluidos sin chasquido en los bordes`() {
        for (style in SoundStyle.entries) {
            val inhale = SessionTone(style, six, seed = 7L).cycleBuffers()
                .first { it.phase == BreathPhase.INHALE }.pcm
            val edge = 2205 // primeros/últimos 100 ms
            val midFrom = inhale.size / 2 - sr / 2
            val mid = rms(inhale, midFrom, midFrom + sr)
            assertTrue("$style sin energía en el medio", mid > 100.0 * 100.0)
            assertTrue(
                "$style borde ruidoso",
                maxAbs(inhale, 0, edge) < mid / 4 && maxAbs(inhale, inhale.size - edge, inhale.size) < mid / 4,
            )
        }
    }

    @Test
    fun `continuidad en las junturas del ciclo`() {
        for (style in SoundStyle.entries) {
            val pcm = concat(SessionTone(style, noHold, seed = 11L).cycleBuffers())
            // Fronteras INHALE→REST→EXHALE→REST (núcleos 3700/5700 + rests 300).
            val cuts = listOf(3700 * sr / 1000 - 1, 4000 * sr / 1000 - 1, 9700 * sr / 1000 - 1)
            for (c in cuts) {
                val d = kotlin.math.abs(pcm[c].toInt() - pcm[c + 1].toInt())
                assertTrue("$style salto $d en $c", d < 9000)
            }
        }
    }

    private fun crossings(pcm: ShortArray, from: Int, to: Int): Int {
        var n = 0
        for (i in from + 1 until to.coerceAtMost(pcm.size)) {
            if ((pcm[i - 1] < 0) != (pcm[i] < 0)) n++
        }
        return n
    }

    private fun rate(pcm: ShortArray, fromSec: Int, toSec: Int): Double {
        val from = fromSec * sr
        val to = toSec * sr
        return crossings(pcm, from, to).toDouble() / (toSec - fromSec)
    }

    @Test
    fun `glide inhala sube y exhala baja`() {
        val pcm = render(SoundStyle.GLIDE, noHold, 9L, 30)
        // Primer ciclo: inhala 0-3.7 s, exhala 4-9.7 s.
        assertTrue(rate(pcm, 2, 3) > rate(pcm, 1, 2))
        assertTrue(rate(pcm, 4, 7) > rate(pcm, 7, 10))
    }

    @Test
    fun `aire crece al inicio y mengua al exhalar`() {
        val pcm = render(SoundStyle.AIRE, noHold, 13L, 30)
        // La exhalación arranca fuerte: más energía que el final de la inhalación.
        assertTrue(rmsSec(pcm, 4.5, 6.5) > rmsSec(pcm, 2.0, 3.4))
        // Exhala en núcleo [4,9.7]: primera mitad con más energía.
        assertTrue(rmsSec(pcm, 5.0, 7.0) > rmsSec(pcm, 7.5, 9.3))
    }

    /** Energía en la fracción [a,b) de un buffer (evita los fundidos de borde). */
    private fun rmsFrac(pcm: ShortArray, a: Double, b: Double): Double =
        rms(pcm, (pcm.size * a).toInt(), (pcm.size * b).toInt())

    @Test
    fun `glide respira como aire (inhala crece, exhala mengua)`() {
        val buffers = SessionTone(SoundStyle.GLIDE, noHold, seed = 7L).cycleBuffers()
        val inhale = buffers.first { it.phase == BreathPhase.INHALE }.pcm
        val exhale = buffers.first { it.phase == BreathPhase.EXHALE }.pcm
        assertTrue(rmsFrac(inhale, 0.55, 0.70) > rmsFrac(inhale, 0.30, 0.45))
        assertTrue(rmsFrac(exhale, 0.30, 0.45) > rmsFrac(exhale, 0.55, 0.70))
    }

    @Test
    fun `cuenco acompana la fase (exhala decae, inhala sostiene)`() {
        val buffers = SessionTone(SoundStyle.CUENCO, noHold, seed = 17L).cycleBuffers()
        val inhale = buffers.first { it.phase == BreathPhase.INHALE }.pcm
        val exhale = buffers.first { it.phase == BreathPhase.EXHALE }.pcm
        // Exhala: caída del tañido + envolvente a favor → decae fuerte.
        assertTrue(rmsFrac(exhale, 0.30, 0.45) > rmsFrac(exhale, 0.55, 0.70))
        // Inhala: la envolvente compensa la caída → sostiene, no colapsa.
        assertTrue(rmsFrac(inhale, 0.55, 0.70) > 0.5 * rmsFrac(inhale, 0.30, 0.45))
    }

    @Test
    fun `triangulo continuo en los tres estilos (cierra arriba y abajo)`() {
        for (style in SoundStyle.entries) {
            val buffers = SessionTone(style, noHold, seed = 17L).cycleBuffers()
            val inhale = buffers.first { it.phase == BreathPhase.INHALE }.pcm
            val exhale = buffers.first { it.phase == BreathPhase.EXHALE }.pcm
            // Arribas: fin de inhala y arranque de exhala; abajos: arranque
            // de inhala y fin de exhala (ventanas fuera de los fundidos).
            val top1 = rmsFrac(inhale, 0.70, 0.90)
            val top2 = rmsFrac(exhale, 0.10, 0.30)
            val bot1 = rmsFrac(inhale, 0.05, 0.20)
            val bot2 = rmsFrac(exhale, 0.75, 0.92)
            assertTrue("$style sin triangulo: $top1 $top2 vs $bot1 $bot2", minOf(top1, top2) > 2 * maxOf(bot1, bot2))
        }
    }

    @Test
    fun `cuenco inhala llega arriba como exhala (picos a la par)`() {
        for ((style, lo, hi) in listOf(Triple(SoundStyle.CUENCO, 0.8, 1.25), Triple(SoundStyle.GLIDE, 0.7, 1.4))) {
            val buffers = SessionTone(style, noHold, seed = 17L).cycleBuffers()
            val pi = maxAbs(buffers.first { it.phase == BreathPhase.INHALE }.pcm, 0, Int.MAX_VALUE)
            val pe = maxAbs(buffers.first { it.phase == BreathPhase.EXHALE }.pcm, 0, Int.MAX_VALUE)
            val r = pi.toDouble() / pe.toDouble()
            assertTrue("$style picos inh=$pi exh=$pe ratio=$r", r in lo..hi)
        }
    }

    @Test
    fun `cuenco exhala decae y el sosten es tenue`() {
        val pcm = render(SoundStyle.CUENCO, noHold, 17L, 30)
        // Exhala en núcleo [4,9.7]: primera parte con más energía.
        assertTrue(rmsSec(pcm, 5.0, 7.0) > rmsSec(pcm, 7.5, 9.3))
        // El sostén suena con menos ganancia que las fases activas.
        val tone = SessionTone(SoundStyle.CUENCO, pattern, seed = 17L)
        assertEquals(0.3, tone.baseGainFor(BreathPhase.HOLD_IN), 0.0)
        assertEquals(1.2, tone.baseGainFor(BreathPhase.INHALE), 0.0)
        assertEquals(0.5, tone.baseGainFor(BreathPhase.EXHALE), 0.0)
    }

    @Test
    fun `rest recortado silencio exacto cada ciclo`() {
        val pcm = render(SoundStyle.GLIDE, six, 43L, 20)
        // REST [5700,6000) y [17700,18000): ceros exactos con margen.
        val rest = pcm.slice((5.75 * sr).toInt() until (5.95 * sr).toInt())
        assertTrue("rest no silencioso", rest.all { it == 0.toShort() })
        val rest2 = pcm.slice((17.75 * sr).toInt() until (17.95 * sr).toInt())
        assertTrue("rest2 no silencioso", rest2.all { it == 0.toShort() })
    }

    @Test
    fun `primer ciclo entra suave y el resto igual`() {
        val steady = SessionTone(SoundStyle.AIRE, six, seed = 7L).cycleBuffers()
        val attack = SessionTone(SoundStyle.AIRE, six, seed = 7L).cycleBuffers(withAttack = true)
        fun energy(buffers: List<SessionTone.PhaseBuffer>): Double {
            var sum = 0.0
            var n = 0
            for (b in buffers) for (s in b.pcm) {
                sum += s * s.toDouble()
                n++
            }
            return sum / n
        }
        // El ataque solo atenúa el arranque: menos energía total...
        assertTrue(energy(attack) < energy(steady))
        // ...y pasado el arranque suenan idéntico.
        val tailA = attack.flatMap { it.pcm.toList() }.takeLast(sr * 2)
        val tailS = steady.flatMap { it.pcm.toList() }.takeLast(sr * 2)
        assertTrue(tailA.indices.all { tailA[it] == tailS[it] })
    }
}
