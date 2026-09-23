package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Reproductor estático: conmuta por fase, pausa retiene, roto se marca. */
class StaticPhasePlayerTest {

    private class FakeSlot : StaticPhasePlayer.StaticSlot {
        var plays = 0
        var pauses = 0
        var resumes = 0
        var stops = 0
        var faded = 0
        var released = 0

        override fun playFromStart() {
            plays++
        }

        override fun pause() {
            pauses++
        }

        override fun resume() {
            resumes++
        }

        override fun stop() {
            stops++
        }

        override fun release() {
            released++
        }

        override fun fadeOutAndStop() {
            faded++
        }
    }

    @Test
    fun `playAt conmuta y no reinicia la misma`() {
        val slots = listOf(FakeSlot(), FakeSlot())
        val player = StaticPhasePlayer(slots)
        player.playAt(0)
        player.playAt(0)
        assertEquals(1, slots[0].plays)
        player.playAt(1)
        assertEquals(1, slots[0].stops)
        assertEquals(1, slots[1].plays)
    }

    @Test
    fun `stopCurrent pausa y resume delegan`() {
        val slots = listOf(FakeSlot())
        val player = StaticPhasePlayer(slots)
        player.playAt(0)
        player.pause()
        assertEquals(1, slots[0].pauses)
        player.resume()
        assertEquals(1, slots[0].resumes)
        player.stopCurrent()
        assertEquals(1, slots[0].stops)
        // Sin actual: pausa/resume no hacen nada.
        player.pause()
        player.resume()
        assertEquals(1, slots[0].pauses)
        assertEquals(1, slots[0].resumes)
    }

    @Test
    fun `stopAllWithFade y release delegan`() {
        val slots = listOf(FakeSlot())
        val player = StaticPhasePlayer(slots)
        player.playAt(0)
        player.stopAllWithFade()
        assertEquals(1, slots[0].faded)
        player.release()
        assertEquals(1, slots[0].released)
    }

    @Test
    fun `slot nulo marca roto pero los validos suenan`() {
        val player = StaticPhasePlayer(listOf(FakeSlot(), null))
        assertTrue(player.broken)
        player.playAt(0)
        assertTrue(player.broken)
    }

    @Test
    fun `create con fabrica que falla marca roto sin reventar`() {
        val player = StaticPhasePlayer.create(
            listOf(ShortArray(10), ShortArray(10)),
            factory = { null },
        )
        assertTrue(player.broken)
    }

    @Test
    fun `create con fabrica sana deja reproductor util`() {
        val player = StaticPhasePlayer.create(
            listOf(ShortArray(10), ShortArray(10)),
            factory = { FakeSlot() },
        )
        assertTrue(!player.broken)
        player.playAt(0)
        player.stopCurrent()
        player.release()
    }
}
