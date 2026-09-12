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
 * Fase 1 modo entreno: intervalos de descanso locales y ocultos.
 *
 * Semántica honesta para el futuro cruce con FC: Iniciar abre un intervalo,
 * Pausar lo cierra. Reanudar abre otro. Una serie puede tener N intervalos;
 * el análisis futuro los une por tiempo, nunca por ordinal.
 *
 * Reloj dual (crítico para FC):
 * - wall_ms (System.currentTimeMillis): mismo reloj UTC-epoch que
 *   health_records.start/end_epoch_ms → sirve para el JOIN temporal.
 * - elapsed_ms (SystemClock.elapsedRealtime): monótono, inmune a saltos
 *   NTP/cambios manuales de hora → sirve para la DURACIÓN real.
 * Duración = end_elapsed - start_elapsed. Join = wall_ms.
 *
 * Clave de unión: el tiempo + client_set_uuid (generado en el móvil por fila
 * de borrador, nunca enviado al servidor). set_orden_aparente es solo
 * informativo: el servidor reasigna set_orden 1..N en cada guardado y el
 * cliente nunca lo envía (training-api-contract.md §2).
 */
@Entity(
    tableName = "rest_intervals",
    indices = [androidx.room.Index(value = ["fecha", "start_wall_ms"])],
)
data class RestIntervalEntity(
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
interface RestDao {
    @Insert
    suspend fun insert(interval: RestIntervalEntity): Long

    @Query("SELECT * FROM rest_intervals WHERE id = :id")
    suspend fun get(id: Long): RestIntervalEntity?

    @Query("SELECT * FROM rest_intervals WHERE estado = 'ABIERTO' ORDER BY start_wall_ms")
    suspend fun openAll(): List<RestIntervalEntity>

    @Query("SELECT * FROM rest_intervals WHERE fecha = :fecha ORDER BY start_wall_ms")
    suspend fun forFecha(fecha: String): List<RestIntervalEntity>

    @Query(
        "UPDATE rest_intervals SET end_wall_ms = :endWall, end_elapsed_ms = :endElapsed, " +
            "estado = 'CERRADO' WHERE id = :id AND estado = 'ABIERTO'",
    )
    suspend fun close(id: Long, endWall: Long, endElapsed: Long)

    /**
     * Barrido de huérfanos al arrancar: todo ABIERTO anterior se marca
     * ABANDONADO con el último tick conocido. Nunca se reanuda solo;
     * solo se reanuda el de la sesión activa en memoria.
     */
    @Query(
        "UPDATE rest_intervals SET end_wall_ms = :endWall, end_elapsed_ms = :endElapsed, " +
            "estado = 'ABANDONADO' WHERE estado = 'ABIERTO'",
    )
    suspend fun abandonAllOpen(endWall: Long, endElapsed: Long)

    @Query("SELECT * FROM rest_intervals WHERE client_set_uuid = :uuid ORDER BY start_wall_ms")
    suspend fun forSet(uuid: String): List<RestIntervalEntity>
}

/** v7: tabla local de intervalos de descanso (sin backend en Fase 1). */
val MIGRATION_6_7 = object : Migration(6, 7) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS rest_intervals (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "fecha TEXT NOT NULL, ejercicio TEXT NOT NULL, " +
                "client_set_uuid TEXT NOT NULL, set_orden_aparente INTEGER NOT NULL DEFAULT 0, " +
                "start_wall_ms INTEGER NOT NULL, start_elapsed_ms INTEGER NOT NULL, " +
                "end_wall_ms INTEGER, end_elapsed_ms INTEGER, " +
                "estado TEXT NOT NULL DEFAULT 'ABIERTO', " +
                "created_at_epoch_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_rest_intervals_fecha_start " +
                "ON rest_intervals (fecha, start_wall_ms)",
        )
    }
}
