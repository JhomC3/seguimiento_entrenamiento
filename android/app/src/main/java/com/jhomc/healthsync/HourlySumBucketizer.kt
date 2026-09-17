package com.jhomc.healthsync

import com.jhomc.healthsync.data.HealthRecordEntity

/** Un tramo de 1 hora: suma de los intervalos que empiezan dentro. */
data class HourBucket(
    val startEpochMs: Long,
    val endEpochMs: Long,
    val total: Double,
)

/** Especificación de un agregado horario: prefijo de hc_id + clave del valor. */
data class HourlySumSpec(val prefix: String, val valueKey: String)

/**
 * Agrupa intervalos crudos (pasos, calorías, distancia) en totales por hora.
 * Puro y determinista (por epoch, sin zona horaria): cada intervalo imputa su
 * valor ÍNTEGRO a la hora de su inicio (sin prorrateo). Solo se emiten horas
 * CON al menos un intervalo. Espejo del precedente HrBucketizer (5 min).
 *
 * Corte hacia adelante: los tipos crudos dejan de sincronizarse y estos
 * agregados arrancan desde la migración (sin reenviar 30 días). El servidor
 * conserva el histórico crudo y prefiere el agregado por día cuando existe.
 */
object HourlySumBucketizer {

    const val HOUR_MS = 3_600_000L

    /** Tipos agregados por hora: el hc_id lleva prefijo propio (PK global). */
    val SPECS: Map<String, HourlySumSpec> = mapOf(
        "STEPS_H1" to HourlySumSpec("STEPS_H1", "count"),
        "ACTIVE_CALORIES_H1" to HourlySumSpec("CALA_H1", "energy_kcal"),
        "TOTAL_CALORIES_H1" to HourlySumSpec("CALT_H1", "energy_kcal"),
        "DISTANCE_H1" to HourlySumSpec("DIST_H1", "meters"),
    )

    fun bucketize(
        startsToValues: List<Pair<Long, Double>>,
        hourMs: Long = HOUR_MS,
    ): List<HourBucket> {
        if (startsToValues.isEmpty()) return emptyList()
        val buckets = LinkedHashMap<Long, Double>()
        for ((start, value) in startsToValues) {
            val hour = start / hourMs * hourMs
            buckets[hour] = (buckets[hour] ?: 0.0) + value
        }
        return buckets.map { (hour, total) ->
            HourBucket(startEpochMs = hour, endEpochMs = hour + hourMs, total = total)
        }.sortedBy { it.startEpochMs }
    }

    /** hc_id estable por tramo: idempotente entre syncs (re-agregar = overwrite). */
    fun hcId(prefix: String, startEpochMs: Long): String = "$prefix:$startEpochMs"

    fun toEntity(recordType: String, bucket: HourBucket, nowMs: Long): HealthRecordEntity {
        val spec = SPECS[recordType]
            ?: throw IllegalArgumentException("Sin spec horaria: $recordType")
        return HealthRecordEntity(
            hcId = hcId(spec.prefix, bucket.startEpochMs),
            recordType = recordType,
            startEpochMs = bucket.startEpochMs,
            endEpochMs = bucket.endEpochMs,
            lastModifiedEpochMs = bucket.startEpochMs,
            dataOriginPackage = null, // una hora puede mezclar proveedores
            timeZoneOffsetMinutes = null,
            payloadSchemaVersion = 1,
            valueJson = """{"${spec.valueKey}":${formatTotal(bucket.total)}}""",
            sourceUpdatedAtEpochMs = nowMs,
        )
    }

    private fun formatTotal(total: Double): String =
        if (!total.isInfinite() && total == kotlin.math.floor(total)) {
            total.toLong().toString()
        } else {
            total.toString()
        }
}
