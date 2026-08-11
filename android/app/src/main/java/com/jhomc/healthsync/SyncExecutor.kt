package com.jhomc.healthsync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.SecureTargetStore
import java.time.Instant

data class SyncReport(
    val typesSynced: Int,
    val delivered: Int,
    val failed: Int,
    val permanentError: String? = null,
    val notice: String? = null,
)

/**
 * Single sync pipeline shared by the WorkManager worker (background) and the
 * UI "sync now" button (foreground). Never throws for expected outcomes; the
 * worker decides retry/failure policy from the report.
 */
object SyncExecutor {

    suspend fun run(context: Context): SyncReport {
        val appContext = context.applicationContext
        val gateway = RealHealthConnectGateway(appContext)
        if (HealthConnectClient.getSdkStatus(appContext) != HealthConnectClient.SDK_AVAILABLE) {
            return SyncReport(0, 0, 0, notice = "health_connect_no_disponible")
        }
        val db = HealthDatabaseBuilder.get(appContext)
        val repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), Instant::now)
        val store = SecureTargetStore(appContext)
        val client = HealthSyncClient()

        val granted = gateway.grantedPermissions()
        if (granted.isEmpty()) {
            return SyncReport(0, 0, 0, notice = "sin_permisos")
        }
        val sourceResults = repo.syncAuthorizedTypes()

        val target = store.target()
        if (target == null) {
            return SyncReport(sourceResults.size, 0, 0, notice = "sin_destino")
        }
        val token = store.token()
        if (token == null) {
            return SyncReport(sourceResults.size, 0, 0, notice = "sin_token_guardado")
        }
        if (client.validateTargetUrl(target.url, allowHttp = true).isFailure) {
            return SyncReport(sourceResults.size, 0, 0, notice = "url_invalida: ${target.url}")
        }
        val targetRow = repo.ensureTarget(target.url, target.name)
        val upload = repo.uploadPending(client, targetRow, token, store.deviceId())
        return SyncReport(
            typesSynced = sourceResults.size,
            delivered = upload.delivered,
            failed = upload.failed,
            permanentError = upload.permanentError,
        )
    }
}
