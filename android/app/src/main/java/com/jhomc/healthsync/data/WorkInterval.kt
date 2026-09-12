package com.jhomc.healthsync.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Tramos de trabajo por serie: del tap Ir al tap de Guardar. Espejo de
 * rest_intervals con el mismo reloj dual (wall para el futuro join con
 * Health Connect, elapsed para duraciones inmunes a saltos de hora).
 * Local y oculto, como los descansos. Sin backend en esta fase.
 */
@Entity(tableName = "work_intervals")
data class WorkIntervalEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val fecha: String, // ISO YYYY-MM-DD
    val ejercicio: String, // snapshot del nombre al abrir
    @ColumnInfo(name = "client_set_uuid") val clientSetUuid: String,
    @ColumnInfo(name = "set_orden_aparente") val setOrdenAparente: Int = 0,
    @ColumnInfo(name = "start_wall_ms") val startWallMs: Long,
    @ColumnInfo(name = "start_elapsed_ms") val startElapsedMs: Long,
    @ColumnInfo(name = "end_wall_ms") val endWallMs: Long? = null,
    @ColumnInfo(name = "end_elapsed_ms") val endElapsedMs: Long? = null,
    /** ABIERTO | CERRADO | ABANDONADO (huérfano de sesión anterior). */
    val estado: String = "ABIERTO",
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtEpochMs: Long,
)

@Dao
interface WorkDao {
    @Insert
    suspend fun insert(interval: WorkIntervalEntity): Long

    @Query("SELECT * FROM work_intervals WHERE estado = 'ABIERTO' ORDER BY start_wall_ms")
    suspend fun openAll(): List<WorkIntervalEntity>

    @Query(
        "UPDATE work_intervals SET end_wall_ms = :endWall, end_elapsed_ms = :endElapsed, " +
            "estado = 'CERRADO' WHERE id = :id AND estado = 'ABIERTO'",
    )
    suspend fun close(id: Long, endWall: Long, endElapsed: Long)

    @Query(
        "UPDATE work_intervals SET end_wall_ms = :endWall, end_elapsed_ms = :endElapsed, " +
            "estado = 'ABANDONADO' WHERE estado = 'ABIERTO'",
    )
    suspend fun abandonAllOpen(endWall: Long, endElapsed: Long)
}

/** v9: tramos de trabajo locales (sin backend en esta fase). */
val MIGRATION_8_9 = object : Migration(8, 9) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS work_intervals (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "fecha TEXT NOT NULL, ejercicio TEXT NOT NULL, " +
                "client_set_uuid TEXT NOT NULL, set_orden_aparente INTEGER NOT NULL DEFAULT 0, " +
                "start_wall_ms INTEGER NOT NULL, start_elapsed_ms INTEGER NOT NULL, " +
                "end_wall_ms INTEGER, end_elapsed_ms INTEGER, " +
                "estado TEXT NOT NULL DEFAULT 'ABIERTO', " +
                "created_at_epoch_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_work_intervals_fecha_start " +
                "ON work_intervals (fecha, start_wall_ms)",
        )
    }
}
