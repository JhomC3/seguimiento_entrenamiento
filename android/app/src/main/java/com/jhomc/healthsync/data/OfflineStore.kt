package com.jhomc.healthsync.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * B4: caché de nutrición + outbox unificada de escrituras.
 *
 * - La caché de nutrición guarda el ÚLTIMO payload JSON del servidor por
 *   fecha (los nutrientes los calcula siempre el servidor; cachear drafts
 *   locales mentiría en el resumen). Se parsea con los mismos parsers del
 *   cliente, así que nunca diverge del contrato.
 * - `pending_writes` es la cola offline (una op por dominio+fecha: el
 *   guardado es reemplazo total y lo último gana, igual que health_outbox
 *   por (target,hc_id)). El borrado también encola (DELETE idempotente).
 *   Dominios: sesion|diario. Ops: SAVE|DELETE.
 */
@Entity(tableName = "nutrition_cache")
data class NutritionCacheEntity(
    @PrimaryKey val fecha: String, // ISO YYYY-MM-DD
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "updated_at_epoch_ms") val updatedAtEpochMs: Long,
)

@Entity(tableName = "pending_writes", primaryKeys = ["domain", "fecha"])
data class PendingWriteEntity(
    val domain: String, // sesion|diario
    val fecha: String,
    val op: String, // SAVE|DELETE
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "created_at_epoch_ms") val createdAtEpochMs: Long,
)

@Dao
interface OfflineDao {

    @Query("SELECT * FROM nutrition_cache WHERE fecha = :fecha")
    suspend fun nutritionFor(fecha: String): NutritionCacheEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putNutrition(entry: NutritionCacheEntity)

    @Query("DELETE FROM nutrition_cache WHERE fecha = :fecha")
    suspend fun clearNutrition(fecha: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun enqueue(write: PendingWriteEntity)

    @Query("SELECT * FROM pending_writes ORDER BY created_at_epoch_ms")
    suspend fun pendingAll(): List<PendingWriteEntity>

    @Query("SELECT COUNT(*) FROM pending_writes")
    suspend fun pendingCount(): Int

    @Query("DELETE FROM pending_writes WHERE domain = :domain AND fecha = :fecha")
    suspend fun ack(domain: String, fecha: String)
}

/** v5: caché de nutrición (payload JSON) + cola offline de escrituras. */
val MIGRATION_4_5 = object : Migration(4, 5) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS nutrition_cache (" +
                "fecha TEXT NOT NULL PRIMARY KEY, payload_json TEXT NOT NULL, " +
                "updated_at_epoch_ms INTEGER NOT NULL)",
        )
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS pending_writes (" +
                "domain TEXT NOT NULL, fecha TEXT NOT NULL, op TEXT NOT NULL, " +
                "payload_json TEXT NOT NULL, created_at_epoch_ms INTEGER NOT NULL, " +
                "PRIMARY KEY (domain, fecha))",
        )
    }
}
