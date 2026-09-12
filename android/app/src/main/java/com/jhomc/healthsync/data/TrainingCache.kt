package com.jhomc.healthsync.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Caché de lectura del diario (API v1). Network-first con fallback a caché:
 * la última sesión vista por fecha sigue disponible sin red. La escritura es
 * solo online en v1 (sin outbox: el guardado sin LAN devuelve error visible;
 * la cola offline queda para v2 según training-api-contract.md §5).
 */
@Entity(tableName = "training_cache", indices = [androidx.room.Index("fecha")])
data class TrainingCacheEntity(
    @PrimaryKey(autoGenerate = true) val rowId: Long = 0,
    val fecha: String, // ISO YYYY-MM-DD
    @ColumnInfo(name = "set_orden") val setOrden: Int,
    val ejercicio: String,
    val kg: Double?,
    val reps: Double?,
    val rir: Double?,
    @ColumnInfo(name = "descanso_seg") val descansoSeg: Double?,
    val rm: Double?,
    @ColumnInfo(name = "velocidad_kmh", defaultValue = "NULL") val velocidadKmh: Double? = null,
    @ColumnInfo(name = "dificultad", defaultValue = "NULL") val dificultad: Double? = null,
)

@Entity(tableName = "training_cache_meta")
data class TrainingCacheMetaEntity(
    @PrimaryKey val fecha: String,
    val semana: Int,
    val dia: String,
    @ColumnInfo(name = "has_data") val hasData: Boolean,
    @ColumnInfo(name = "updated_at_epoch_ms") val updatedAtEpochMs: Long,
)

@Dao
interface TrainingCacheDao {

    @Query("SELECT * FROM training_cache WHERE fecha = :fecha ORDER BY set_orden")
    suspend fun rowsFor(fecha: String): List<TrainingCacheEntity>

    @Query("SELECT * FROM training_cache_meta WHERE fecha = :fecha")
    suspend fun metaFor(fecha: String): TrainingCacheMetaEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertMeta(meta: TrainingCacheMetaEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertRows(rows: List<TrainingCacheEntity>)

    @Query("DELETE FROM training_cache WHERE fecha = :fecha")
    suspend fun clearRows(fecha: String)

    /** Reemplazo total del día (misma semántica que POST /api/v1/sesion). */
    @Transaction
    suspend fun replaceDay(meta: TrainingCacheMetaEntity, rows: List<TrainingCacheEntity>) {
        clearRows(meta.fecha)
        upsertMeta(meta)
        if (rows.isNotEmpty()) upsertRows(rows)
    }

    @Transaction
    suspend fun clearDay(fecha: String, nowMs: Long) {
        clearRows(fecha)
        upsertMeta(TrainingCacheMetaEntity(fecha, 0, "", false, nowMs))
    }
}

/** v4: caché de lectura del diario (tablas training_cache + training_cache_meta). */
val MIGRATION_3_4 = object : Migration(3, 4) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS training_cache (" +
                "rowId INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "fecha TEXT NOT NULL, set_orden INTEGER NOT NULL, " +
                "ejercicio TEXT NOT NULL, kg REAL, reps REAL, rir REAL, " +
                "descanso_seg REAL, rm REAL)",
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS index_training_cache_fecha ON training_cache (fecha)")
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS training_cache_meta (" +
                "fecha TEXT NOT NULL PRIMARY KEY, semana INTEGER NOT NULL, " +
                "dia TEXT NOT NULL, has_data INTEGER NOT NULL, " +
                "updated_at_epoch_ms INTEGER NOT NULL)",
        )
    }
}

/** v6: columnas HIIT en la caché (velocidad_kmh, dificultad, anulables). */
val MIGRATION_5_6 = object : Migration(5, 6) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE training_cache ADD COLUMN velocidad_kmh REAL")
        db.execSQL("ALTER TABLE training_cache ADD COLUMN dificultad REAL")
    }
}
