package com.jhomc.healthsync.data

/**
 * Per-type changes token persisted in Room (health_sync_state) so that token
 * advancement is transactional with the page that consumed it. DataStore is
 * not atomic with Room, hence the DAO-backed store.
 */
class ChangesTokenStore(private val dao: HealthDao) {

    suspend fun get(recordType: String): String? =
        dao.getState(recordType)?.changesToken

    suspend fun save(recordType: String, token: String, nowMs: Long) {
        dao.upsertState(
            HealthSyncStateEntity(
                recordType = recordType,
                changesToken = token,
                permissionGranted = true,
                lastSuccessfulReadAtEpochMs = nowMs,
            ),
        )
    }

    suspend fun markPermissionLost(recordType: String) {
        val current = dao.getState(recordType)
        dao.upsertState(
            HealthSyncStateEntity(
                recordType = recordType,
                changesToken = current?.changesToken,
                permissionGranted = false,
                lastSuccessfulReadAtEpochMs = current?.lastSuccessfulReadAtEpochMs,
            ),
        )
    }
}
