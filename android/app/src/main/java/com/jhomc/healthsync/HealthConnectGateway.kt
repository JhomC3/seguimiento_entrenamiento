package com.jhomc.healthsync

import android.content.Context
import androidx.activity.result.contract.ActivityResultContract
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant

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
}

class RealHealthConnectGateway(context: Context) : HealthConnectGateway {

    private val appContext = context.applicationContext
    private val client: HealthConnectClient = HealthConnectClient.getOrCreate(appContext)

    override suspend fun sdkStatus(): Int = HealthConnectClient.getSdkStatus(appContext)

    override suspend fun grantedPermissions(): Set<String> =
        client.permissionController.getGrantedPermissions()

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

    override fun permissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        PermissionController.createRequestPermissionResultContract()
}
