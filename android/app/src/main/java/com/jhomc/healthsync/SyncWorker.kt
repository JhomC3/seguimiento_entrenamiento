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
                    // Rate limit: succeed (no retry). Retrying from background
                    // keeps the provider's quota exhausted, since the
                    // background limit is stricter than foreground. Next run
                    // happens on the next schedule/manual trigger.
                    "rate_limited" -> Result.success(
                        Data.Builder()
                            .putString("reason", "rate_limited")
                            .build(),
                    )
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
                        .putInt("quarantined", report.quarantined)
                        .putString("quarantine_sample", report.quarantineSample ?: "")
                        .putString("permanent_error", report.permanentError ?: "")
                        .build(),
                )
            }
        } catch (e: RateLimitedException) {
            // Defensive: the executor normally converts this to a notice;
            // if it ever escapes, do NOT retry (see above).
            Result.success(Data.Builder().putString("reason", "rate_limited").build())
        } catch (e: ForegroundRequiredException) {
            // Not retryable: only the user can change it (foreground or
            // background read access). Retrying would burn quota for nothing.
            Result.success(Data.Builder().putString("reason", "foreground_requerido").build())
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
