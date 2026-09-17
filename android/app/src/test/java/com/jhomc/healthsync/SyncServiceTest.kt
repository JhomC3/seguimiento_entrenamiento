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

    private fun waitFor(deadlineMs: Long = 8_000, predicate: () -> Boolean) {
        val deadline = System.currentTimeMillis() + deadlineMs
        while (!predicate() && System.currentTimeMillis() < deadline) {
            Thread.sleep(20)
        }
    }

    private fun notificationShadow() = org.robolectric.Shadows.shadowOf(
        ApplicationProvider.getApplicationContext<Context>()
            .getSystemService(NotificationManager::class.java),
    )

    @Test
    fun `service runs the sync publishes progress and completes`() {
        SyncService.runner = { ctx, onProgress ->
            onProgress("STEPS: página 1 (10 registros)")
            SyncReport(typesSynced = 1, delivered = 10, failed = 0)
        }
        val controller = Robolectric.buildService(SyncService::class.java).create()
        controller.startCommand(0, 0)

        // La notificación se publica DURANTE el sync (el finally la cancela al terminar).
        waitFor { notificationShadow().getNotification(SyncService.NOTIFICATION_ID) != null }
        assertTrue("debe publicar la notificación de progreso", notificationShadow().getNotification(SyncService.NOTIFICATION_ID) != null)

        waitFor { SyncService.progress.value is SyncStage.Done }
        val stage = SyncService.progress.value
        assertTrue("debe terminar en Done, fue: $stage", stage is SyncStage.Done)
        assertEquals(10, (stage as SyncStage.Done).report.delivered)
        assertEquals(1, stage.report.typesSynced)
    }

    @Test
    fun `notification opens the app on click and is removed when the service stops`() {
        SyncService.runner = { _, onProgress ->
            onProgress("STEPS: página 1")
            SyncReport(typesSynced = 1, delivered = 1, failed = 0)
        }
        val controller = Robolectric.buildService(SyncService::class.java).create()
        controller.startCommand(0, 0)

        waitFor { notificationShadow().getNotification(SyncService.NOTIFICATION_ID) != null }
        val notification = notificationShadow().getNotification(SyncService.NOTIFICATION_ID)
        assertTrue("debe publicar la notificación de progreso", notification != null)
        val pendingIntent = notification?.contentIntent
        assertTrue("el clic debe abrir la app", pendingIntent != null)
        val resolved = org.robolectric.Shadows.shadowOf(pendingIntent)?.savedIntent?.component?.className
        assertTrue("debe apuntar a MainActivity, fue: $resolved", resolved?.endsWith("MainActivity") == true)

        // El servicio se detiene solo → la notificación se elimina explícitamente.
        waitFor { SyncService.progress.value is SyncStage.Done }
        waitFor { notificationShadow().getNotification(SyncService.NOTIFICATION_ID) == null }
        assertTrue(
            "la notificación debe eliminarse al terminar el servicio",
            notificationShadow().getNotification(SyncService.NOTIFICATION_ID) == null,
        )
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

    @Test
    fun `destroyed service reports interruption instead of cryptic job error`() {
        SyncService.runner = { _, onProgress ->
            onProgress("STEPS: página 1") // prueba que el cuerpo de la corrutina arrancó
            kotlinx.coroutines.delay(Long.MAX_VALUE)
            SyncReport(0, 0, 0)
        }
        val controller = Robolectric.buildService(SyncService::class.java).create()
        controller.startCommand(0, 0)

        // Espera a que la corrutina esté DENTRO del runner (no solo "Iniciando…").
        val started = System.currentTimeMillis() + 5_000
        while (System.currentTimeMillis() < started) {
            val stage = SyncService.progress.value
            if (stage is SyncStage.Running && stage.stage.contains("STEPS")) break
            Thread.sleep(10)
        }
        assertTrue(
            "el runner debe haber arrancado, fue: ${SyncService.progress.value}",
            SyncService.progress.value is SyncStage.Running &&
                (SyncService.progress.value as SyncStage.Running).stage.contains("STEPS"),
        )
        controller.destroy() // simula el sistema matando el servicio a mitad

        val deadline = System.currentTimeMillis() + 8_000
        while (SyncService.progress.value !is SyncStage.Failed && System.currentTimeMillis() < deadline) {
            Thread.sleep(10)
        }
        val stage = SyncService.progress.value
        assertTrue("debe terminar en Failed, fue: $stage", stage is SyncStage.Failed)
        assertTrue(
            "mensaje claro de interrupción: ${(stage as SyncStage.Failed).error}",
            stage.error.contains("interrumpida"),
        )
    }

    @Test
    fun `noticeMessage explains how to fix missing destination and token`() {
        val noTarget = SyncService.noticeMessage(SyncReport(17, 0, 0, notice = "sin_destino"))
        assertTrue("sin_destino debe ser accionable, fue: $noTarget", noTarget?.contains("APK debug") == true)

        val noToken = SyncService.noticeMessage(SyncReport(17, 0, 0, notice = "sin_token_guardado"))
        assertTrue("sin_token_guardado debe pedir recompilar, fue: $noToken", noToken?.contains("recompila") == true)

        val badUrl = SyncService.noticeMessage(SyncReport(17, 0, 0, notice = "url_invalida: http://x"))
        assertTrue("url_invalida debe mencionar la IP, fue: $badUrl", badUrl?.contains("IP") == true)

        val noPerms = SyncService.noticeMessage(SyncReport(0, 0, 0, notice = "sin_permisos"))
        assertTrue("sin_permisos debe pedir el botón, fue: $noPerms", noPerms?.contains("Permisos esenciales") == true)

        val badToken = SyncService.noticeMessage(SyncReport(17, 0, 1, permanentError = "HTTP 401"))
        assertTrue("401 debe explicar el mismatch, fue: $badToken", badToken?.contains("401") == true)

        val badBatch = SyncService.noticeMessage(
            SyncReport(17, 0, 500, permanentError = "HTTP 400: {\"detail\":\"Operación 2\"}"),
        )
        assertTrue("400 debe mencionar cuarentena, fue: $badBatch", badBatch?.contains("Cuarentena") == true)

        val ok = SyncService.noticeMessage(SyncReport(17, 42, 0))
        assertTrue("reporte sano no tiene aviso accionable, fue: $ok", ok == null)
    }

    @Test
    fun `summaryOf muestra cuarentena cuando hay ops aisladas`() {
        val text = SyncService.summaryOf(SyncReport(17, 499, 0, quarantined = 1))
        assertTrue("debe pintar cuarentena, fue: $text", text.contains("Cuarentena: 1"))
    }

    @Test
    fun `summaryOf muestra el motivo de cuarentena cuando existe`() {
        val text = SyncService.summaryOf(
            SyncReport(17, 0, 0, quarantined = 2, quarantineSample = "record_type fuera de allow-list"),
        )
        assertTrue("debe pintar el motivo, fue: $text", text.contains("record_type fuera"))
    }
}
