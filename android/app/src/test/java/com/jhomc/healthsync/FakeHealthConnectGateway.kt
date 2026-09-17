package com.jhomc.healthsync

import android.os.RemoteException
import androidx.activity.result.contract.ActivityResultContract
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.response.ChangesResponse
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.response.ReadRecordsResponse
import java.time.Instant
import kotlin.reflect.KClass

class FakeHealthConnectGateway : HealthConnectGateway {

    var sdk = HealthConnectClient.SDK_AVAILABLE
    var granted: Set<String> = emptySet()
    var background = true
    var stepsResult: Long? = null

    val backfillQueue = mutableListOf<List<Record>>()
    val changesQueue = mutableListOf<ChangesResponse>()
    var tokenCounter = 0

    // -- Registro de llamadas para aserciones de presupuesto/rotación --
    val tokenLog = mutableListOf<String>()                       // typeName por getChangesToken
    val readLog = mutableListOf<Pair<String, String?>>()          // (typeName, pageToken) por readRecords
    val changesLog = mutableListOf<String>()                      // token por getChanges
    var failNextTokenWithRateLimit = false                       // getChangesToken → RemoteException rate-limited
    var failReadsWithRateLimit = false                           // readRecords → RemoteException rate-limited (falla la 1ª página NO inicial, para confirmar el checkpoint)
    var failReadsWithForegroundRequired = false                  // readRecords → RemoteException "must be in foreground" (one-shot)

    /** Modo proveedor fantasma: páginas VACÍAS con token nuevo (nunca termina por sí solo). */
    var phantomEmptyPages = false
    /** Modo proveedor fantasma: token idéntico repetido (no avanza). */
    var phantomSameToken = false
    /** Proveedor con registros paginados de 1 en 1 (sirve para probar el presupuesto por ejecución). */
    val phantomRecords = mutableListOf<Record>()

    /** Resultados de aggregateTotal por typeName (p. ej. "STEPS_H1" → 9018). */
    val aggregateTotals = mutableMapOf<String, Long?>()
    /** Tipos para los que se llamó a aggregateTotal. */
    val aggregateTotalLog = mutableListOf<String>()
    val pageStore = mutableMapOf<String?, List<Record>>()         // paginación determinista para bootstrap (null = primera página)

    /** When true, getChanges throws AFTER returning a page (crash before commit). */
    var crashAfterGetChanges = false

    /** When true, getChanges nunca responde (binder colgado del proveedor). */
    var getChangesHangs = false

    /** When true, readRecords nunca responde (binder colgado del proveedor). */
    var readRecordsHangs = false

    /**
     * Hook opcional: si está definido, readRecords delega en él (permite
     * respuestas por ventana de tiempo, p. ej. un día distinto por llamada,
     * o simular colgues por tipo).
     */
    var readRecordsHandler: (suspend (
        recordType: KClass<out Record>,
        start: Instant,
        end: Instant,
        pageToken: String?,
    ) -> ReadRecordsResponse<Record>?)? = null

    // Health Connect is idempotent per token: the same token always yields the
    // same page until the client advances it. Simulate that with a cache.
    private val pageCache = mutableMapOf<String, ChangesResponse>()

    override suspend fun sdkStatus() = sdk
    override suspend fun grantedPermissions() = granted
    override suspend fun backgroundReadAvailable() = background
    override suspend fun stepsCountTotal(start: Instant, end: Instant) = stepsResult
    override fun permissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        throw UnsupportedOperationException()

    override suspend fun getChangesToken(recordTypes: Set<KClass<out Record>>): String {
        tokenCounter++
        tokenLog += recordTypes.mapNotNull { RecordTypes.byClass(it)?.typeName }
        if (failNextTokenWithRateLimit) {
            failNextTokenWithRateLimit = false
            throw RemoteException("Rate limited request quota has been exceeded")
        }
        return "token-$tokenCounter"
    }

    override suspend fun aggregateTotal(
        recordClass: KClass<out Record>,
        start: Instant,
        end: Instant,
    ): Long? {
        val typeName = RecordTypes.byClass(recordClass)?.typeName ?: return null
        aggregateTotalLog += typeName
        return aggregateTotals[typeName]
    }

    override suspend fun getChanges(token: String): ChangesResponse {
        changesLog += token
        if (getChangesHangs) {
            kotlinx.coroutines.delay(60_000)
            throw AssertionError("unreachable")
        }
        val cached = pageCache[token]
        if (cached != null) {
            if (crashAfterGetChanges) {
                crashAfterGetChanges = false
                throw RuntimeException("simulated crash before commit")
            }
            return cached
        }
        val page = if (changesQueue.isNotEmpty()) changesQueue.removeAt(0)
        else ChangesResponse(emptyList(), "next-of-$token", hasMore = false, changesTokenExpired = false)
        pageCache[token] = page
        if (crashAfterGetChanges) {
            crashAfterGetChanges = false
            throw RuntimeException("simulated crash before commit")
        }
        return page
    }

    override suspend fun readRecords(
        recordType: KClass<out Record>,
        start: Instant,
        end: Instant,
        pageToken: String?,
    ): ReadRecordsResponse<Record> {
        readLog += (RecordTypes.byClass(recordType)?.typeName ?: "?") to pageToken
        readRecordsHandler?.let { handler ->
            val handled = handler(recordType, start, end, pageToken)
            if (handled != null) return handled
        }
        if (readRecordsHangs) {
            kotlinx.coroutines.delay(60_000)
            throw AssertionError("unreachable")
        }
        if (failReadsWithRateLimit && pageToken != null) {
            failReadsWithRateLimit = false
            throw RemoteException("Rate limited request quota has been exceeded")
        }
        if (failReadsWithForegroundRequired) {
            failReadsWithForegroundRequired = false
            throw RemoteException(
                "com.jhomc.healthsync must be in foreground to read the following data types " +
                    "[Steps, StepsCadenceSeries]",
            )
        }
        if (phantomEmptyPages) {
            val next = if (phantomSameToken) (pageToken ?: "pt-loop") else "pt-${tokenCounter++}"
            return ReadRecordsResponse(emptyList(), next)
        }
        if (phantomRecords.isNotEmpty()) {
            val record = phantomRecords.removeAt(0)
            val next = if (phantomRecords.isNotEmpty()) "pt-${tokenCounter++}" else null
            return ReadRecordsResponse(listOf(record), next)
        }
        if (backfillQueue.isNotEmpty()) {
            val page = backfillQueue.removeAt(0)
            return ReadRecordsResponse(page, if (backfillQueue.isNotEmpty()) "page-token-${tokenCounter}" else null)
        }
        val records = pageStore[pageToken].orEmpty()
        val next = when {
            pageToken == null && pageStore.containsKey("pt-1") -> "pt-1"
            pageToken == "pt-1" && pageStore.containsKey("pt-2") -> "pt-2"
            else -> null
        }
        return ReadRecordsResponse(records, next)
    }

    override suspend fun providerDetail() = ProviderDetail(
        packageName = "com.google.android.apps.healthdata",
        installedVersionCode = 1752L,
        minRequiredVersionCode = 1000L,
    )
}
