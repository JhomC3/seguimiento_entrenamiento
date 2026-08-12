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

    suspend fun markSynced(recordType: String, hadChanges: Boolean, nowMs: Long, zoneId: java.time.ZoneId) {
        val current = dao.getState(recordType)
        dao.upsertState(
            current?.copy(
                permissionGranted = true,
                lastSuccessfulReadAtEpochMs = nowMs,
                nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(recordType, nowMs, zoneId),
                cooldownUntilEpochMs = null,
            )
                ?: HealthSyncStateEntity(
                    recordType = recordType,
                    permissionGranted = true,
                    lastSuccessfulReadAtEpochMs = nowMs,
                    nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(recordType, nowMs, zoneId),
                ),
        )
    }

    suspend fun markCooldown(recordType: String, nowMs: Long) {
        val current = dao.getState(recordType)
        dao.upsertState(
            current?.copy(cooldownUntilEpochMs = nowMs + COOLDOWN_AFTER_RATE_LIMIT_MS)
                ?: HealthSyncStateEntity(recordType, cooldownUntilEpochMs = nowMs + COOLDOWN_AFTER_RATE_LIMIT_MS),
        )
    }

    suspend fun markPermissionLost(recordType: String) {
        val current = dao.getState(recordType)
        dao.upsertState(current?.copy(permissionGranted = false) ?: HealthSyncStateEntity(recordType))
    }

    companion object {
        /** Enfriamiento tras rate limit / lectura colgada; el tipo se salta hasta entonces. */
        const val COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000L
    }
}
