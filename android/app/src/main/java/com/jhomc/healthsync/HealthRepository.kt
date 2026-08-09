package com.jhomc.healthsync

import androidx.health.connect.client.changes.DeletionChange
import androidx.health.connect.client.changes.UpsertionChange
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.response.ChangesResponse
import androidx.health.connect.client.response.ReadRecordsResponse
import androidx.room.withTransaction
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDao
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.HealthRecordEntity
import com.jhomc.healthsync.data.RecordMappers
import java.time.Instant
import java.time.temporal.ChronoUnit

data class TypeSyncResult(
    val recordType: String,
    val upserts: Int = 0,
    val deletes: Int = 0,
    val backfilled: Int = 0,
    val tokenAdvanced: Boolean = false,
)

/** Token expired signal, per the 1.1.0 SDK contract (changesTokenExpired + exception). */
class ChangesTokenExpiredException(message: String) : RuntimeException(message)

/**
 * Differential sync per record type. Delivery never blocks source progress:
 * once a page is persisted (record + outbox + next token) in ONE transaction,
 * the source cursor advances even if the HTTP target is down.
 */
class HealthRepository(
    private val db: HealthDatabase,
    private val gateway: HealthConnectGateway,
    private val tokenStore: ChangesTokenStore,
    private val now: () -> Instant = Instant::now,
) {

    private val dao: HealthDao = db.healthDao()

    /** Backfill window used for first sync and token-expiry recovery. */
    suspend fun syncType(entry: RecordTypeEntry): TypeSyncResult {
        val existing = tokenStore.get(entry.typeName)
        return if (existing == null) {
            firstSync(entry)
        } else {
            drainChanges(entry, existing)
        }
    }

    private suspend fun firstSync(entry: RecordTypeEntry): TypeSyncResult {
        // 1) Reserve the changes token BEFORE the backfill, so changes that
        //    arrive while backfilling are drained afterwards (no gap window).
        val reserved = gateway.getChangesToken(setOf(entry.recordClass))
        // 2) Backfill last 30 days, paginated, persisted per page.
        val backfilled = backfill(entry)
        // 3) Drain everything that happened since the reserved token.
        val drained = drainChanges(entry, reserved, tokenReserved = true)
        return TypeSyncResult(
            recordType = entry.typeName,
            backfilled = backfilled,
            upserts = drained.upserts,
            deletes = drained.deletes,
            tokenAdvanced = drained.tokenAdvanced,
        )
    }

    private suspend fun backfill(entry: RecordTypeEntry): Int {
        val end = now()
        val start = end.minus(30, ChronoUnit.DAYS)
        var pageToken: String? = null
        var total = 0
        do {
            val page: ReadRecordsResponse<Record> = gateway.readRecords(entry.recordClass, start, end, pageToken)
            val entities = page.records.map { toEntity(it) }
            db.withTransaction { dao.applyBackfillPage(entities, now().toEpochMilli()) }
            total += entities.size
            pageToken = page.pageToken
        } while (pageToken != null)
        return total
    }

    private suspend fun drainChanges(
        entry: RecordTypeEntry,
        token: String,
        tokenReserved: Boolean = false,
    ): TypeSyncResult {
        var current = token
        var upserts = 0
        var deletes = 0
        var advanced = false
        while (true) {
            val response: ChangesResponse = try {
                gateway.getChanges(current)
            } catch (e: ChangesTokenExpiredException) {
                recoverFromExpiry(entry)
                return TypeSyncResult(entry.typeName, tokenAdvanced = true)
            }
            if (response.changesTokenExpired) {
                recoverFromExpiry(entry)
                return TypeSyncResult(entry.typeName, tokenAdvanced = true)
            }
            db.withTransaction {
                for (change in response.changes) {
                    when (change) {
                        is UpsertionChange -> {
                            dao.applyChangeAndEnqueue(toEntity(change.record), null, now().toEpochMilli())
                            upserts++
                        }
                        is DeletionChange -> {
                            dao.applyChangeAndEnqueue(null, change.recordId, now().toEpochMilli())
                            deletes++
                        }
                    }
                }
                tokenStore.save(entry.typeName, response.nextChangesToken, now().toEpochMilli())
            }
            advanced = true
            current = response.nextChangesToken
            if (!response.hasMore) break
        }
        return TypeSyncResult(
            recordType = entry.typeName,
            upserts = upserts,
            deletes = deletes,
            tokenAdvanced = advanced,
        )
    }

    private suspend fun recoverFromExpiry(entry: RecordTypeEntry) {
        backfill(entry)
        val fresh = gateway.getChangesToken(setOf(entry.recordClass))
        db.withTransaction { tokenStore.save(entry.typeName, fresh, now().toEpochMilli()) }
    }

    private fun toEntity(record: Record): HealthRecordEntity {
        val entry = RecordTypes.byClass(record::class)
            ?: throw IllegalArgumentException("Tipo fuera del catálogo: ${record::class.simpleName}")
        val json = RecordMappers.toPayload(record)
        return HealthRecordEntity(
            hcId = json.getString("hc_id"),
            recordType = entry.typeName,
            startEpochMs = json.optLong("start_epoch_ms"),
            endEpochMs = if (json.has("end_epoch_ms")) json.getLong("end_epoch_ms") else null,
            lastModifiedEpochMs = record.metadata.lastModifiedTime.toEpochMilli(),
            dataOriginPackage = record.metadata.dataOrigin.packageName,
            timeZoneOffsetMinutes = if (json.has("time_zone_offset_minutes")) {
                json.getInt("time_zone_offset_minutes")
            } else {
                null
            },
            payloadSchemaVersion = json.getInt("payload_schema_version"),
            valueJson = json.toString(),
            sourceUpdatedAtEpochMs = now().toEpochMilli(),
        )
    }
}
