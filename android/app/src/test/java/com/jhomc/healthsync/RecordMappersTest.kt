package com.jhomc.healthsync

import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.metadata.DataOrigin
import com.jhomc.healthsync.data.RecordMappers
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordMappersTest {

    private val t0: Instant = Instant.parse("2026-08-08T12:00:00Z")
    private val t1: Instant = Instant.parse("2026-08-08T13:00:00Z")

    @Test
    fun `interval family maps count and base fields`() {
        val record = Fixtures.steps("hc-steps-1", t0, t1, count = 8123, lastModified = t1)
        val json = JSONObject(RecordMappers.toPayloadJson(record))
        assertEquals("hc-steps-1", json.getString("hc_id"))
        assertEquals("STEPS", json.getString("record_type"))
        assertEquals(t1.toEpochMilli(), json.getLong("revision"))
        assertEquals(t0.toEpochMilli(), json.getLong("start_epoch_ms"))
        assertEquals(t1.toEpochMilli(), json.getLong("end_epoch_ms"))
        assertEquals("com.samsung.health", json.getString("data_origin_package"))
        assertEquals(-300, json.getInt("time_zone_offset_minutes"))
        assertEquals(1, json.getInt("payload_schema_version"))
        assertEquals(8123L, json.getJSONObject("value").getLong("count"))
    }

    @Test
    fun `series family maps samples deterministically`() {
        val record = Fixtures.heartRate("hc-hr-1", t0, t1, bpm = 72)
        val json = JSONObject(RecordMappers.toPayloadJson(record))
        val samples = json.getJSONObject("value").getJSONArray("samples")
        assertEquals(1, samples.length())
        assertEquals(72L, samples.getJSONObject(0).getLong("bpm"))
        assertEquals(t0.toEpochMilli() + 1000, samples.getJSONObject(0).getLong("time"))
    }

    @Test
    fun `instant family maps value and time`() {
        val record = Fixtures.weight("hc-w-1", t0, kg = 69.5)
        val json = JSONObject(RecordMappers.toPayloadJson(record))
        assertEquals(t0.toEpochMilli(), json.getLong("start_epoch_ms"))
        assertTrue(!json.has("end_epoch_ms"))
        assertEquals(69.5, json.getJSONObject("value").getDouble("kg"), 0.001)
    }

    @Test
    fun `composition family maps percentage`() {
        val record = Fixtures.bodyFat("hc-bf-1", t0, percent = 20.5)
        val json = JSONObject(RecordMappers.toPayloadJson(record))
        assertEquals(20.5, json.getJSONObject("value").getDouble("percentage"), 0.001)
    }

    @Test
    fun `session family maps stages`() {
        val record = Fixtures.sleepSession("hc-sleep-1", t0, t1)
        val json = JSONObject(RecordMappers.toPayloadJson(record))
        assertEquals("Noche", json.getJSONObject("value").getString("title"))
        val stages = json.getJSONObject("value").getJSONArray("stages")
        assertEquals(1, stages.length())
        assertEquals(3, stages.getJSONObject(0).getInt("stage"))
    }

    @Test
    fun `type outside catalog is rejected, never partially serialized`() {
        val alien = object : Record {
            override val metadata = Fixtures.metadata("alien", Instant.now())
        }
        assertThrows(IllegalArgumentException::class.java) {
            RecordMappers.toPayloadJson(alien)
        }
    }
}
