package com.jhomc.healthsync

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

    /** When true, getChanges throws AFTER returning a page (crash before commit). */
    var crashAfterGetChanges = false

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
        return "token-$tokenCounter"
    }

    override suspend fun getChanges(token: String): ChangesResponse {
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
        if (backfillQueue.isEmpty()) return ReadRecordsResponse(emptyList(), null)
        val page = backfillQueue.removeAt(0)
        return ReadRecordsResponse(page, if (backfillQueue.isNotEmpty()) "page-token-${tokenCounter}" else null)
    }

    override suspend fun providerDetail() = ProviderDetail(
        packageName = "com.google.android.apps.healthdata",
        installedVersionCode = 1752L,
        minRequiredVersionCode = 1000L,
    )
}
