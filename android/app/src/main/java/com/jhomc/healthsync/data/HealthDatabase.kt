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
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

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
    @ColumnInfo(name = "next_due_at_epoch_ms") val nextDueAtEpochMs: Long? = null,
    @ColumnInfo(name = "cooldown_until_epoch_ms") val cooldownUntilEpochMs: Long? = null,
    @ColumnInfo(name = "priority") val priority: Int = 1,
    @ColumnInfo(name = "bootstrap_page_token") val bootstrapPageToken: String? = null,
    @ColumnInfo(name = "bootstrap_start_epoch_ms") val bootstrapStartEpochMs: Long? = null,
    @ColumnInfo(name = "empty_runs") val emptyRuns: Int = 0,
)

@Entity(tableName = "sync_meta")
data class SyncMetaEntity(
    @PrimaryKey @ColumnInfo(name = "meta_key") val key: String,
    @ColumnInfo(name = "meta_value") val value: String,
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

    @Query("SELECT * FROM sync_meta WHERE meta_key = :key")
    suspend fun getMeta(key: String): SyncMetaEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putMeta(meta: SyncMetaEntity)

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
        SyncMetaEntity::class,
    ],
    version = 3,
    exportSchema = false,
)
abstract class HealthDatabase : RoomDatabase() {
    abstract fun healthDao(): HealthDao
}

/** Tipos esenciales del catálogo (RecordTypes.kt) + el agregado interno de HR. */
internal val ESSENTIAL_RECORD_TYPES = listOf(
    "STEPS",
    "HEART_RATE",
    "HEART_RATE_5MIN",  // agregado por tramos de 5 min (fuera del catálogo HC)
    "SLEEP_SESSION",
    "EXERCISE_SESSION",
    "ACTIVE_CALORIES_BURNED",
    "TOTAL_CALORIES_BURNED",
    "RESTING_HEART_RATE",
    "WEIGHT",
    "HEIGHT",
    "BODY_FAT",
    "BONE_MASS",
    "BODY_WATER_MASS",
    "LEAN_BODY_MASS",
    "DISTANCE",
    "VO2_MAX",
    "OXYGEN_SATURATION",
    "BASAL_METABOLIC_RATE",
)

val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN next_due_at_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN cooldown_until_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN priority INTEGER NOT NULL DEFAULT 1")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN bootstrap_page_token TEXT")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN bootstrap_start_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN empty_runs INTEGER NOT NULL DEFAULT 0")
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS sync_meta (" +
                "meta_key TEXT NOT NULL PRIMARY KEY, meta_value TEXT NOT NULL)"
        )
    }
}

/**
 * v3: purga los tipos recortados del catálogo (22 tipos no esenciales) de las
 * tablas locales: estado de sync, registros espejo y operaciones pendientes del
 * outbox. Los datos ya entregados al servidor no se tocan.
 */
val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        val placeholders = ESSENTIAL_RECORD_TYPES.joinToString(",") { "?" }
        // Fuera del outbox primero: el hc_id es la única clave de unión.
        db.execSQL(
            "DELETE FROM health_outbox WHERE hc_id IN (" +
                "SELECT hc_id FROM health_records WHERE record_type NOT IN ($placeholders))",
            ESSENTIAL_RECORD_TYPES.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_records WHERE record_type NOT IN ($placeholders)",
            ESSENTIAL_RECORD_TYPES.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_sync_state WHERE record_type NOT IN ($placeholders)",
            ESSENTIAL_RECORD_TYPES.toTypedArray(),
        )
    }
}
