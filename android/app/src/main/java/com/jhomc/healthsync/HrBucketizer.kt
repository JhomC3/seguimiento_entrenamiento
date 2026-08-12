package com.jhomc.healthsync

import androidx.health.connect.client.records.HeartRateRecord
import com.jhomc.healthsync.data.HealthRecordEntity
import java.time.Instant

/** Un tramo de 5 minutos: media/mín/máx de las muestras que caen dentro. */
data class HrBucket(
    val startEpochMs: Long,
    val endEpochMs: Long,
    val avgBpm: Long,
    val minBpm: Long,
    val maxBpm: Long,
)

/**
 * Agrupa muestras crudas de ritmo cardiaco en tramos de [slicerMinutes]
 * minutos (5 por defecto). Pura y determinista (por epoch, sin zona horaria):
 * el proveedor del SDK fijado no expone métricas de agregación para
 * HeartRateRecord (verificado en el AAR 1.1.0), así que el agrupado se hace
 * localmente antes de subir. Solo se emiten tramos CON al menos una muestra.
 */
object HrBucketizer {

    const val RECORD_TYPE = "HEART_RATE_5MIN"
    const val SLICER_MINUTES = 5

    fun bucketize(
        samples: List<HeartRateRecord.Sample>,
        slicerMinutes: Int = SLICER_MINUTES,
    ): List<HrBucket> {
        if (samples.isEmpty()) return emptyList()
        val slicerMs = slicerMinutes * 60_000L
        val buckets = LinkedHashMap<Long, MutableList<Long>>()
        for (sample in samples) {
            val start = sample.time.toEpochMilli() / slicerMs * slicerMs
            buckets.getOrPut(start) { mutableListOf() }.add(sample.beatsPerMinute)
        }
        return buckets.map { (start, values) ->
            HrBucket(
                startEpochMs = start,
                endEpochMs = start + slicerMs,
                avgBpm = values.average().toLong(),
                minBpm = values.min(),
                maxBpm = values.max(),
            )
        }.sortedBy { it.startEpochMs }
    }

    /** hc_id estable por tramo: idempotente entre syncs. */
    fun hcId(startEpochMs: Long): String = "HR5M:$startEpochMs"

    fun toEntity(bucket: HrBucket, nowMs: Long): HealthRecordEntity =
        HealthRecordEntity(
            hcId = hcId(bucket.startEpochMs),
            recordType = RECORD_TYPE,
            startEpochMs = bucket.startEpochMs,
            endEpochMs = bucket.endEpochMs,
            lastModifiedEpochMs = bucket.startEpochMs,
            dataOriginPackage = null,
            timeZoneOffsetMinutes = null,
            payloadSchemaVersion = 1,
            valueJson = """{"avg":${bucket.avgBpm},"min":${bucket.minBpm},"max":${bucket.maxBpm}}""",
            sourceUpdatedAtEpochMs = nowMs,
        )
}
