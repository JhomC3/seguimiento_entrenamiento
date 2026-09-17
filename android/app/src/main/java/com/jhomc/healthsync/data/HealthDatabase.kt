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
     * Reparo: re-encola los registros activos de los tipos dados que no tienen
     * operación pendiente (p. ej. crudo cuarentenado por un pre-vuelo demasiado
     * estricto). Idempotente por PK: nunca duplica.
     */
    @Query(
        "INSERT OR IGNORE INTO health_outbox " +
            "(target_id, hc_id, operation, revision, attempt_count, created_at_epoch_ms) " +
            "SELECT :targetId, hc_id, 'UPSERT', last_modified_epoch_ms, 0, :nowMs " +
            "FROM health_records WHERE record_type IN (:types) " +
            "AND deleted_at_epoch_ms IS NULL " +
            "AND hc_id NOT IN (SELECT hc_id FROM health_outbox WHERE target_id = :targetId)",
    )
    suspend fun requeueByTypes(targetId: Long, types: List<String>, nowMs: Long)

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
        TrainingCacheEntity::class,
        TrainingCacheMetaEntity::class,
        NutritionCacheEntity::class,
        PendingWriteEntity::class,
        RestIntervalEntity::class,
        EntrenoDraftEntity::class,
        WorkIntervalEntity::class,
        NutritionPublishEntity::class,
    ],
    version = 12,
    exportSchema = false,
)
abstract class HealthDatabase : RoomDatabase() {
    abstract fun healthDao(): HealthDao
    abstract fun nutritionPublishDao(): NutritionPublishDao
    abstract fun trainingCacheDao(): TrainingCacheDao
    abstract fun offlineDao(): OfflineDao
    abstract fun restDao(): RestDao
    abstract fun entrenoDraftDao(): EntrenoDraftDao
    abstract fun workDao(): WorkDao
}

/** Tipos crudos retirados del catálogo. El SERVIDOR los sigue aceptando como
 *  histórico (allow-list), aunque el dispositivo ya no los produce: el pre-vuelo
 *  de subida debe aceptarlos para drenar el pendiente, no cuarentenarlos. */
internal val RETIRED_RAW_TYPES = listOf(
    "STEPS",
    "ACTIVE_CALORIES_BURNED",
    "TOTAL_CALORIES_BURNED",
    "DISTANCE",
)

/** Tipos esenciales del catálogo (RecordTypes.kt) + el agregado interno de HR. */
internal val ESSENTIAL_RECORD_TYPES = listOf(
    "STEPS_H1",  // total horario (corte hacia adelante; el crudo STEPS es histórico)
    "HEART_RATE",
    "HEART_RATE_5MIN",  // agregado por tramos de 5 min (fuera del catálogo HC)
    "SLEEP_SESSION",
    "EXERCISE_SESSION",
    "ACTIVE_CALORIES_H1",  // total horario (el crudo es histórico)
    "TOTAL_CALORIES_H1",  // total horario (el crudo es histórico)
    "RESTING_HEART_RATE",
    "WEIGHT",
    "HEIGHT",
    "BODY_FAT",
    "BONE_MASS",
    "BODY_WATER_MASS",
    "LEAN_BODY_MASS",
    "DISTANCE_H1",  // total horario (el crudo DISTANCE es histórico)
    "VO2_MAX",
    "OXYGEN_SATURATION",
    "BASAL_METABOLIC_RATE",
)

/** v10: retira los 4 tipos crudos en favor de los agregados horarios *_H1
 *  (corte hacia adelante): estado, espejo y outbox pendiente. Lo ya entregado
 *  al servidor no se toca (histórico crudo; el servidor prefiere el agregado
 *  por día cuando existe). */
val MIGRATION_9_10 = object : Migration(9, 10) {
    private val retired = RETIRED_RAW_TYPES

    override fun migrate(db: SupportSQLiteDatabase) {
        val placeholders = retired.joinToString(",") { "?" }
        // Fuera del outbox primero: el hc_id es la única clave de unión.
        db.execSQL(
            "DELETE FROM health_outbox WHERE hc_id IN (" +
                "SELECT hc_id FROM health_records WHERE record_type IN ($placeholders))",
            retired.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_records WHERE record_type IN ($placeholders)",
            retired.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_sync_state WHERE record_type IN ($placeholders)",
            retired.toTypedArray(),
        )
    }
}

/**
 * v11: converge los linajes divergentes con versión 10 (dos ramas llegaron a
 * v10 con distinto esquema: la de nutrición añade `nutrition_publish`) y
 * normaliza artefactos históricos de DDL (defaults de `training_cache`,
 * índice de `work_intervals`). Sin esto, Room rechaza la apertura ("cannot
 * verify data integrity" si coincide versión, "didn't properly handle" si
 * migra). Solo DDL: ningún dato de salud se toca.
 */
val MIGRATION_10_11 = object : Migration(10, 11) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // Resto de la rama de nutrición (unmerged): su dato vive en el
        // servidor/diario, la tabla local es caché reconstruible.
        db.execSQL("DROP TABLE IF EXISTS nutrition_publish")
        // training_cache con el DDL exacto de las entidades (DEFAULT NULL en
        // las columnas HIIT): conserva todas las filas.
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS training_cache_new (" +
                "rowId INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "fecha TEXT NOT NULL, set_orden INTEGER NOT NULL, " +
                "ejercicio TEXT NOT NULL, kg REAL, reps REAL, rir REAL, " +
                "descanso_seg REAL, rm REAL, velocidad_kmh REAL DEFAULT NULL, " +
                "dificultad REAL DEFAULT NULL)",
        )
        db.execSQL(
            "INSERT OR IGNORE INTO training_cache_new " +
                "(rowId, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm, velocidad_kmh, dificultad) " +
                "SELECT rowId, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm, velocidad_kmh, dificultad " +
                "FROM training_cache",
        )
        db.execSQL("DROP TABLE IF EXISTS training_cache")
        db.execSQL("ALTER TABLE training_cache_new RENAME TO training_cache")
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_training_cache_fecha ON training_cache (fecha)",
        )
        // Índice con el nombre exacto que declaran las entidades.
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_work_intervals_fecha_start " +
                "ON work_intervals (fecha, start_wall_ms)",
        )
    }
}

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
 *
 * Snapshot congelado a propósito: las migraciones nunca referencian la lista
 * viva ESSENTIAL_RECORD_TYPES (el catálogo evoluciona; el historial no).
 */
val MIGRATION_2_3 = object : Migration(2, 3) {
    private val v2Essential = listOf(
        "STEPS",
        "HEART_RATE",
        "HEART_RATE_5MIN",
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

    override fun migrate(db: SupportSQLiteDatabase) {
        val placeholders = v2Essential.joinToString(",") { "?" }
        // Fuera del outbox primero: el hc_id es la única clave de unión.
        db.execSQL(
            "DELETE FROM health_outbox WHERE hc_id IN (" +
                "SELECT hc_id FROM health_records WHERE record_type NOT IN ($placeholders))",
            v2Essential.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_records WHERE record_type NOT IN ($placeholders)",
            v2Essential.toTypedArray(),
        )
        db.execSQL(
            "DELETE FROM health_sync_state WHERE record_type NOT IN ($placeholders)",
            v2Essential.toTypedArray(),
        )
    }
}
