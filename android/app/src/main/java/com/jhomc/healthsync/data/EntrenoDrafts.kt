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
import org.json.JSONArray
import org.json.JSONObject

/**
 * Borrador local del día (modo solo-registro). Es la libreta del bolsillo:
 * sobrevive a la muerte del proceso, a la falta de red y a los reinicios.
 * Cada mutación (steppers, diálogo, ✓, completar) escribe aquí en el acto.
 *
 * - payload_json: filas con uuid, ejercicio, kg, reps, rir, descanso_seg,
 *   velocidad_kmh y dificultad, en orden (los uuid alinean por índice).
 * - done_json: uuids marcados como hechos.
 * - base_hash: hash canónico de lo último visto del servidor al nacer el
 *   borrador. Al drenar con borrador local se compara contra un GET fresco:
 *   servidor más nuevo → reemplazo silencioso; local más nuevo → drena.
 * - updated_at_epoch_ms: último toque local (reloj del móvil).
 */
@Entity(tableName = "entreno_drafts")
data class EntrenoDraftEntity(
    @PrimaryKey val fecha: String, // ISO YYYY-MM-DD
    @ColumnInfo(name = "payload_json") val payloadJson: String,
    @ColumnInfo(name = "done_json") val doneJson: String,
    @ColumnInfo(name = "base_hash") val baseHash: String,
    @ColumnInfo(name = "updated_at_epoch_ms") val updatedAtEpochMs: Long,
)

@Dao
interface EntrenoDraftDao {
    @Query("SELECT * FROM entreno_drafts WHERE fecha = :fecha")
    suspend fun forFecha(fecha: String): EntrenoDraftEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(entry: EntrenoDraftEntity)

    @Query("DELETE FROM entreno_drafts WHERE fecha = :fecha")
    suspend fun clear(fecha: String)
}

/** Fila del borrador con su uuid local (nunca viaja al servidor). */
data class DraftRow(
    val uuid: String,
    val ejercicio: String,
    val kg: String,
    val reps: String,
    val rir: String,
    val descansoSeg: String,
    val velocidadKmh: String,
    val dificultad: String,
)

fun payloadJson(rows: List<DraftRow>): String =
    JSONArray().apply {
        for (r in rows) {
            put(
                JSONObject().put("uuid", r.uuid).put("ejercicio", r.ejercicio)
                    .put("kg", r.kg).put("reps", r.reps).put("rir", r.rir)
                    .put("descanso_seg", r.descansoSeg)
                    .put("velocidad_kmh", r.velocidadKmh)
                    .put("dificultad", r.dificultad),
            )
        }
    }.toString()

fun parsePayload(json: String): List<DraftRow> =
    runCatching {
        val arr = JSONArray(json)
        List(arr.length()) { i ->
            val o = arr.getJSONObject(i)
            DraftRow(
                uuid = o.optString("uuid"),
                ejercicio = o.optString("ejercicio"),
                kg = o.optString("kg"),
                reps = o.optString("reps"),
                rir = o.optString("rir"),
                descansoSeg = o.optString("descanso_seg"),
                velocidadKmh = o.optString("velocidad_kmh"),
                dificultad = o.optString("dificultad"),
            )
        }.filter { it.uuid.isNotBlank() }
    }.getOrDefault(emptyList())

fun doneJson(done: Set<String>): String =
    JSONArray().apply { for (u in done) put(u) }.toString()

fun parseDone(json: String): Set<String> =
    runCatching {
        val arr = JSONArray(json)
        (0 until arr.length()).mapTo(mutableSetOf()) { arr.getString(it) }
    }.getOrDefault(emptySet())

/** Hash canónico de filas (orden + campos de valor, sin uuid). */
fun canonicalRowsHash(rows: List<DraftRow>): String {
    var h = 1125899906842597L
    rows.forEachIndexed { i, r ->
        val s = listOf(r.ejercicio, r.kg, r.reps, r.rir, r.descansoSeg, r.velocidadKmh, r.dificultad)
            .joinToString("|")
        for (c in "$i:$s;") h = 31 * h + c.code
    }
    return h.toString(36)
}

/** v8: borradores locales del editor solo-registro. */
val MIGRATION_7_8 = object : Migration(7, 8) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS entreno_drafts (" +
                "fecha TEXT NOT NULL PRIMARY KEY, payload_json TEXT NOT NULL, " +
                "done_json TEXT NOT NULL, base_hash TEXT NOT NULL, " +
                "updated_at_epoch_ms INTEGER NOT NULL)",
        )
    }
}
