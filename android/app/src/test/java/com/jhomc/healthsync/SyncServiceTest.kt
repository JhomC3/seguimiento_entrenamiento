package com.jhomc.healthsync

import android.app.NotificationManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowNotificationManager

/**
 * El servicio en primer plano ejecuta el sync (runner inyectado), publica el
 * progreso en el StateFlow y la notificación, y termina al completarse.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class SyncServiceTest {

    private val originalRunner = SyncService.runner

    @Before
    fun setUp() {
        SyncService.progress.value = SyncStage.Idle
    }

    @After
    fun tearDown() {
        SyncService.runner = originalRunner
        SyncService.progress.value = SyncStage.Idle
    }

    private fun waitUntilDone(deadlineMs: Long = 8_000) {
        val deadline = System.currentTimeMillis() + deadlineMs
        while (SyncService.progress.value !is SyncStage.Done && System.currentTimeMillis() < deadline) {
            Thread.sleep(20)
        }
    }

    @Test
    fun `service runs the sync publishes progress and completes`() {
        SyncService.runner = { ctx, onProgress ->
            onProgress("STEPS: página 1 (10 registros)")
            SyncReport(typesSynced = 1, delivered = 10, failed = 0)
        }
        val controller = Robolectric.buildService(SyncService::class.java).create()
        controller.startCommand(0, 0)

        waitUntilDone()
        val stage = SyncService.progress.value
        assertTrue("debe terminar en Done, fue: $stage", stage is SyncStage.Done)
        assertEquals(10, (stage as SyncStage.Done).report.delivered)
        assertEquals(1, stage.report.typesSynced)

        val nm = ApplicationProvider.getApplicationContext<Context>()
            .getSystemService(NotificationManager::class.java)
        val shadow = org.robolectric.Shadows.shadowOf(nm)
        assertTrue("debe publicar notificaciones de progreso", shadow.size() > 0)
    }

    @Test
    fun `failed runner surfaces the error as Failed stage`() {
        SyncService.runner = { _, _ -> throw IllegalStateException("explosión controlada") }
        Robolectric.buildService(SyncService::class.java).create().startCommand(0, 0)

        val deadline = System.currentTimeMillis() + 8_000
        while (SyncService.progress.value !is SyncStage.Failed && System.currentTimeMillis() < deadline) {
            Thread.sleep(20)
        }
        val stage = SyncService.progress.value
        assertTrue("debe terminar en Failed, fue: $stage", stage is SyncStage.Failed)
        assertTrue((stage as SyncStage.Failed).error.contains("explosión"))
    }
}
