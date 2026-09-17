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
 * Estado de publicación nutricional en Health Connect (réplica eventual).
 *
 * - 1 fila por fecha ISO: el diario es reemplazo total y lo último gana.
 * - `day_hash`: hash del `NutritionDay` publicado (ver `NutritionPublishMapper.dayHash`).
 *   Si el servidor trae otro hash, hay que re-publicar (edición web o undo).
 * - `client_ids`: CSV de `clientRecordId`s publicados (para borrar huérfanos).
 * - `status`: OK | PENDING | ERROR | DISABLED (permiso revocado / toggle off).
 * - `detail`: mensaje corto no sensible (p. ej. "sin_permiso", "insert:3").
 */
@Entity(tableName = "nutrition_publish")
data class NutritionPublishEntity(
    @PrimaryKey val fecha: String,
    @ColumnInfo(name = "day_hash") val dayHash: String,
    @ColumnInfo(name = "client_ids") val clientIds: String,
    val status: String,
    val detail: String? = null,
    @ColumnInfo(name = "updated_at_epoch_ms") val updatedAtEpochMs: Long,
)

@Dao
interface NutritionPublishDao {
    @Query("SELECT * FROM nutrition_publish WHERE fecha = :fecha")
    suspend fun forFecha(fecha: String): NutritionPublishEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(state: NutritionPublishEntity)

    @Query("DELETE FROM nutrition_publish WHERE fecha = :fecha")
    suspend fun clear(fecha: String)
}

/**
 * v12: estado de publicación nutricional (1 fila por fecha). Vive en 11_12 y
 * no en 9_10 porque esa versión ya existe en dev con otro significado (retiro
 * del crudo de sync): dos ramas reclamaron la v10 y la convergencia v11 la
 * dejó sin esta tabla (DROP IF EXISTS). Quien venga de la rama de nutrición
 * la recupera vacía y el pase la reconstruye por hash desde el servidor.
 */
val MIGRATION_11_12 = object : Migration(11, 12) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS nutrition_publish (" +
                "fecha TEXT NOT NULL PRIMARY KEY, " +
                "day_hash TEXT NOT NULL, client_ids TEXT NOT NULL, " +
                "status TEXT NOT NULL, detail TEXT, " +
                "updated_at_epoch_ms INTEGER NOT NULL)",
        )
    }
}
