package com.jhomc.healthsync

/**
 * Pure scheduling math for the per-type sync agenda (§3.1). No I/O: every
 * function is deterministic so the planner is unit-testable without Room.
 * All intervals stay below the 30-day changes-token expiry.
 */
object HealthSyncPlanner {

    const val PRIORITY_HIGH = 2
    const val PRIORITY_MEDIUM = 1
    const val PRIORITY_LOW = 0

    const val EMPTY_RUNS_TO_DEMOTE = 3

    /** Cooldown after a rate-limit response; the type is skipped until then. */
    const val COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000L

    /** Core activity types Samsung Health actually writes: synced first. */
    val HIGH_FREQUENCY_TYPES = setOf(
        "STEPS", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION",
        "ACTIVE_CALORIES_BURNED", "TOTAL_CALORIES_BURNED", "RESTING_HEART_RATE",
    )

    fun initialPriority(entry: RecordTypeEntry): Int = when {
        entry.typeName in HIGH_FREQUENCY_TYPES -> PRIORITY_HIGH
        entry.family == MappingFamily.COMPOSITION ||
            entry.family == MappingFamily.MEDICAL ||
            entry.family == MappingFamily.ROUTE -> PRIORITY_LOW
        else -> PRIORITY_MEDIUM
    }

    fun dueIntervalMs(priority: Int): Long = when (priority) {
        PRIORITY_HIGH -> 6L * 3_600_000
        PRIORITY_LOW -> 7L * 24 * 3_600_000
        else -> 24L * 3_600_000
    }

    fun nextDueMs(priority: Int, nowMs: Long): Long = nowMs + dueIntervalMs(priority)

    /** Returns (newPriority, newEmptyRuns) after one completed run of a type. */
    fun adjustAfterRun(priority: Int, emptyRuns: Int, hadChanges: Boolean): Pair<Int, Int> =
        if (hadChanges) {
            (priority + 1).coerceAtMost(PRIORITY_HIGH) to 0
        } else if (emptyRuns + 1 >= EMPTY_RUNS_TO_DEMOTE) {
            (priority - 1).coerceAtLeast(PRIORITY_LOW) to 0
        } else {
            priority to (emptyRuns + 1)
        }
}
