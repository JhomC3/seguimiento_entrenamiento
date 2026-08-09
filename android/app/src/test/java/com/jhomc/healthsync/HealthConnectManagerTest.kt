package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FakeHealthConnectGateway(
    private var sdk: Int = HealthConnectClient.SDK_AVAILABLE,
    private var granted: Set<String> = emptySet(),
    private var background: Boolean = true,
    private var steps: Long? = 8123L,
) : HealthConnectGateway {

    override suspend fun sdkStatus(): Int = sdk
    override suspend fun grantedPermissions(): Set<String> = granted
    override suspend fun backgroundReadAvailable(): Boolean = background
    override suspend fun stepsCountTotal(start: Instant, end: Instant): Long? = steps
    override fun permissionContract(): androidx.activity.result.contract.ActivityResultContract<Set<String>, Set<String>> =
        throw UnsupportedOperationException("permission contract is UI-only")

    fun grant(permissions: Set<String>) {
        granted = granted + permissions
    }
}

class HealthConnectManagerTest {

    @Test
    fun `compatible when sdk available`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        assertTrue(manager.isCompatible())
        val broken = HealthConnectManager(FakeHealthConnectGateway(sdk = HealthConnectClient.SDK_UNAVAILABLE))
        assertTrue(!broken.isCompatible())
    }

    @Test
    fun `core batch excludes sensitive medical types`() {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        val core = manager.corePermissions()
        assertTrue(core.isNotEmpty())
        val medical = manager.familyPermissions(MappingFamily.MEDICAL)
        assertTrue(medical.none { it in core })
        assertTrue(medical.isNotEmpty())
    }

    @Test
    fun `type states reflect granted permissions`() = runBlocking {
        val gateway = FakeHealthConnectGateway()
        val manager = HealthConnectManager(gateway)
        assertEquals(TypeStatus.NOT_AUTHORIZED, manager.typeStates().first().status)
        gateway.grant(manager.corePermissions())
        val states = manager.typeStates()
        assertEquals(TypeStatus.READY, states.first { it.entry.typeName == "STEPS" }.status)
        assertEquals(
            TypeStatus.NOT_AUTHORIZED,
            states.first { it.entry.family == MappingFamily.MEDICAL }.status,
        )
    }

    @Test
    fun `unavailable sdk marks every type as not available`() = runBlocking {
        val manager = HealthConnectManager(
            FakeHealthConnectGateway(sdk = HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED),
        )
        assertTrue(manager.typeStates().all { it.status == TypeStatus.NOT_AVAILABLE })
    }

    @Test
    fun `steps smoke read uses the gateway aggregate`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway(steps = 12483L))
        assertEquals(12483L, manager.stepsLast24h())
    }
}
