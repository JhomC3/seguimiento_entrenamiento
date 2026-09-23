package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Planillas en prefs: tope, roundtrip, corruptas que no rompen. */
class BreathingPlansTest {

    private val pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0)
    private fun plan(nombre: String) = BreathingPlans.Plan(nombre, pattern, 600, SoundStyle.AIRE)

    @Test
    fun `vacio y roundtrip`() {
        assertTrue(BreathingPlans.load("").isEmpty())
        val back = BreathingPlans.load(BreathingPlans.dump(listOf(plan("A"), plan("B"))))
        assertEquals(listOf("A", "B"), back.map { it.nombre })
        assertEquals(600, back[0].duracionS)
        assertEquals(SoundStyle.AIRE, back[1].timbre)
    }

    @Test
    fun `tope ocho y reemplazo por nombre`() {
        var plans = emptyList<BreathingPlans.Plan>()
        for (i in 1..8) {
            plans = BreathingPlans.add(plans, plan("P$i"))!!
        }
        assertNull(BreathingPlans.add(plans, plan("P9")))
        // Mismo nombre reemplaza sin contar como nuevo.
        val updated = BreathingPlans.add(plans, plan("P1"))!!
        assertEquals(8, updated.size)
        assertEquals(listOf("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P1"), updated.map { it.nombre })
    }

    @Test
    fun `nombre vacio se rechaza y borrar inexistente no rompe`() {
        assertNull(BreathingPlans.add(emptyList(), plan("  ")))
        assertTrue(BreathingPlans.remove(listOf(plan("A")), "Z").map { it.nombre } == listOf("A"))
    }

    @Test
    fun `corrupto y version vieja devuelven vacio`() {
        assertTrue(BreathingPlans.load("{no-json").isEmpty())
        assertTrue(BreathingPlans.load("""{"v":999,"planes":[]}""").isEmpty())
        assertTrue(
            BreathingPlans.load("""{"v":1,"planes":[{"nombre":"","pattern":{}}]}""").isEmpty(),
        )
    }
}
