package com.jhomc.healthsync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** Etapas del sync observables desde la UI (panel) y la notificación. */
sealed interface SyncStage {
    data object Idle : SyncStage
    data class Running(val stage: String) : SyncStage
    data class Done(val report: SyncReport) : SyncStage
    data class Failed(val error: String) : SyncStage
}

/**
 * Ejecuta la sincronización en un servicio en primer plano: Android trata la
 * app como activa aunque la pantalla esté apagada, y Health Connect sigue
 * aceptando las lecturas (su recomendación oficial para lecturas largas).
 * El progreso vive en [progress] (StateFlow) y se refleja en la notificación.
 */
class SyncService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var watchdog: Job? = null

    override fun onCreate() {
        super.onCreate()
        createChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat("Iniciando sincronización…")
        progress.value = SyncStage.Running("Iniciando…")

        // Watchdog: si el sync se cuelga, el servicio termina con error claro.
        watchdog = scope.launch {
            delay(WATCHDOG_MS)
            if (progress.value is SyncStage.Running) {
                progress.value = SyncStage.Failed(
                    "Timeout: la sincronización no terminó en ${WATCHDOG_MS / 60_000} min",
                )
                stopSelf()
            }
        }

        scope.launch {
            try {
                val report = runner(this@SyncService) { stage ->
                    progress.value = SyncStage.Running(stage)
                    notify("Sincronizando… $stage")
                }
                progress.value = SyncStage.Done(report)
                notify(summaryOf(report))
            } catch (e: Exception) {
                progress.value = SyncStage.Failed(e.message ?: e.javaClass.simpleName)
                notify("Error: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                watchdog?.cancel()
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startForegroundCompat(text: String) {
        val notification = buildNotification(this, text)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun notify(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(this, text))
    }

    companion object {
        const val CHANNEL_ID = "health_sync_progress"
        const val NOTIFICATION_ID = 1
        const val WATCHDOG_MS = 5 * 60 * 1000L

        /** runner inyectable en tests; firma idéntica a SyncExecutor.run. */
        @Volatile
        var runner: suspend (Context, (String) -> Unit) -> SyncReport = { ctx, onProgress ->
            SyncExecutor.run(ctx, onProgress)
        }

        /** Progreso observable: la UI lo colecta para el panel. */
        val progress: MutableStateFlow<SyncStage> = MutableStateFlow(SyncStage.Idle)

        /** Arranca el servicio si no hay ya un sync en marcha. */
        fun start(context: Context) {
            if (progress.value is SyncStage.Running) return
            context.startForegroundService(Intent(context, SyncService::class.java))
        }

        fun createChannel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Progreso de sincronización", NotificationManager.IMPORTANCE_LOW),
            )
        }

        fun buildNotification(context: Context, text: String): Notification =
            NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("HealthSync")
                .setContentText(text)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .build()

        fun summaryOf(report: SyncReport): String = buildString {
            append("Tipos leídos: ${report.typesSynced} | Entregados: ${report.delivered}")
            if (report.failed > 0) append(" | Fallos: ${report.failed}")
            report.notice?.let { append(" | Aviso: $it") }
            report.permanentError?.let { append(" | Error: $it") }
        }
    }
}
