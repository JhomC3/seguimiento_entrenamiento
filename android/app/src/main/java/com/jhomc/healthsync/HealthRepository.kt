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
import com.jhomc.healthsync.data.HealthSyncStateEntity
import com.jhomc.healthsync.data.RecordMappers
import com.jhomc.healthsync.data.SyncMetaEntity
import com.jhomc.healthsync.data.SyncTargetEntity
import java.io.IOException
import java.time.Instant
import java.time.temporal.ChronoUnit
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout

data class TypeSyncResult(
    val recordType: String,
    val upserts: Int = 0,
    val deletes: Int = 0,
    val backfilled: Int = 0,
    val tokenAdvanced: Boolean = false,
    /** True when the run stopped at the per-run page budget: bootstrap is NOT
     *  complete and the next run must resume from the persisted checkpoint. */
    val budgetHit: Boolean = false,
)

/** Types synced per run to stay inside the provider's per-hour quota. */
const val MAX_TYPES_PER_RUN = 1

/**
 * Max pages read per run. Some providers return a non-null pageToken even for
 * EMPTY pages (verified on device: every type shows "more" with 0 records), so
 * an unbounded loop never terminates. The budget bounds the run; the
 * checkpoint persists so the next run resumes.
 */
const val MAX_PAGES_PER_RUN = 50

/** Consecutive EMPTY pages that end the backfill (provider phantom tokens). */
const val MAX_EMPTY_PAGES = 3

/** Max changes pages per drain run (defensive; progress persists per page). */
const val MAX_DRAIN_PAGES_PER_RUN = 50

/** sync_meta key holding the persisted round-robin cursor. */
private const val ROTATION_META_KEY = "round_robin_index"

/** Bootstrap window: 30 days of history fetched on first sync. */
private const val BACKFILL_WINDOW_MS = 30L * 24 * 3_600_000

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

/**
 * Health Connect only allows reading Steps/StepsCadence (and other sensitive
 * series) while the app is in the foreground, unless the user granted
 * background read access. Raised when the provider replies "must be in
 * foreground"; NOT retryable from the worker — the condition only changes by
 * user action (bring the app to the foreground or enable background access).
 */
class ForegroundRequiredException(message: String) : RuntimeException(message)

private fun Throwable.isRateLimited(): Boolean =
    this is RemoteException &&
        (message?.contains("ate limited", ignoreCase = true) == true ||
            message?.contains("uota", ignoreCase = true) == true)

private fun Throwable.isForegroundRequired(): Boolean =
    this is RemoteException && message?.contains("must be in foreground", ignoreCase = true) == true

private fun Throwable.asSyncExceptionOrSelf(): Throwable = when {
    isRateLimited() -> RateLimitedException(message ?: "rate limited")
    isForegroundRequired() -> ForegroundRequiredException(message ?: "foreground required")
    else -> this
}

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
    private val pacer: suspend () -> Unit = { delay(PACING_DEFAULT_MS) },
    private val onProgress: (String) -> Unit = {},
    private val changesTimeoutMs: Long = CHANGES_TIMEOUT_MS,
) {
    companion object {
        const val PACING_DEFAULT_MS = 500L

        /**
         * Tope por llamada a getChanges: algunos proveedores cuelgan el binder
         * en la Changes API (verificado en dispositivo); el timeout convierte
         * el cuelgue en modo rango (backfill idempotente) en vez de un sync
         * infinito que el sistema acaba matando a mitad.
         */
        const val CHANGES_TIMEOUT_MS = 30_000L
    }

    /** Slows the page loop so bursts never blow the provider's per-window quota. */
    private suspend fun pace() = pacer()

    private val dao: HealthDao = db.healthDao()

    /** Backfill window used for first sync and token-expiry recovery. */
    suspend fun syncType(entry: RecordTypeEntry): TypeSyncResult {
        val state = dao.getState(entry.typeName)
        val token = state?.changesToken
        val bootstrapInProgress = state?.bootstrapStartEpochMs != null
        return if (token == null || bootstrapInProgress) {
            firstSync(entry)
        } else {
            drainChanges(entry, token)
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
     * Source phase: sync ONLY the authorized types whose next_due_at has passed
     * and that are not cooling down, budgeted to MAX_TYPES_PER_RUN. Candidates
     * are ordered by priority (HIGH first, in catalog order so the first runs
     * hit the types with guaranteed data: STEPS, HEART_RATE, SLEEP...), then by
     * due time, and the selection rotates from the persisted cursor so no type
     * starves. If nothing is due, no Health Connect call happens at all.
     */
    suspend fun syncAuthorizedTypes(): List<TypeSyncResult> {
        val granted = gateway.grantedPermissions()
        val nowMs = now().toEpochMilli()
        val catalogIndex = HashMap<String, Int>().also { map ->
            RecordTypes.all.forEachIndexed { i, e -> map[e.typeName] = i }
        }
        val candidates = RecordTypes.all
            .filter { it.permission in granted }
            .map { entry -> entry to dao.getState(entry.typeName) }
            .filter { (_, st) ->
                val cooldown = st?.cooldownUntilEpochMs
                cooldown == null || cooldown <= nowMs
            }
            .filter { (_, st) ->
                val due = st?.nextDueAtEpochMs
                due == null || due <= nowMs
            }
            .sortedWith(
                compareByDescending<Pair<RecordTypeEntry, HealthSyncStateEntity?>> {
                    it.second?.priority ?: HealthSyncPlanner.initialPriority(it.first)
                }
                    .thenBy { catalogIndex[it.first.typeName] ?: Int.MAX_VALUE }
                    .thenBy { it.second?.nextDueAtEpochMs ?: 0L }
                    .thenBy { it.first.typeName },
            )
        if (candidates.isEmpty()) return emptyList()

        val cursor = rotationCursor()
        val start = cursor % candidates.size
        val rotated = candidates.drop(start) + candidates.take(start)
        val selected = rotated.take(MAX_TYPES_PER_RUN)
        saveRotationCursor((cursor + selected.size) % candidates.size)

        val results = mutableListOf<TypeSyncResult>()
        for ((entry, _) in selected) {
            try {
                onProgress("Sincronizando ${entry.typeName}…")
                val result = syncType(entry)
                // Solo se marca sincronizado si el bootstrap terminó; si se
                // cortó por presupuesto, el checkpoint permite reanudar y el
                // tipo sigue vencido para la próxima ejecución.
                if (!result.budgetHit) {
                    tokenStore.markSynced(entry.typeName, result.hadChanges(), now().toEpochMilli())
                }
                results += result
            } catch (e: RateLimitedException) {
                tokenStore.markCooldown(entry.typeName, now().toEpochMilli())
                throw e
            } catch (e: SecurityException) {
                tokenStore.markPermissionLost(entry.typeName)
            }
        }
        return results
    }

    private suspend fun rotationCursor(): Int =
        dao.getMeta(ROTATION_META_KEY)?.value?.toIntOrNull() ?: 0

    private suspend fun saveRotationCursor(value: Int) {
        runCatching { dao.putMeta(SyncMetaEntity(ROTATION_META_KEY, value.toString())) }
    }

    private fun TypeSyncResult.hadChanges(): Boolean = upserts + deletes + backfilled > 0

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
        var batchOps = MAX_BATCH_OPERATIONS
        while (true) {
            val batch = dao.pendingOps(target.targetId, batchOps)
            if (batch.isEmpty()) break
            val records = batch.associate { it.hcId to dao.getRecord(it.hcId) }
            val payload = client.buildBatchPayload(deviceId, batch, records)
            if (payload.toString().length > MAX_BATCH_BYTES && batch.size > 1) {
                // Lote sobredimensionado (tipos con series grandes, p. ej.
                // HEART_RATE): partir a la mitad; las ops siguen en el outbox.
                batchOps = (batch.size / 2).coerceAtLeast(1)
                continue
            }
            when (val outcome = client.postBatch(target.url, token, payload)) {
                is UploadOutcome.Accepted -> db.withTransaction {
                    outcome.acked.forEach { dao.ackOp(target.targetId, it.hcId, it.revision) }
                    outcome.rejected.forEach { dao.dropOp(target.targetId, it.hcId) }
                    batchOps = MAX_BATCH_OPERATIONS
                }
                is UploadOutcome.PermanentError -> {
                    if (outcome.detail == "HTTP 413" && batchOps > 1) {
                        // El servidor rechaza por tamaño (estima más conservador):
                        // partir a la mitad y reintentar en vez de rendirse.
                        batchOps = (batch.size / 2).coerceAtLeast(1)
                        continue
                    }
                    return UploadResult(target.targetId, delivered, failed + batch.size, outcome.detail)
                }
                is UploadOutcome.TransientError -> {
                    db.withTransaction { batch.forEach { dao.bumpAttempt(target.targetId, it.hcId) } }
                    failed += batch.size
                    return UploadResult(target.targetId, delivered, failed)
                }
            }
            delivered += batch.size
            onProgress("Entregados $delivered ops al servidor")
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
        // 1) Reserve the changes token BEFORE the backfill and persist it with
        //    the 30-day anchor in the SAME transaction, so a crash mid-backfill
        //    resumes from the reserved token (no gap window) instead of
        //    restarting the token reservation from scratch.
        val nowMs = now().toEpochMilli()
        val state = dao.getState(entry.typeName)
        if (state?.bootstrapStartEpochMs == null && state?.changesToken == null) {
            val reserved = try {
                gateway.getChangesToken(setOf(entry.recordClass))
            } catch (e: RemoteException) {
                if (e.isRateLimited() || e.isForegroundRequired()) throw e.asSyncExceptionOrSelf()
                return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
            } catch (e: IOException) {
                return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
            } catch (e: SecurityException) {
                return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
            }
            db.withTransaction {
                dao.upsertState(
                    state?.copy(
                        changesToken = reserved,
                        permissionGranted = true,
                        lastSuccessfulReadAtEpochMs = nowMs,
                        bootstrapStartEpochMs = nowMs - BACKFILL_WINDOW_MS,
                    )
                        ?: HealthSyncStateEntity(
                            recordType = entry.typeName,
                            changesToken = reserved,
                            permissionGranted = true,
                            lastSuccessfulReadAtEpochMs = nowMs,
                            priority = HealthSyncPlanner.initialPriority(entry),
                            bootstrapStartEpochMs = nowMs - BACKFILL_WINDOW_MS,
                        ),
                )
            }
        }
        // 2) Backfill the window resuming from the last confirmed page, with
        //    the page token checkpointed in the same transaction as each page.
        val anchorMs = dao.getState(entry.typeName)?.bootstrapStartEpochMs ?: (nowMs - BACKFILL_WINDOW_MS)
        val outcome = resumeBackfill(entry, anchorMs)
        // 3) El bootstrap queda COMPLETO en cuanto el backfill termina (antes
        //    del drenaje): si getChanges se cuelga o el sistema mata el
        //    servicio, la próxima ejecución NO rehace el historial desde cero
        //    — solo drena lo nuevo desde el token reservado.
        if (!outcome.budgetHit) {
            db.withTransaction {
                dao.upsertState(
                    dao.getState(entry.typeName)!!.copy(
                        bootstrapPageToken = null,
                        bootstrapStartEpochMs = null,
                        lastSuccessfulReadAtEpochMs = now().toEpochMilli(),
                    ),
                )
            }
        }
        // 4) Drain everything that happened since the reserved token.
        val reservedToken = dao.getState(entry.typeName)?.changesToken
            ?: throw IllegalStateException("bootstrap sin token reservado: ${entry.typeName}")
        val drained = drainChanges(entry, reservedToken, tokenReserved = true)
        return TypeSyncResult(
            recordType = entry.typeName,
            backfilled = outcome.records,
            upserts = drained.upserts,
            deletes = drained.deletes,
            tokenAdvanced = drained.tokenAdvanced,
            budgetHit = outcome.budgetHit,
        )
    }

    /**
     * Paginated 30-day backfill that resumes from the persisted page token:
     * each page and its checkpoint (bootstrap_page_token) commit in ONE
     * transaction, so an interruption (rate limit, crash) continues from the
     * last confirmed page instead of re-reading from the start.
     *
     * Termination guards (verified on device: some providers return a non-null
     * pageToken even for EMPTY pages, which would loop forever):
     *  - MAX_EMPTY_PAGES consecutive empty pages end the backfill (data done).
     *  - A pageToken that does not advance ends the backfill (data done).
     *  - MAX_PAGES_PER_RUN bounds the run; budgetHit=true → next run resumes
     *    from the persisted checkpoint.
     */
    private suspend fun resumeBackfill(entry: RecordTypeEntry, anchorMs: Long): BackfillOutcome {
        val end = now()
        val start = Instant.ofEpochMilli(anchorMs)
        var pageToken = dao.getState(entry.typeName)?.bootstrapPageToken
        var total = 0
        var pageNo = 0
        var emptyPages = 0
        var lastToken: String? = null
        do {
            pageNo++
            if (pageNo > MAX_PAGES_PER_RUN) {
                // Presupuesto agotado: el checkpoint ya persistido permite reanudar.
                return BackfillOutcome(total, budgetHit = true)
            }
            val page: ReadRecordsResponse<Record> = try {
                gateway.readRecords(entry.recordClass, start, end, pageToken)
            } catch (e: RemoteException) {
                throw e.asSyncExceptionOrSelf()
            }
            if (page.pageToken != null && page.pageToken == lastToken) {
                // El token no avanza: el proveedor no tiene más datos.
                return BackfillOutcome(total, budgetHit = false)
            }
            lastToken = page.pageToken
            val entities = page.records.map { toEntity(it) }
            if (entities.isEmpty()) {
                emptyPages++
                if (emptyPages >= MAX_EMPTY_PAGES) {
                    // Páginas fantasma vacías: el historial está agotado.
                    return BackfillOutcome(total, budgetHit = false)
                }
            } else {
                emptyPages = 0
            }
            db.withTransaction {
                dao.applyBackfillPage(entities, now().toEpochMilli())
                dao.upsertState(
                    dao.getState(entry.typeName)!!.copy(
                        bootstrapPageToken = page.pageToken,
                        lastSuccessfulReadAtEpochMs = now().toEpochMilli(),
                    ),
                )
            }
            total += entities.size
            onProgress("${entry.typeName}: página $pageNo (${total} registros)")
            pageToken = page.pageToken
            if (pageToken != null) pace()
        } while (pageToken != null)
        return BackfillOutcome(total, budgetHit = false)
    }

    /** Result of one resumeBackfill run. */
    private data class BackfillOutcome(val records: Int, val budgetHit: Boolean)

    private suspend fun backfill(entry: RecordTypeEntry): Int {
        val end = now()
        val start = end.minus(30, ChronoUnit.DAYS)
        var pageToken: String? = null
        var total = 0
        var emptyPages = 0
        var lastToken: String? = null
        do {
            val page: ReadRecordsResponse<Record> = try {
                gateway.readRecords(entry.recordClass, start, end, pageToken)
            } catch (e: RemoteException) {
                throw e.asSyncExceptionOrSelf()
            }
            if (page.pageToken != null && page.pageToken == lastToken) break
            lastToken = page.pageToken
            val entities = page.records.map { toEntity(it) }
            if (entities.isEmpty()) {
                emptyPages++
                if (emptyPages >= MAX_EMPTY_PAGES) break
            } else {
                emptyPages = 0
            }
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
        var pages = 0
        var emptyPages = 0
        var lastToken: String? = null
        while (true) {
            if (++pages > MAX_DRAIN_PAGES_PER_RUN) break
            val response: ChangesResponse = try {
                withTimeout(changesTimeoutMs) { gateway.getChanges(current) }
            } catch (e: ChangesTokenExpiredException) {
                recoverFromExpiry(entry)
                return TypeSyncResult(entry.typeName, tokenAdvanced = true)
            } catch (e: TimeoutCancellationException) {
                // El proveedor cuelga la Changes API (binder): modo rango
                // (backfill idempotente) en vez de un sync infinito.
                val backfilled = backfill(entry)
                return TypeSyncResult(entry.typeName, backfilled = backfilled)
            } catch (e: RemoteException) {
                if (e.isRateLimited() || e.isForegroundRequired()) throw e.asSyncExceptionOrSelf()
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
            // Defensivo: un token que no avanza o páginas vacías repetidas
            // significan que no hay más cambios (proveedores con tokens fantasma).
            if (response.nextChangesToken == lastToken) break
            if (response.changes.isEmpty()) {
                emptyPages++
                if (emptyPages >= MAX_EMPTY_PAGES) break
            } else {
                emptyPages = 0
            }
            lastToken = response.nextChangesToken
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
