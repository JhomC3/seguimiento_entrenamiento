package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthSyncPlannerTest {

    @Test
    fun `high frequency types start at high priority`() {
        for (name in listOf("STEPS", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION", "TOTAL_CALORIES_BURNED")) {
            assertEquals(HealthSyncPlanner.PRIORITY_HIGH, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName(name)!!))
        }
    }

    @Test
    fun `composition and medical families start cold`() {
        for (name in listOf("WEIGHT", "BODY_FAT", "HEIGHT", "BLOOD_GLUCOSE", "BLOOD_PRESSURE")) {
            assertEquals(HealthSyncPlanner.PRIORITY_LOW, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName(name)!!))
        }
    }

    @Test
    fun `remaining types start medium`() {
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("DISTANCE")!!))
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("HYDRATION")!!))
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("NUTRITION")!!))
    }

    @Test
    fun `due intervals respect priority and stay below token expiry`() {
        for (p in listOf(0, 1, 2)) {
            val ms = HealthSyncPlanner.dueIntervalMs(p)
            assertTrue(ms in 1..(30L * 24 * 3_600_000))
        }
        assertEquals(6L * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_HIGH))
        assertEquals(24L * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_MEDIUM))
        assertEquals(7L * 24 * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_LOW))
    }

    @Test
    fun `activity promotes one level and resets empty runs`() {
        val (p, e) = HealthSyncPlanner.adjustAfterRun(1, 2, hadChanges = true)
        assertEquals(2, p)
        assertEquals(0, e)
        val (p2, _) = HealthSyncPlanner.adjustAfterRun(2, 0, hadChanges = true)
        assertEquals(2, p2) // nunca pasa de HIGH
    }

    @Test
    fun `three empty runs demote one level`() {
        assertEquals(1 to 0, HealthSyncPlanner.adjustAfterRun(2, 2, hadChanges = false))
        assertEquals(0 to 0, HealthSyncPlanner.adjustAfterRun(1, 2, hadChanges = false))
        assertEquals(1 to 1, HealthSyncPlanner.adjustAfterRun(1, 0, hadChanges = false))
        assertEquals(0 to 0, HealthSyncPlanner.adjustAfterRun(0, 2, hadChanges = false)) // nunca baja de LOW
    }
}
