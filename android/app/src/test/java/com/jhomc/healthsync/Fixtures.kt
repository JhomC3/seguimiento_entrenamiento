package com.jhomc.healthsync

import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Mass
import androidx.health.connect.client.units.Percentage
import java.lang.reflect.Constructor
import java.time.Instant
import java.time.ZoneOffset

object Fixtures {

    val ZONE: ZoneOffset = ZoneOffset.ofHours(-5)

    /**
     * The 1.1.0 SDK keeps the Metadata constructor internal and its factories
     * stamp lastModifiedTime = now, which is useless for deterministic tests.
     * Reflection is used HERE ONLY (test fixtures) to control id/origin/time.
     */
    private val metadataCtor: Constructor<*> by lazy {
        Metadata::class.java.getDeclaredConstructor(
            Int::class.javaPrimitiveType,
            String::class.java,
            DataOrigin::class.java,
            Instant::class.java,
            String::class.java,
            Long::class.javaPrimitiveType,
            Device::class.java,
        ).apply { isAccessible = true }
    }

    fun metadata(
        id: String,
        lastModified: Instant,
        origin: String = "com.samsung.health",
    ): Metadata = metadataCtor.newInstance(
        Metadata.RECORDING_METHOD_AUTOMATICALLY_RECORDED,
        id,
        DataOrigin(origin),
        lastModified,
        "",
        0L,
        null,
    ) as Metadata

    fun steps(
        id: String,
        start: Instant,
        end: Instant,
        count: Long,
        lastModified: Instant = end,
        origin: String = "com.samsung.health",
    ): StepsRecord = StepsRecord(
        start, ZONE, end, ZONE, count,
        metadata(id, lastModified, origin),
    )

    fun heartRate(
        id: String,
        start: Instant,
        end: Instant,
        bpm: Long = 72,
        lastModified: Instant = end,
    ): HeartRateRecord = HeartRateRecord(
        start, ZONE, end, ZONE,
        listOf(HeartRateRecord.Sample(Instant.ofEpochMilli(start.toEpochMilli() + 1000), bpm)),
        metadata(id, lastModified),
    )

    fun weight(
        id: String,
        time: Instant,
        kg: Double,
        lastModified: Instant = time,
    ): WeightRecord = WeightRecord(
        time, ZONE, Mass.kilograms(kg), metadata(id, lastModified),
    )

    fun bodyFat(
        id: String,
        time: Instant,
        percent: Double,
    ): BodyFatRecord = BodyFatRecord(
        time, ZONE, Percentage(percent), metadata(id, time),
    )

    fun sleepSession(
        id: String,
        start: Instant,
        end: Instant,
    ): SleepSessionRecord = SleepSessionRecord(
        start, ZONE, end, ZONE,
        metadata(id, end),
        "Noche", "nota",
        listOf(
            SleepSessionRecord.Stage(start, end, 3),
        ),
    )
}
