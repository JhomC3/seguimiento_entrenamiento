package com.jhomc.healthsync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.WorkerParameters
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * WorkManager wrapper around [SyncExecutor] (the same pipeline the UI button
 * runs). Every exit path carries diagnostic output data so the UI can explain
 * what happened without USB debugging.
 */
class SyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val report = SyncExecutor.run(applicationContext)
            if (report.notice != null) {
                when (report.notice) {
                    // Rate limit: retry later via WorkManager backoff (30 min
                    // exponential), never hammer the provider.
                    "rate_limited" -> Result.retry()
                    "sin_permisos", "health_connect_no_disponible" ->
                        Result.failure(Data.Builder().putString("reason", report.notice).build())
                    else ->
                        Result.success(
                            Data.Builder()
                                .putInt("types_synced", report.typesSynced)
                                .putString("notice", report.notice)
                                .build(),
                        )
                }
            } else {
                Result.success(
                    Data.Builder()
                        .putInt("types_synced", report.typesSynced)
                        .putInt("delivered", report.delivered)
                        .putInt("failed", report.failed)
                        .putString("permanent_error", report.permanentError ?: "")
                        .build(),
                )
            }
        } catch (e: SecurityException) {
            Result.failure(Data.Builder().putString("reason", "permisos_revocados").build())
        } catch (e: IOException) {
            Result.retry()
        } catch (e: Exception) {
            if (runAttemptCount < 3) {
                Result.retry()
            } else {
                Result.failure(
                    Data.Builder()
                        .putString("reason", "${e::class.simpleName}: ${e.message}")
                        .build(),
                )
            }
        }
    }
}
