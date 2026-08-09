package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import java.time.Instant

enum class TypeStatus { NOT_AVAILABLE, NOT_AUTHORIZED, READY, SYNCED, ERROR }

data class TypeState(val entry: RecordTypeEntry, val status: TypeStatus)

/**
 * Facade over [HealthConnectGateway]: availability, per-type permission state
 * and the steps smoke-read. No WorkManager, no persistence (Phase 2).
 */
class HealthConnectManager(private val gateway: HealthConnectGateway) {

    val catalog: List<RecordTypeEntry> = RecordTypes.all

    suspend fun sdkStatus(): Int = gateway.sdkStatus()

    suspend fun isCompatible(): Boolean = sdkStatus() == HealthConnectClient.SDK_AVAILABLE

    suspend fun backgroundReadAvailable(): Boolean = gateway.backgroundReadAvailable()

    /** Permission set for the core batch (types Samsung Health writes). */
    fun corePermissions(): Set<String> = RecordTypes.core.map { it.permission }.toSet()

    /** One optional family at a time (buttons per family + explanation). */
    fun familyPermissions(family: MappingFamily): Set<String> =
        RecordTypes.optionalByFamily[family].orEmpty().map { it.permission }.toSet()

    suspend fun typeStates(): List<TypeState> {
        val granted = gateway.grantedPermissions()
        val sdkOk = isCompatible()
        return RecordTypes.all.map { entry ->
            val status = when {
                !sdkOk -> TypeStatus.NOT_AVAILABLE
                entry.permission !in granted -> TypeStatus.NOT_AUTHORIZED
                else -> TypeStatus.READY
            }
            TypeState(entry, status)
        }
    }

    suspend fun stepsLast24h(): Long? {
        val end = Instant.now()
        val start = end.minusSeconds(24 * 3600)
        return gateway.stepsCountTotal(start, end)
    }
}

object HealthPermissions {
    val BACKGROUND: String = HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND
}
