package com.jhomc.healthsync

import com.jhomc.healthsync.data.NutritionPublishDao
import com.jhomc.healthsync.data.NutritionPublishEntity
import java.time.ZoneId

/**
 * Réplica eventual diario -> Health Connect (solo automático, sin botón).
 *
 * - Fuente de verdad: `NutritionDay` confirmado por el servidor (nunca borrador).
 * - Idempotencia: `clientRecordId` estable + `clientRecordVersion` = hash;
 *   re-insert del mismo contenido es no-op en HC.
 * - Reconciliación por fecha: si el hash publicado == hash deseado, no se toca HC
 *   (cubre web-edits detectados en load + reintentos sin duplicar).
 * - Borrado: día eliminado o día sin filas mapeables -> borrar publicados previos
 *   por `clientRecordIds` (sin READ, sobre lo propio) + limpiar estado.
 * - Transaccionalidad HC: `insertRecords` falla el lote entero si un registro es
 *   inválido; el mapper ya omite campos fuera de rango, y aquí se inserta de
 *   uno en uno para aislar (días típicos <20 filas, coste aceptable).
 * - Nunca lanza: devuelve `Result` para pintar estado discreto en el diario.
 */
class NutritionPublisher(
    private val gateway: HealthConnectGateway,
    private val publishDao: NutritionPublishDao,
    private val manager: HealthConnectManager? = null,
    private val nowMs: () -> Long = { System.currentTimeMillis() },
    private val zoneId: ZoneId = ZoneId.systemDefault(),
    private val enabled: () -> Boolean = { true },
) {

    sealed class Outcome {
        data class Published(val inserted: Int, val deleted: Int) : Outcome()
        data class Skipped(val reason: String) : Outcome()
        data class Failed(val reason: String) : Outcome()
    }

    suspend fun publishDay(day: NutritionDay): Outcome {
        if (!enabled()) {
            return Outcome.Skipped("disabled")
        }
        val fecha = day.fecha
        val desired = NutritionPublishMapper.mapDay(day, zoneId)
        val desiredHash = NutritionPublishMapper.dayHash(day)
        val desiredIds = desired.map { it.clientRecordId }.toSet()

        val previous = runCatching { publishDao.forFecha(fecha) }.getOrNull()
        if (previous != null && previous.dayHash == desiredHash && previous.status == "OK") {
            return Outcome.Skipped("up_to_date")
        }
        val previousIds = previous?.clientIds
            ?.split(",")
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            ?.toSet() ?: emptySet()

        // Permiso de escritura: sin él no se toca HC ni se pierde estado.
        if (!hasWritePermission()) {
            runCatching {
                publishDao.put(
                    NutritionPublishEntity(fecha, desiredHash, previousIds.joinToString(","), "PENDING", "sin_permiso", nowMs()),
                )
            }
            return Outcome.Failed("sin_permiso")
        }

        // Día vacío (o sin filas mapeables): borrar lo previo y limpiar.
        if (desired.isEmpty()) {
            return deleteDay(fecha, previousIds)
        }

        // 1. Borrar huérfanos (filas que ya no están) de uno en uno para aislar.
        var deleted = 0
        for (orphan in previousIds - desiredIds) {
            val ok = runCatching { gateway.deleteNutritionByClientIds(listOf(orphan)) }.isSuccess
            if (ok) deleted++ else return fail(fecha, desiredHash, previousIds, "delete:$orphan")
        }

        // 2. Upsert deseados de uno en uno (aisla un registro inválido).
        var inserted = 0
        for (meal in desired) {
            val ok = runCatching { gateway.insertNutrition(listOf(meal.record)) }.isSuccess
            if (!ok) return fail(fecha, desiredHash, previousIds, "insert:${meal.clientRecordId}")
            inserted++
        }

        runCatching {
            publishDao.put(
                NutritionPublishEntity(
                    fecha, desiredHash, desiredIds.joinToString(","), "OK",
                    "insert:$inserted delete:$deleted", nowMs(),
                ),
            )
        }
        return Outcome.Published(inserted, deleted)
    }

    suspend fun deleteDay(fecha: String, knownIds: Set<String>? = null): Outcome {
        if (!enabled()) return Outcome.Skipped("disabled")
        val previous = runCatching { publishDao.forFecha(fecha) }.getOrNull()
        val ids = knownIds
            ?: previous?.clientIds?.split(",")?.map { it.trim() }?.filter { it.isNotEmpty() }?.toSet()
            ?: emptySet()
        if (ids.isEmpty()) {
            runCatching { publishDao.clear(fecha) }
            return Outcome.Published(0, 0)
        }
        if (!hasWritePermission()) {
            runCatching {
                publishDao.put(
                    NutritionPublishEntity(fecha, previous?.dayHash ?: "", ids.joinToString(","), "PENDING", "sin_permiso", nowMs()),
                )
            }
            return Outcome.Failed("sin_permiso")
        }
        for (id in ids) {
            val ok = runCatching { gateway.deleteNutritionByClientIds(listOf(id)) }.isSuccess
            if (!ok) {
                runCatching {
                    publishDao.put(
                        NutritionPublishEntity(fecha, previous?.dayHash ?: "", ids.joinToString(","), "ERROR", "delete:$id", nowMs()),
                    )
                }
                return Outcome.Failed("delete:$id")
            }
        }
        runCatching { publishDao.clear(fecha) }
        return Outcome.Published(0, ids.size)
    }

    private suspend fun fail(fecha: String, hash: String, ids: Set<String>, detail: String): Outcome {
        runCatching {
            publishDao.put(NutritionPublishEntity(fecha, hash, ids.joinToString(","), "ERROR", detail, nowMs()))
        }
        return Outcome.Failed(detail)
    }

    private suspend fun hasWritePermission(): Boolean {
        val mgr = manager ?: return true
        return runCatching {
            val granted = gateway.grantedPermissions()
            granted.contains(mgr.nutritionWritePermission())
        }.getOrDefault(false)
    }
}
