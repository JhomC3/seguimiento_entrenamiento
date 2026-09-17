package com.jhomc.healthsync

import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthSyncPlannerTest {

    private val utc: ZoneId = ZoneOffset.UTC
    private fun at(iso: String): Long = Instant.parse(iso).toEpochMilli()

    @Test
    fun `morning window covers sleep resting hr and body composition`() {
        for (name in listOf("SLEEP_SESSION", "RESTING_HEART_RATE", "WEIGHT", "HEIGHT", "BODY_FAT", "BONE_MASS", "BODY_WATER_MASS", "LEAN_BODY_MASS")) {
            assertEquals(setOf(9), HealthSyncPlanner.windowHours(name))
        }
    }

    @Test
    fun `exercise and calories sync at noon and evening`() {
        for (name in listOf("EXERCISE_SESSION", "ACTIVE_CALORIES_H1", "TOTAL_CALORIES_H1")) {
            assertEquals(setOf(13, 19), HealthSyncPlanner.windowHours(name))
        }
    }

    @Test
    fun `steps and heart rate sync in the evening window`() {
        assertEquals(setOf(19), HealthSyncPlanner.windowHours("STEPS_H1"))
        assertEquals(setOf(19), HealthSyncPlanner.windowHours("DISTANCE_H1"))
        assertEquals(setOf(19), HealthSyncPlanner.windowHours("HEART_RATE"))
    }

    @Test
    fun `next due is the next window occurrence`() {
        // 10:00 → la ventana de las 13:00 (entrenos).
        assertEquals(
            at("2026-08-08T13:00:00Z"),
            HealthSyncPlanner.nextDueMs("EXERCISE_SESSION", at("2026-08-08T10:00:00Z"), utc),
        )
        // 14:00 → la de las 19:00.
        assertEquals(
            at("2026-08-08T19:00:00Z"),
            HealthSyncPlanner.nextDueMs("EXERCISE_SESSION", at("2026-08-08T14:00:00Z"), utc),
        )
        // 20:00 → mañana a las 9:00 (sueño).
        assertEquals(
            at("2026-08-09T09:00:00Z"),
            HealthSyncPlanner.nextDueMs("SLEEP_SESSION", at("2026-08-08T20:00:00Z"), utc),
        )
        // 8:00 → hoy a las 9:00.
        assertEquals(
            at("2026-08-08T09:00:00Z"),
            HealthSyncPlanner.nextDueMs("SLEEP_SESSION", at("2026-08-08T08:00:00Z"), utc),
        )
        // 19:00 en punto → no cuenta la hora actual: mañana a las 19:00.
        assertEquals(
            at("2026-08-09T19:00:00Z"),
            HealthSyncPlanner.nextDueMs("STEPS_H1", at("2026-08-08T19:00:00Z"), utc),
        )
    }
}
