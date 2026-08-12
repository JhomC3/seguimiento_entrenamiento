package com.jhomc.healthsync

import java.time.Instant
import java.time.ZoneId

/** Per-type read result of the one-shot inventory. */
data class TypeInventory(
    val typeName: String,
    val recordsToday: Int,
    val hasMore: Boolean,
    val aggregateTotal: Long? = null,
    val error: String? = null,
)

/**
 * One-shot diagnostic: what data does Health Connect have TODAY, per granted
 * type. Reads only the first page of the current day (bounded), so a dense
 * type reports hasMore=true instead of draining it. Errors are per-type and
 * never abort the rest of the inventory. Cumulative types (steps, calories)
 * also report the aggregate total for today — the read mode the official
 * docs recommend for them.
 */
class HealthInventory(
    private val gateway: HealthConnectGateway,
    private val now: () -> Instant = Instant::now,
    private val zoneId: ZoneId = ZoneId.systemDefault(),
) {

    suspend fun todayInventory(): List<TypeInventory> {
        val granted = gateway.grantedPermissions()
        val end = now()
        val start = end.atZone(zoneId).toLocalDate().atStartOfDay(zoneId).toInstant()
        return RecordTypes.all
            .filter { it.permission in granted }
            .map { entry -> inventoryType(entry, start, end) }
    }

    private suspend fun inventoryType(entry: RecordTypeEntry, start: Instant, end: Instant): TypeInventory {
        val aggregateTotal = if (entry.typeName in AGGREGATE_TYPES) {
            try {
                gateway.aggregateTotal(entry.recordClass, start, end)
            } catch (e: Exception) {
                return TypeInventory(entry.typeName, 0, false, error = errorOf(e))
            }
        } else {
            null
        }
        return try {
            val page = gateway.readRecords(entry.recordClass, start, end, null)
            TypeInventory(
                typeName = entry.typeName,
                recordsToday = page.records.size,
                hasMore = page.pageToken != null,
                aggregateTotal = aggregateTotal,
            )
        } catch (e: Exception) {
            TypeInventory(
                typeName = entry.typeName,
                recordsToday = 0,
                hasMore = false,
                aggregateTotal = aggregateTotal,
                error = errorOf(e),
            )
        }
    }

    private fun errorOf(e: Exception): String = "${e.javaClass.simpleName}: ${e.message ?: "sin detalle"}"

    companion object {
        /** Cumulative types: the aggregate total is the recommended read. */
        val AGGREGATE_TYPES = setOf("STEPS", "ACTIVE_CALORIES_BURNED", "TOTAL_CALORIES_BURNED")
    }
}
