package com.jhomc.healthsync

import android.content.Context
import androidx.activity.result.contract.ActivityResultContract
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ChangesTokenRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.response.ChangesResponse
import androidx.health.connect.client.response.ReadRecordsResponse
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import kotlin.reflect.KClass

/**
 * Small seam around the Health Connect SDK so repositories and workers can be
 * unit-tested with a fake. The real implementation wraps HealthConnectClient.
 */
interface HealthConnectGateway {
    suspend fun sdkStatus(): Int
    suspend fun grantedPermissions(): Set<String>
    suspend fun backgroundReadAvailable(): Boolean
    suspend fun stepsCountTotal(start: Instant, end: Instant): Long?
    fun permissionContract(): ActivityResultContract<Set<String>, Set<String>>

    // Phase 2: differential sync
    suspend fun getChangesToken(recordTypes: Set<KClass<out Record>>): String
    suspend fun getChanges(token: String): ChangesResponse
    suspend fun readRecords(
        recordType: KClass<out Record>,
        start: Instant,
        end: Instant,
        pageToken: String?,
    ): ReadRecordsResponse<Record>

    // Phase 5: provider diagnostics
    suspend fun providerDetail(): ProviderDetail
}

data class ProviderDetail(
    val packageName: String,
    val installedVersionCode: Long?,
    val minRequiredVersionCode: Long,
)

class RealHealthConnectGateway(context: Context) : HealthConnectGateway {

    private val appContext = context.applicationContext
    private val client: HealthConnectClient = HealthConnectClient.getOrCreate(appContext)

    // Granted-permission cache: refreshStates() runs on every onResume and a
    // binder call per screen refresh is wasteful (and a quota call).
    @Volatile
    private var cachedGranted: Set<String>? = null
    @Volatile
    private var cachedGrantedAtMs: Long = 0L

    companion object {
        private const val PERMISSION_CACHE_TTL_MS = 15_000L
    }

    override suspend fun sdkStatus(): Int = HealthConnectClient.getSdkStatus(appContext)

    override suspend fun grantedPermissions(): Set<String> {
        val nowMs = System.currentTimeMillis()
        cachedGranted?.let { cached ->
            if (nowMs - cachedGrantedAtMs < PERMISSION_CACHE_TTL_MS) return cached
        }
        val fresh = client.permissionController.getGrantedPermissions()
        cachedGranted = fresh
        cachedGrantedAtMs = nowMs
        return fresh
    }

    /** Call after the permission flow returns so the next read is fresh. */
    fun invalidatePermissionCache() {
        cachedGranted = null
        cachedGrantedAtMs = 0L
    }

    override suspend fun backgroundReadAvailable(): Boolean =
        client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) ==
            HealthConnectFeatures.FEATURE_STATUS_AVAILABLE

    override suspend fun stepsCountTotal(start: Instant, end: Instant): Long? {
        val response = client.aggregate(
            AggregateRequest(
                metrics = setOf(StepsRecord.COUNT_TOTAL),
                timeRangeFilter = TimeRangeFilter.between(start, end),
            ),
        )
        return response[StepsRecord.COUNT_TOTAL]
    }

    override suspend fun getChangesToken(recordTypes: Set<KClass<out Record>>): String =
        client.getChangesToken(ChangesTokenRequest(recordTypes))

    override suspend fun getChanges(token: String): ChangesResponse =
        client.getChanges(token)

    override suspend fun readRecords(
        recordType: KClass<out Record>,
        start: Instant,
        end: Instant,
        pageToken: String?,
    ): ReadRecordsResponse<Record> {
        val response = client.readRecords(
            ReadRecordsRequest(
                recordType = recordType,
                timeRangeFilter = TimeRangeFilter.between(start, end),
                pageSize = 500,
                pageToken = pageToken,
            ),
        )
        @Suppress("UNCHECKED_CAST")
        return response as ReadRecordsResponse<Record>
    }

    override fun permissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        PermissionController.createRequestPermissionResultContract()

    override suspend fun providerDetail(): ProviderDetail {
        val installed = runCatching {
            appContext.packageManager.getPackageInfo(
                HealthConnectProvider.PACKAGE_NAME,
                0,
            ).longVersionCode
        }.getOrNull()
        return ProviderDetail(
            packageName = HealthConnectProvider.PACKAGE_NAME,
            installedVersionCode = installed,
            minRequiredVersionCode = HealthConnectProvider.MIN_VERSION_CODE,
        )
    }
}

/**
 * Health Connect provider constants for connect-client 1.1.0. The SDK marks
 * DEFAULT_PROVIDER_* as internal; values verified from the 1.1.0 AAR bytecode.
 */
object HealthConnectProvider {
    const val PACKAGE_NAME = "com.google.android.apps.healthdata"
    const val MIN_VERSION_CODE = 68_623L
}
