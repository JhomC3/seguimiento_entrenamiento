package com.jhomc.healthsync

import androidx.health.connect.client.records.HeartRateRecord
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HrBucketizerTest {

    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    private fun sample(secondsOffset: Long, bpm: Long) =
        HeartRateRecord.Sample(t.plusSeconds(secondsOffset), bpm)

    @Test
    fun `empty samples produce no buckets`() {
        assertTrue(HrBucketizer.bucketize(emptyList()).isEmpty())
    }

    @Test
    fun `samples are grouped in 5 minute buckets with avg min max`() {
        // Tres muestras en el mismo tramo de 5 min + una en el siguiente.
        val buckets = HrBucketizer.bucketize(
            listOf(
                sample(0, 70),
                sample(60, 80),
                sample(120, 90),
                sample(360, 50), // 6 min: tramo siguiente
            ),
        )
        assertEquals(2, buckets.size)

        val first = buckets[0]
        assertEquals(t.toEpochMilli(), first.startEpochMs)
        assertEquals(t.toEpochMilli() + 5 * 60_000, first.endEpochMs)
        assertEquals(80L, first.avgBpm)
        assertEquals(70L, first.minBpm)
        assertEquals(90L, first.maxBpm)

        val second = buckets[1]
        assertEquals(t.toEpochMilli() + 5 * 60_000, second.startEpochMs)
        assertEquals(50L, second.avgBpm)
    }

    @Test
    fun `hc id is stable per bucket start`() {
        assertEquals("HR5M:${t.toEpochMilli()}", HrBucketizer.hcId(t.toEpochMilli()))
    }

    @Test
    fun `entity carries the bucket as value json with stable revision`() {
        val bucket = HrBucket(t.toEpochMilli(), t.toEpochMilli() + 300_000, 72, 60, 95)
        val entity = HrBucketizer.toEntity(bucket, nowMs = 123L)
        assertEquals(HrBucketizer.RECORD_TYPE, entity.recordType)
        assertEquals(bucket.startEpochMs, entity.lastModifiedEpochMs)
        assertEquals("""{"avg":72,"min":60,"max":95}""", entity.valueJson)
        assertEquals(t.toEpochMilli(), entity.startEpochMs)
    }
}
