package com.jhomc.healthsync

import android.os.RemoteException
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
import com.jhomc.healthsync.data.SyncTargetEntity
import java.io.IOException
import java.time.Instant
import java.time.temporal.ChronoUnit

data class TypeSyncResult(
    val recordType: String,
    val upserts: Int = 0,
    val deletes: Int = 0,
    val backfilled: Int = 0,
    val tokenAdvanced: Boolean = false,
)

/** Types synced per run to stay inside the provider's per-hour quota. */
const val MAX_TYPES_PER_RUN = 3

data class UploadResult(
    val targetId: Long,
    val delivered: Int,
    val failed: Int,
    val permanentError: String? = null,
)

/** Token expired signal, per the 1.1.0 SDK contract (changesTokenExpired + exception). */
class ChangesTokenExpiredException(message: String) : RuntimeException(message)

/**
 * Health Connect enforces per-app usage quotas (new apps start with a low
 * per-hour limit). Raised when the provider replies "rate limited"; callers
 * must NOT retry immediately — wait for the quota to replenish.
 */
class RateLimitedException(message: String) : RuntimeException(message)

private fun Throwable.isRateLimited(): Boolean =
    this is RemoteException &&
        (message?.contains("ate limited", ignoreCase = true) == true ||
            message?.contains("uota", ignoreCase = true) == true)

private fun Throwable.asRateLimitedOrSelf(): Throwable =
    if (isRateLimited()) RateLimitedException(message ?: "rate limited") else this

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

    /**
     * Structural fallback: the Changes API depends on the provider generation
     * (verified on-device: aggregate works, getChangesToken raises
     * RemoteException against providers newer than the SDK). When Changes is
     * unavailable, the type syncs in range mode (paginated 30-day backfill,
     * idempotent by hc_id + revision).
     */
    private fun isChangesUnavailable(e: Exception): Boolean =
        e is RemoteException || e is IOException || e is SecurityException

    /**
     * Source phase: sync authorized types, throttled. Health Connect gives new
     * apps a low per-hour quota; a single run touching every type would burn
     * it. MAX_TYPES_PER_RUN types per run; the rest sync in later runs.
     */
    suspend fun syncAuthorizedTypes(): List<TypeSyncResult> {
        val granted = gateway.grantedPermissions()
        return RecordTypes.all.mapNotNull { entry ->
            if (entry.permission !in granted) return@mapNotNull null
            try {
                syncType(entry)
            } catch (e: SecurityException) {
                tokenStore.markPermissionLost(entry.typeName)
                null
            }
        }.take(MAX_TYPES_PER_RUN)
    }

    /**
     * Delivery phase: upload pending outbox ops for every active target in
     * bounded batches. Only server-confirmed ops are marked delivered;
     * permanent errors stop the batch loop for that target.
     */
    suspend fun uploadPending(
        client: HealthSyncClient,
        target: SyncTargetEntity,
        token: String,
        deviceId: String,
    ): UploadResult {
        var delivered = 0
        var failed = 0
        while (true) {
            val batch = dao.pendingOps(target.targetId, MAX_BATCH_OPERATIONS)
            if (batch.isEmpty()) break
            val records = batch.associate { it.hcId to dao.getRecord(it.hcId) }
            val payload = client.buildBatchPayload(deviceId, batch, records)
            when (val outcome = client.postBatch(target.url, token, payload)) {
                is UploadOutcome.Accepted -> db.withTransaction {
                    outcome.acked.forEach { dao.ackOp(target.targetId, it.hcId, it.revision) }
                    outcome.rejected.forEach { dao.dropOp(target.targetId, it.hcId) }
                }
                is UploadOutcome.PermanentError ->
                    return UploadResult(target.targetId, delivered, failed + batch.size, outcome.detail)
                is UploadOutcome.TransientError -> {
                    db.withTransaction { batch.forEach { dao.bumpAttempt(target.targetId, it.hcId) } }
                    failed += batch.size
                    return UploadResult(target.targetId, delivered, failed)
                }
            }
            delivered += batch.size
        }
        return UploadResult(target.targetId, delivered, failed)
    }

    /** Replay the active buffer into a brand-new target (seed, not re-sync). */
    suspend fun seedNewTarget(targetId: Long) {
        dao.seedTarget(targetId, now().toEpochMilli())
    }

    /**
     * Resolves the configured URL to a sync_targets row. A NEW URL gets a new
     * target_id and a seed of every active record (replay of the buffer, the
     * Health Connect source is never re-read). Same URL reuses the row.
     */
    suspend fun ensureTarget(url: String, name: String): SyncTargetEntity {
        dao.activeTargets().firstOrNull { it.url == url }?.let { return it }
        val targetId = dao.upsertTarget(
            SyncTargetEntity(0, url, name, active = true, createdAtEpochMs = now().toEpochMilli()),
        )
        dao.seedTarget(targetId, now().toEpochMilli())
        return dao.getTarget(targetId) ?: throw IllegalStateException("target no creado")
    }

    private suspend fun firstSync(entry: RecordTypeEntry): TypeSyncResult {
        // 1) Reserve the changes token BEFORE the backfill, so changes that
        //    arrive while backfilling are drained afterwards (no gap window).
        val reserved = try {
            gateway.getChangesToken(setOf(entry.recordClass))
        } catch (e: RemoteException) {
            if (e.isRateLimited()) throw e.asRateLimitedOrSelf()
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        } catch (e: IOException) {
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        } catch (e: SecurityException) {
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        }
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
            val page: ReadRecordsResponse<Record> = try {
                gateway.readRecords(entry.recordClass, start, end, pageToken)
            } catch (e: RemoteException) {
                throw e.asRateLimitedOrSelf()
            }
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
            } catch (e: RemoteException) {
                if (e.isRateLimited()) throw e.asRateLimitedOrSelf()
                // Changes API no disponible con este proveedor: modo rango.
                val backfilled = backfill(entry)
                return TypeSyncResult(entry.typeName, backfilled = backfilled)
            } catch (e: IOException) {
                val backfilled = backfill(entry)
                return TypeSyncResult(entry.typeName, backfilled = backfilled)
            } catch (e: SecurityException) {
                val backfilled = backfill(entry)
                return TypeSyncResult(entry.typeName, backfilled = backfilled)
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

    private fun toEntity(record: Record): HealthRecordEntity {        val entry = RecordTypes.byClass(record::class)
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
