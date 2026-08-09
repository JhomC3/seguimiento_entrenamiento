package com.jhomc.healthsync.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Transaction

/**
 * Local source of continuity: origin state (health_records + health_sync_state)
 * is separated from delivery (sync_targets + health_outbox). The outbox holds
 * one pending operation per (target, hc_id); the latest revision replaces the
 * previous one (INSERT OR REPLACE), so no two operations accumulate.
 */

@Entity(tableName = "health_records")
data class HealthRecordEntity(
    @PrimaryKey @ColumnInfo(name = "hc_id") val hcId: String,
    @ColumnInfo(name = "record_type") val recordType: String,
    @ColumnInfo(name = "start_epoch_ms") val startEpochMs: Long,
    @ColumnInfo(name = "end_epoch_ms") val endEpochMs: Long?,
    @ColumnInfo(name = "last_modified_epoch_ms") val lastModifiedEpochMs: Long,
    @ColumnInfo(name = "data_origin_package") val dataOriginPackage: String?,
    @ColumnInfo(name = "time_zone_offset_minutes") val timeZoneOffsetMinutes: Int?,
    @ColumnInfo(name = "payload_schema_version") val payloadSchemaVersion: Int,
    @ColumnInfo(name = "value_json") val valueJson: String,
    @ColumnInfo(name = "deleted_at_epoch_ms") val deletedAtEpochMs: Long? = null,
    @ColumnInfo(name = "source_updated_at_epoch_ms") val sourceUpdatedAtEpochMs: Long,
)

@Entity(tableName = "health_sync_state")
data class HealthSyncStateEntity(
    @PrimaryKey @ColumnInfo(name = "record_type") val recordType: String,
    @ColumnInfo(name = "changes_token") val changesToken: String? = null,
    @ColumnInfo(name = "permission_granted") val permissionGranted: Boolean = false,
    @ColumnInfo(name = "last_successful_read_at_epoch_ms") val lastSuccessfulReadAtEpochMs: Long? = null,
)

@Entity(tableName = "sync_targets")
data class SyncTargetEntity(
    @PrimaryKey(autoGenerate = true) @ColumnInfo(name = "target_id") val targetId: Long = 0,
    val url: String,
    val name: String,
    val active: Boolean,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtEpochMs: Long,
)

@Entity(tableName = "health_outbox", primaryKeys = ["target_id", "hc_id"])
data class HealthOutboxEntity(
    @ColumnInfo(name = "target_id") val targetId: Long,
    @ColumnInfo(name = "hc_id") val hcId: String,
    val operation: String, // UPSERT | DELETE
    val revision: Long,
    @ColumnInfo(name = "attempt_count") val attemptCount: Int = 0,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtEpochMs: Long,
)

@Dao
interface HealthDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertRecord(record: HealthRecordEntity)

    @Query("SELECT * FROM health_records WHERE hc_id = :hcId")
    suspend fun getRecord(hcId: String): HealthRecordEntity?

    @Query("UPDATE health_records SET deleted_at_epoch_ms = :now WHERE hc_id = :hcId")
    suspend fun markDeleted(hcId: String, now: Long)

    @Query("SELECT * FROM health_records WHERE deleted_at_epoch_ms IS NULL ORDER BY start_epoch_ms")
    suspend fun allActiveRecords(): List<HealthRecordEntity>

    @Query("SELECT * FROM health_records WHERE deleted_at_epoch_ms IS NULL AND hc_id = :hcId")
    suspend fun activeRecord(hcId: String): HealthRecordEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertState(state: HealthSyncStateEntity)

    @Query("SELECT * FROM health_sync_state WHERE record_type = :recordType")
    suspend fun getState(recordType: String): HealthSyncStateEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertTarget(target: SyncTargetEntity): Long

    @Query("SELECT * FROM sync_targets WHERE active = 1 ORDER BY target_id")
    suspend fun activeTargets(): List<SyncTargetEntity>

    @Query("SELECT * FROM sync_targets WHERE target_id = :targetId")
    suspend fun getTarget(targetId: Long): SyncTargetEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertOutbox(op: HealthOutboxEntity)

    @Query("SELECT * FROM health_outbox WHERE target_id = :targetId ORDER BY created_at_epoch_ms LIMIT :limit")
    suspend fun pendingOps(targetId: Long, limit: Int): List<HealthOutboxEntity>

    @Query("DELETE FROM health_outbox WHERE target_id = :targetId AND hc_id = :hcId AND revision = :revision")
    suspend fun ackOp(targetId: Long, hcId: String, revision: Long)

    @Query("DELETE FROM health_outbox WHERE target_id = :targetId AND hc_id = :hcId")
    suspend fun dropOp(targetId: Long, hcId: String)

    @Query("UPDATE health_outbox SET attempt_count = attempt_count + 1 WHERE target_id = :targetId AND hc_id = :hcId")
    suspend fun bumpAttempt(targetId: Long, hcId: String)

    /**
     * Transactionally persists a change (upsert or logical delete) and
     * enqueues the matching outbox operation for every active target.
     * INSERT OR REPLACE on (target_id, hc_id) guarantees at most one pending
     * operation per record per target: a newer revision replaces the older.
     */
    @Transaction
    suspend fun applyChangeAndEnqueue(
        record: HealthRecordEntity?,
        deletedHcId: String?,
        nowMs: Long,
    ) {
        if (record != null) {
            upsertRecord(record)
            for (target in activeTargets()) {
                upsertOutbox(
                    HealthOutboxEntity(
                        targetId = target.targetId,
                        hcId = record.hcId,
                        operation = "UPSERT",
                        revision = record.lastModifiedEpochMs,
                        createdAtEpochMs = nowMs,
                    ),
                )
            }
        }
        if (deletedHcId != null) {
            markDeleted(deletedHcId, nowMs)
            for (target in activeTargets()) {
                upsertOutbox(
                    HealthOutboxEntity(
                        targetId = target.targetId,
                        hcId = deletedHcId,
                        operation = "DELETE",
                        revision = nowMs,
                        createdAtEpochMs = nowMs,
                    ),
                )
            }
        }
    }

    /** Seeds a brand-new target with an UPSERT per active record (replay). */
    @Transaction
    suspend fun seedTarget(targetId: Long, nowMs: Long) {
        for (record in allActiveRecords()) {
            upsertOutbox(
                HealthOutboxEntity(
                    targetId = targetId,
                    hcId = record.hcId,
                    operation = "UPSERT",
                    revision = record.lastModifiedEpochMs,
                    createdAtEpochMs = nowMs,
                ),
            )
        }
    }

    /** Persists one backfill page + outbox entries for every active target. */
    @Transaction
    suspend fun applyBackfillPage(records: List<HealthRecordEntity>, nowMs: Long) {
        records.forEach { upsertRecord(it) }
        val targets = activeTargets()
        for (record in records) {
            for (target in targets) {
                upsertOutbox(
                    HealthOutboxEntity(
                        targetId = target.targetId,
                        hcId = record.hcId,
                        operation = "UPSERT",
                        revision = record.lastModifiedEpochMs,
                        createdAtEpochMs = nowMs,
                    ),
                )
            }
        }
    }
}

@Database(
    entities = [
        HealthRecordEntity::class,
        HealthSyncStateEntity::class,
        SyncTargetEntity::class,
        HealthOutboxEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class HealthDatabase : RoomDatabase() {
    abstract fun healthDao(): HealthDao
}
