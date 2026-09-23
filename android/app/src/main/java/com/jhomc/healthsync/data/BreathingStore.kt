package com.jhomc.healthsync.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * B5.0-revisión: historial de sesiones del pacer + cola de entrega al
 * servidor. Los presets se retiraron (migración 13→14): la pantalla no los
 * usa; el patrón vive en cada sesión guardada.
 *
 * - `breathing_sessions`: historial local (métricas del servidor cuando se
 *   entregó; ciclos/BPM estimados por el motor si aún no).
 * - `breathing_pending`: una op por sesión (PK `client_session_id`, lo último
 *   gana como `health_outbox`): SAVE con el payload o DELETE.
 */
@Entity(tableName = "breathing_sessions", indices = [Index("fecha")])
data class BreathingSessionEntity(
    @PrimaryKey @ColumnInfo(name = "client_session_id") val clientSessionId: String,
    val fecha: String,
    @ColumnInfo(name = "start_epoch_ms") val startMs: Long,
    @ColumnInfo(name = "end_epoch_ms") val endMs: Long,
    @ColumnInfo(name = "tz_offset_min") val tzOffsetMin: Int,
    @ColumnInfo(name = "planned_s") val plannedS: Int?,
    @ColumnInfo(name = "real_s") val realS: Int,
    @ColumnInfo(name = "pattern_json") val patternJson: String,
    val ciclos: Int,
    val bpm: Double,
    val completada: Boolean,
    val delivered: Boolean = false,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtMs: Long,
)

@Entity(tableName = "breathing_pending", primaryKeys = ["client_session_id"])
data class BreathingPendingEntity(
    @ColumnInfo(name = "client_session_id") val clientSessionId: String,
    val op: String, // SAVE | DELETE
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtMs: Long,
)

@Dao
interface BreathingDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putSession(session: BreathingSessionEntity)

    @Query("SELECT * FROM breathing_sessions WHERE fecha = :fecha ORDER BY start_epoch_ms")
    suspend fun sessionsFor(fecha: String): List<BreathingSessionEntity>

    @Query("SELECT * FROM breathing_sessions WHERE client_session_id = :id")
    suspend fun sessionById(id: String): BreathingSessionEntity?

    /** Guardadas sin op en cola (un rechazo del servidor las dejó huérfanas). */
    @Query(
        "SELECT * FROM breathing_sessions WHERE delivered = 0 AND client_session_id " +
            "NOT IN (SELECT client_session_id FROM breathing_pending) ORDER BY start_epoch_ms",
    )
    suspend fun orphans(): List<BreathingSessionEntity>

    @Query("UPDATE breathing_sessions SET delivered = 1, ciclos = :ciclos, bpm = :bpm WHERE client_session_id = :id")
    suspend fun markDelivered(id: String, ciclos: Int, bpm: Double)

    @Query("DELETE FROM breathing_sessions WHERE client_session_id = :id")
    suspend fun deleteSession(id: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun enqueue(op: BreathingPendingEntity)

    @Query("SELECT * FROM breathing_pending ORDER BY created_at_epoch_ms")
    suspend fun pendingAll(): List<BreathingPendingEntity>

    @Query("SELECT COUNT(*) FROM breathing_pending")
    suspend fun pendingCount(): Int

    @Query("DELETE FROM breathing_pending WHERE client_session_id = :id")
    suspend fun ack(id: String)
}

/** v13: tablas de respiración (sesiones + cola). Solo DDL. */
val MIGRATION_12_13 = object : Migration(12, 13) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS breathing_presets (" +
                "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, nombre TEXT NOT NULL, " +
                "pattern_json TEXT NOT NULL, duration_s INTEGER, " +
                "updated_at_epoch_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS breathing_sessions (" +
                "client_session_id TEXT NOT NULL PRIMARY KEY, fecha TEXT NOT NULL, " +
                "start_epoch_ms INTEGER NOT NULL, end_epoch_ms INTEGER NOT NULL, " +
                "tz_offset_min INTEGER NOT NULL, planned_s INTEGER, real_s INTEGER NOT NULL, " +
                "pattern_json TEXT NOT NULL, ciclos INTEGER NOT NULL, bpm REAL NOT NULL, " +
                "completada INTEGER NOT NULL, delivered INTEGER NOT NULL, " +
                "created_at_epoch_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS index_breathing_sessions_fecha " +
                "ON breathing_sessions (fecha)",
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS breathing_pending (" +
                "client_session_id TEXT NOT NULL PRIMARY KEY, op TEXT NOT NULL, " +
                "payload_json TEXT NOT NULL, created_at_epoch_ms INTEGER NOT NULL)",
        )
    }
}

/**
 * v14: retira los presets de respiración (la pantalla ya no los usa; el
 * patrón vive en cada sesión). Solo DDL: sesiones y cola no se tocan.
 */
val MIGRATION_13_14 = object : Migration(13, 14) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("DROP TABLE IF EXISTS breathing_presets")
    }
}
