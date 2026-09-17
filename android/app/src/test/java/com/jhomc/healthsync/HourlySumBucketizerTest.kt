package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class HourlySumBucketizerTest {

    private val h = HourlySumBucketizer.HOUR_MS

    @Test
    fun `empty input yields no buckets`() {
        assertTrue(HourlySumBucketizer.bucketize(emptyList()).isEmpty())
    }

    @Test
    fun `intervals in the same hour are summed`() {
        val buckets = HourlySumBucketizer.bucketize(
            listOf((2 * h + 100) to 100.0, (2 * h + 2000) to 50.0),
        )
        assertEquals(1, buckets.size)
        assertEquals(2 * h, buckets[0].startEpochMs)
        assertEquals(3 * h, buckets[0].endEpochMs)
        assertEquals(150.0, buckets[0].total, 0.0)
    }

    @Test
    fun `hour boundary splits buckets and output is sorted`() {
        val buckets = HourlySumBucketizer.bucketize(
            listOf((5 * h + 10) to 1.0, (3 * h + h - 1) to 2.0, (3 * h) to 4.0),
        )
        assertEquals(listOf(3 * h, 5 * h), buckets.map { it.startEpochMs })
        assertEquals(6.0, buckets[0].total, 0.0)
        assertEquals(1.0, buckets[1].total, 0.0)
    }

    @Test
    fun `hc ids are stable per hour and entities carry the spec`() {
        assertEquals("STEPS_H1:7200000", HourlySumBucketizer.hcId("STEPS_H1", 2 * h))
        val entity = HourlySumBucketizer.toEntity(
            "STEPS_H1", HourBucket(2 * h, 3 * h, 7000.0), nowMs = 9L,
        )
        assertEquals("STEPS_H1:7200000", entity.hcId)
        assertEquals("STEPS_H1", entity.recordType)
        assertEquals(2 * h, entity.startEpochMs)
        assertEquals(3 * h, entity.endEpochMs)
        assertEquals(2 * h, entity.lastModifiedEpochMs)
        assertEquals("""{"count":7000}""", entity.valueJson)
        val kcal = HourlySumBucketizer.toEntity(
            "ACTIVE_CALORIES_H1", HourBucket(h, 2 * h, 12.5), nowMs = 9L,
        )
        assertEquals("CALA_H1:3600000", kcal.hcId)
        assertEquals("""{"energy_kcal":12.5}""", kcal.valueJson)
    }

    @Test
    fun `unknown hourly type is rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            HourlySumBucketizer.toEntity("STEPS", HourBucket(h, 2 * h, 1.0), nowMs = 9L)
        }
    }
}
