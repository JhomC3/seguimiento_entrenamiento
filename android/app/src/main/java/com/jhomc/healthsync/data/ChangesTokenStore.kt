package com.jhomc.healthsync.data

import com.jhomc.healthsync.HealthSyncPlanner

/**
 * Per-type changes token persisted in Room (health_sync_state) so that token
 * advancement is transactional with the page that consumed it. DataStore is
 * not atomic with Room, hence the DAO-backed store.
 */
class ChangesTokenStore(private val dao: HealthDao) {

    suspend fun get(recordType: String): String? =
        dao.getState(recordType)?.changesToken

    suspend fun save(recordType: String, token: String, nowMs: Long) {
        val current = dao.getState(recordType)
        dao.upsertState(
            current?.copy(
                changesToken = token,
                permissionGranted = true,
                lastSuccessfulReadAtEpochMs = nowMs,
            )
                ?: HealthSyncStateEntity(
                    recordType = recordType,
                    changesToken = token,
                    permissionGranted = true,
                    lastSuccessfulReadAtEpochMs = nowMs,
                ),
        )
    }

    suspend fun markSynced(recordType: String, hadChanges: Boolean, nowMs: Long) {
        val current = dao.getState(recordType)
        val basePriority = current?.priority ?: HealthSyncPlanner.PRIORITY_MEDIUM
        val (newPriority, newEmptyRuns) = HealthSyncPlanner.adjustAfterRun(basePriority, current?.emptyRuns ?: 0, hadChanges)
        dao.upsertState(
            current?.copy(
                permissionGranted = true,
                lastSuccessfulReadAtEpochMs = nowMs,
                nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(newPriority, nowMs),
                cooldownUntilEpochMs = null,
                priority = newPriority,
                bootstrapPageToken = null,
                bootstrapStartEpochMs = null,
                emptyRuns = newEmptyRuns,
            )
                ?: HealthSyncStateEntity(
                    recordType = recordType,
                    changesToken = null,
                    permissionGranted = true,
                    lastSuccessfulReadAtEpochMs = nowMs,
                    nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(newPriority, nowMs),
                    priority = newPriority,
                ),
        )
    }

    suspend fun markCooldown(recordType: String, nowMs: Long) {
        val current = dao.getState(recordType)
        dao.upsertState(
            current?.copy(cooldownUntilEpochMs = nowMs + HealthSyncPlanner.COOLDOWN_AFTER_RATE_LIMIT_MS)
                ?: HealthSyncStateEntity(recordType, cooldownUntilEpochMs = nowMs + HealthSyncPlanner.COOLDOWN_AFTER_RATE_LIMIT_MS),
        )
    }

    suspend fun markPermissionLost(recordType: String) {
        val current = dao.getState(recordType)
        dao.upsertState(current?.copy(permissionGranted = false) ?: HealthSyncStateEntity(recordType))
    }
}
