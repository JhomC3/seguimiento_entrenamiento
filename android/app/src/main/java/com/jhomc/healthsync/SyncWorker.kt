package com.jhomc.healthsync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.work.CoroutineWorker
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
 */
class SyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val context = applicationContext
        val gateway = RealHealthConnectGateway(context)
        if (HealthConnectClient.getSdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) {
            return@withContext Result.failure() // no Health Connect on this device
        }
        val db = HealthDatabaseBuilder.get(context)
        val repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), Instant::now)
        val store = SecureTargetStore(context)
        val client = HealthSyncClient()
        try {
            // 1) Source: authorized types only; revoked types never block.
            val granted = gateway.grantedPermissions()
            if (granted.isEmpty()) {
                return@withContext Result.failure() // user must grant from the app
            }
            repo.syncAuthorizedTypes()

            // 2) Delivery: only if a target is configured.
            val target = store.target()
            val token = store.token()
            if (target != null && token != null) {
                if (client.validateTargetUrl(target.url).isFailure) {
                    return@withContext Result.failure() // permanent config error
                }
                val targetRow = repo.ensureTarget(target.url, target.name)
                repo.uploadPending(client, targetRow, token, store.deviceId())
            }
            Result.success()
        } catch (e: SecurityException) {
            Result.failure() // permissions revoked mid-run
        } catch (e: IOException) {
            Result.retry()
        } catch (e: Exception) {
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }
}
