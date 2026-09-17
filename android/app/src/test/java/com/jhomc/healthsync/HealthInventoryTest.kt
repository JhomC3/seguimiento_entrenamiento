package com.jhomc.healthsync

import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthInventoryTest {

    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    private fun inventory(gateway: FakeHealthConnectGateway) = HealthInventory(
        gateway = gateway,
        now = { t },
        zoneId = ZoneOffset.UTC,
    )

    @Test
    fun `counts today's first page and flags more data`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply {
            granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
            pageStore[null] = listOf(
                Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)),
                Fixtures.sleepSession("hc-2", t, t.plusSeconds(3600)),
            )
            pageStore["pt-1"] = listOf(Fixtures.sleepSession("hc-3", t, t.plusSeconds(3600)))
        }
        val row = inventory(gateway).todayInventory().single()
        assertEquals("SLEEP_SESSION", row.typeName)
        assertEquals(2, row.recordsToday)
        assertTrue("debe marcar hasMore si existe página 2", row.hasMore)
        assertNull(row.aggregateTotal)
        assertNull(row.error)
    }

    @Test
    fun `aggregate totals only for cumulative types`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply {
            granted = setOf(
                RecordTypes.byTypeName("STEPS_H1")!!.permission,
                RecordTypes.byTypeName("HEART_RATE")!!.permission,
            )
            aggregateTotals["STEPS_H1"] = 9018L
        }
        val rows = inventory(gateway).todayInventory().associateBy { it.typeName }
        assertEquals(9018L, rows["STEPS_H1"]!!.aggregateTotal)
        assertNull("HEART_RATE no es acumulativo: sin total", rows["HEART_RATE"]!!.aggregateTotal)
        assertEquals(listOf("STEPS_H1"), gateway.aggregateTotalLog)
    }

    @Test
    fun `a failing type does not break the rest`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply {
            granted = setOf(
                RecordTypes.byTypeName("STEPS_H1")!!.permission,
                RecordTypes.byTypeName("SLEEP_SESSION")!!.permission,
            )
            failReadsWithForegroundRequired = true // golpea la 1ª lectura (STEPS_H1)
        }
        val rows = inventory(gateway).todayInventory().associateBy { it.typeName }
        assertTrue("STEPS_H1 debe reportar error: ${rows["STEPS_H1"]!!.error}", rows["STEPS_H1"]!!.error != null)
        assertEquals(0, rows["STEPS_H1"]!!.recordsToday)
        assertNull("SLEEP_SESSION sigue intacto", rows["SLEEP_SESSION"]!!.error)
    }

    @Test
    fun `empty day reports zero records without error`() = runBlocking {
        val gateway = FakeHealthConnectGateway().apply {
            granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
        }
        val row = inventory(gateway).todayInventory().single()
        assertEquals(0, row.recordsToday)
        assertFalse(row.hasMore)
        assertNull(row.error)
    }
}
