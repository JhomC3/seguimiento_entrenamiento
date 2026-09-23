package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Reglas de entrada: rangos del servidor replicados en el cliente. */
class BreathingValidationTest {

    @Test
    fun `fases activas minimo medio segundo`() {
        assertEquals(4.2, BreathingValidation.phaseValue("inhale", 4, 2)!!, 0.0)
        assertNull(BreathingValidation.phaseValue("inhale", 0, 4))
        assertEquals(0.5, BreathingValidation.phaseValue("exhale", 0, 5)!!, 0.0)
        assertNull(BreathingValidation.phaseValue("inhale", 61, 0))
    }

    @Test
    fun `sosten admite cero`() {
        assertEquals(0.0, BreathingValidation.phaseValue("holdIn", 0, 0)!!, 0.0)
        assertEquals(3.0, BreathingValidation.phaseValue("endHoldOut", 3, 0)!!, 0.0)
    }

    @Test
    fun `duracion minima 30 salvo libre`() {
        assertTrue(BreathingValidation.durationValid(null))
        assertTrue(BreathingValidation.durationValid(30))
        assertTrue(!BreathingValidation.durationValid(29))
        assertTrue(!BreathingValidation.durationValid(7201))
    }

    @Test
    fun `duracion minutos mas segundos`() {
        assertEquals(750, BreathingValidation.durationValue(12, 30))
        assertNull(BreathingValidation.durationValue(0, 20))
        assertNull(BreathingValidation.durationValue(0, 29))
        assertEquals(30, BreathingValidation.durationValue(0, 30))
    }
}
