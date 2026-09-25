package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.feature.ExperimentalMindfulnessSessionApi
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.NutritionRecord

/**
 * Facade over [HealthConnectGateway]: availability, provider details and the
 * essential permission batch. No WorkManager, no persistence (Phase 2).
 */
class HealthConnectManager(private val gateway: HealthConnectGateway) {

    val catalog: List<RecordTypeEntry> = RecordTypes.all

    suspend fun sdkStatus(): Int = gateway.sdkStatus()

    suspend fun isCompatible(): Boolean = sdkStatus() == HealthConnectClient.SDK_AVAILABLE

    suspend fun backgroundReadAvailable(): Boolean = gateway.backgroundReadAvailable()

    /**
     * Permisos ESENCIALES: el catálogo completo (29 tipos) + lectura en
     * segundo plano + historial + escritura nutricional. Un solo botón pide todo.
     */
    fun corePermissions(): Set<String> =
        RecordTypes.all.map { it.permission }.toSet() +
            HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND +
            HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY +
            nutritionWritePermission()

    /** WRITE_NUTRITION vía SDK (sin hardcodear el string del permiso). */
    fun nutritionWritePermission(): String =
        HealthPermission.getWritePermission(NutritionRecord::class)

    fun nutritionWritePermissions(): Set<String> = setOf(nutritionWritePermission())

    /** WRITE_MINDFULNESS vía SDK (meditaciones de respiración; bajo demanda). */
    @OptIn(ExperimentalMindfulnessSessionApi::class)
    fun mindfulnessWritePermission(): String =
        HealthPermission.getWritePermission(
            androidx.health.connect.client.records.MindfulnessSessionRecord::class,
        )

    fun mindfulnessWritePermissions(): Set<String> = setOf(mindfulnessWritePermission())

    /** Exposes the underlying gateway for cache invalidation after permission flows. */
    fun gateway(): HealthConnectGateway = gateway

    suspend fun providerDetail(): ProviderDetail = gateway.providerDetail()
}

object HealthPermissions {
    val BACKGROUND: String = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND
}
