package com.jhomc.healthsync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.WorkerParameters
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.SecureTargetStore
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Orchestrates source sync (Health Connect -> Room) and delivery (Room ->
 * HTTPS target). Delivery never blocks source progress: source tokens advance
 * once Room commits; a down target simply keeps the outbox pending.
 *
 * Every exit path carries diagnostic output data so the UI can explain what
 * happened (no USB debugging needed on the device).
 */
class SyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val context = applicationContext
        val gateway = RealHealthConnectGateway(context)
        if (HealthConnectClient.getSdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) {
            return@withContext Result.failure(
                Data.Builder().putString("reason", "health_connect_no_disponible").build(),
            )
        }
        val db = HealthDatabaseBuilder.get(context)
        val repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), Instant::now)
        val store = SecureTargetStore(context)
        val client = HealthSyncClient()
        try {
            // 1) Source: authorized types only; revoked types never block.
            val granted = gateway.grantedPermissions()
            if (granted.isEmpty()) {
                return@withContext Result.failure(
                    Data.Builder().putString("reason", "sin_permisos").build(),
                )
            }
            val sourceResults = repo.syncAuthorizedTypes()

            // 2) Delivery: only if a target is configured.
            val target = store.target()
            val token = store.token()
            if (target == null || token == null) {
                return@withContext Result.success(
                    Data.Builder()
                        .putInt("types_synced", sourceResults.size)
                        .putString("notice", "sin_destino_configurado").build(),
                )
            }
            if (client.validateTargetUrl(target.url, allowHttp = true).isFailure) {
                return@withContext Result.failure(
                    Data.Builder().putString("reason", "url_invalida: ${target.url}").build(),
                )
            }
            val targetRow = repo.ensureTarget(target.url, target.name)
            val upload = repo.uploadPending(client, targetRow, token, store.deviceId())
            Result.success(
                Data.Builder()
                    .putInt("types_synced", sourceResults.size)
                    .putInt("delivered", upload.delivered)
                    .putInt("failed", upload.failed)
                    .putString("permanent_error", upload.permanentError ?: "")
                    .build(),
            )
        } catch (e: SecurityException) {
            Result.failure(Data.Builder().putString("reason", "permisos_revocados").build())
        } catch (e: IOException) {
            Result.retry(Data.Builder().putString("reason", "red: ${e.message}").build())
        } catch (e: Exception) {
            if (runAttemptCount < 3) {
                Result.retry(Data.Builder().putString("reason", "${e::class.simpleName}: ${e.message}").build())
            } else {
                Result.failure(Data.Builder().putString("reason", "${e::class.simpleName}: ${e.message}").build())
            }
        }
    }
}
