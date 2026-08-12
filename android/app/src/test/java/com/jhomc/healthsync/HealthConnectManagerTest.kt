package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectManagerTest {

    @Test
    fun `compatible when sdk available`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        assertTrue(manager.isCompatible())
        val broken = HealthConnectManager(
            FakeHealthConnectGateway().apply { sdk = HealthConnectClient.SDK_UNAVAILABLE },
        )
        assertTrue(!broken.isCompatible())
    }

    @Test
    fun `type states reflect granted permissions`() = runBlocking {
        val gateway = FakeHealthConnectGateway()
        val manager = HealthConnectManager(gateway)
        assertEquals(TypeStatus.NOT_AUTHORIZED, manager.typeStates().first().status)
        gateway.granted = manager.corePermissions()
        val states = manager.typeStates()
        assertEquals(TypeStatus.READY, states.first { it.entry.typeName == "STEPS" }.status)
    }

    @Test
    fun `unavailable sdk marks every type as not available`() = runBlocking {
        val manager = HealthConnectManager(
            FakeHealthConnectGateway().apply { sdk = HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED },
        )
        assertTrue(manager.typeStates().all { it.status == TypeStatus.NOT_AVAILABLE })
    }

    @Test
    fun `steps smoke read uses the gateway aggregate`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway().apply { stepsResult = 12483L })
        assertEquals(12483L, manager.stepsLast24h())
    }
}
