package com.jhomc.healthsync

import androidx.health.connect.client.HealthConnectClient
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class HealthConnectManagerTest {

    @Test
    fun `compatible when sdk available`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        assertEquals(true, manager.isCompatible())
        val broken = HealthConnectManager(
            FakeHealthConnectGateway().apply { sdk = HealthConnectClient.SDK_UNAVAILABLE },
        )
        assertEquals(false, broken.isCompatible())
    }

    @Test
    fun `core permissions include every catalog type plus background and history`() = runBlocking {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        val expected = RecordTypes.all.map { it.permission }.toSet() +
            androidx.health.connect.client.permission.HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND +
            androidx.health.connect.client.permission.HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY +
            manager.nutritionWritePermission()
        assertEquals(expected, manager.corePermissions())
    }

    @Test
    fun `core batch is exactly the essential catalog`() {
        val manager = HealthConnectManager(FakeHealthConnectGateway())
        assertEquals(RecordTypes.all.map { it.typeName }.toSet(), manager.corePermissions().let { perms ->
            RecordTypes.all.filter { it.permission in perms }.map { it.typeName }.toSet()
        })
    }
}
