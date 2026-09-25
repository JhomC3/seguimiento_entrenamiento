package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordTypesTest {

    @Test
    fun `type names are unique`() {
        val names = RecordTypes.all.map { it.typeName }
        assertEquals(names.size, names.distinct().size)
    }

    @Test
    fun `permissions resolve to the health prefix`() {
        // getReadPermission may return the same permission for grouped types
        // (e.g. sleep/session), so uniqueness is NOT a contract; validity is.
        RecordTypes.all.forEach { entry ->
            assertTrue(entry.typeName, entry.permission.startsWith("android.permission.health."))
            assertFalse(entry.permission.isBlank())
        }
    }

    @Test
    fun `every entry has permission and family`() {
        RecordTypes.all.forEach { entry ->
            assertTrue(entry.typeName.isNotBlank())
            assertTrue(entry.permission.startsWith("android.permission.health."))
            assertFalse(entry.family.name.isBlank())
        }
    }

    @Test
    fun `sensitive types are not in the core batch`() {
        RecordTypes.core.forEach { assertFalse(it.sensitivity == Sensitivity.SENSITIVE) }
    }

    @Test
    fun `core batch is non empty and every family is grouped`() {
        assertTrue(RecordTypes.core.isNotEmpty())
        val optional = RecordTypes.all.size - RecordTypes.core.size
        assertEquals(optional, RecordTypes.optionalByFamily.values.sumOf { it.size })
    }

    @Test
    fun `catalog is the essential twenty-nine types`() {
        assertEquals(29, RecordTypes.all.size)
        val names = RecordTypes.all.map { it.typeName }.toSet()
        for (essential in listOf(
            "STEPS_H1", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION",
            "ACTIVE_CALORIES_H1", "TOTAL_CALORIES_H1", "RESTING_HEART_RATE",
            "WEIGHT", "HEIGHT", "BODY_FAT", "BONE_MASS", "BODY_WATER_MASS", "LEAN_BODY_MASS",
            "DISTANCE_H1", "VO2_MAX", "OXYGEN_SATURATION", "BASAL_METABOLIC_RATE",
            "HEART_RATE_VARIABILITY_RMSSD", "RESPIRATORY_RATE", "SKIN_TEMPERATURE",
            "BODY_TEMPERATURE", "BASAL_BODY_TEMPERATURE", "SPEED", "ELEVATION_GAINED",
            "STEPS_CADENCE", "CYCLING_PEDALING_CADENCE", "POWER", "FLOORS_CLIMBED",
            "HYDRATION",
        )) assertTrue("falta $essential", names.contains(essential))
    }

    @Test
    @OptIn(androidx.health.connect.client.feature.ExperimentalMindfulnessSessionApi::class)
    fun `mindfulness write permission resolves via SDK`() {
        val perm = androidx.health.connect.client.permission.HealthPermission.getWritePermission(
            androidx.health.connect.client.records.MindfulnessSessionRecord::class,
        )
        assertTrue(perm.contains("MINDFULNESS"))
    }

    @Test
    fun `mindfulness stays out of the read catalog (write-only)`() {
        assertTrue(RecordTypes.byTypeName("MINDFULNESS_SESSION") == null)
        assertTrue(RecordTypes.all.none { it.recordClass.simpleName?.contains("Mindfulness") == true })
    }

    @Test
    fun `catalog excludes sensitive and duplicate types`() {
        val names = RecordTypes.all.map { it.typeName }.toSet()
        for (excluded in listOf(
            "BLOOD_PRESSURE", "BLOOD_GLUCOSE", "CERVICAL_MUCUS", "MENSTRUATION_FLOW",
            "MENSTRUATION_PERIOD", "INTERMENSTRUAL_BLEEDING", "OVULATION_TEST", "SEXUAL_ACTIVITY",
            "NUTRITION", "WHEELCHAIR_PUSHES",
            // Crudos duplicados de clases *_H1 (byClass los etiquetaría mal).
            "STEPS", "DISTANCE", "ACTIVE_CALORIES_BURNED", "TOTAL_CALORIES_BURNED",
        )) assertFalse("no debe existir $excluded", names.contains(excluded))
        assertTrue(
            "ningún tipo sensible en el catálogo",
            RecordTypes.all.none { it.sensitivity == Sensitivity.SENSITIVE },
        )
    }

    @Test
    fun `type lookup is case-sensitive and stable`() {
        assertEquals("STEPS_H1", RecordTypes.byTypeName("STEPS_H1")?.typeName)
        assertEquals(null, RecordTypes.byTypeName("steps_h1"))
        assertEquals(null, RecordTypes.byTypeName("STEPS"))
    }

    @Test
    fun `hourly sums replace the raw interval types`() {
        val hourly = RecordTypes.all.filter { it.hourlySum }
        assertEquals(
            setOf("STEPS_H1", "ACTIVE_CALORIES_H1", "TOTAL_CALORIES_H1", "DISTANCE_H1"),
            hourly.map { it.typeName }.toSet(),
        )
        assertTrue(hourly.all { it.historyDays < 30 })
    }
}
