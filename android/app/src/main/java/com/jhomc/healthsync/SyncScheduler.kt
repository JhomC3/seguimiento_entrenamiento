package com.jhomc.healthsync

import android.content.Context
import androidx.room.Room
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_1_2
import com.jhomc.healthsync.data.MIGRATION_2_3
import com.jhomc.healthsync.data.MIGRATION_3_4
import com.jhomc.healthsync.data.MIGRATION_4_5
import com.jhomc.healthsync.data.MIGRATION_5_6
import com.jhomc.healthsync.data.MIGRATION_6_7
import com.jhomc.healthsync.data.MIGRATION_7_8
import com.jhomc.healthsync.data.MIGRATION_8_9
import java.util.concurrent.TimeUnit

/** WorkManager scheduling only; no business logic lives here. */
object SyncScheduler {

    private const val UNIQUE_WORK = "health_connect_sync"

    fun schedulePeriodic(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .setRequiresBatteryNotLow(true)
            .build()
        val request = PeriodicWorkRequestBuilder<SyncWorker>(1, TimeUnit.HOURS, 15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            UNIQUE_WORK,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    /** Manual "sync now": expedited one-time work, falling back gracefully. */
    fun syncNow(context: Context) {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "health_connect_sync_now",
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    /**
     * Cancel both periodic and one-time sync work. Used at app startup while
     * the Health Connect quota investigation is open: a worker running in
     * background (retries or hourly schedule) can keep the quota exhausted,
     * since the provider's background limit is stricter than foreground.
     * With workers cancelled, sync is exclusively manual ("sync now" button).
     */
    fun cancelAll(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(UNIQUE_WORK)
        WorkManager.getInstance(context).cancelUniqueWork("health_connect_sync_now")
    }
}

/** Single Room instance per process (WorkManager may run without the UI). */
object HealthDatabaseBuilder {
    @Volatile
    private var instance: HealthDatabase? = null

    fun get(context: Context): HealthDatabase =
        instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                HealthDatabase::class.java,
                "health_sync.db",
            ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6, MIGRATION_6_7, MIGRATION_7_8, MIGRATION_8_9).build().also { instance = it }
        }
}
