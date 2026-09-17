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
    val quarantined: Int = 0,
    val quarantineSample: String? = null,
    val nutritionPublished: Int = 0,
    val nutritionFailed: Int = 0,
)

/**
 * Single sync pipeline shared by the WorkManager worker (background) and the
 * UI "sync now" button (foreground). Never throws for expected outcomes; the
 * worker decides retry/failure policy from the report.
 */
object SyncExecutor {

    suspend fun run(context: Context, onProgress: (String) -> Unit = {}, force: Boolean = false): SyncReport {
        val appContext = context.applicationContext
        val gateway = RealHealthConnectGateway(appContext)
        if (HealthConnectClient.getSdkStatus(appContext) != HealthConnectClient.SDK_AVAILABLE) {
            return SyncReport(0, 0, 0, notice = "health_connect_no_disponible")
        }
        val db = HealthDatabaseBuilder.get(appContext)
        val repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), Instant::now, onProgress = onProgress)
        val store = SecureTargetStore(appContext)
        val client = HealthSyncClient()

        val granted = gateway.grantedPermissions()
        if (granted.isEmpty()) {
            return SyncReport(0, 0, 0, notice = "sin_permisos")
        }
        val sourceResults = try {
            repo.syncAuthorizedTypes(force = force)
        } catch (e: RateLimitedException) {
            return SyncReport(0, 0, 0, notice = "rate_limited")
        } catch (e: ForegroundRequiredException) {
            return SyncReport(0, 0, 0, notice = "foreground_requerido")
        } catch (e: HcReadTimeoutException) {
            return SyncReport(0, 0, 0, notice = "timeout_lectura")
        }

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
        // Nutrición → Health Connect: lo guardado en la web nunca pasa por el
        // diario móvil, así que el sync empuja los días con datos aún no
        // publicados (reconciliación por hash; lo publicado es no-op).
        val nutrition = runCatching {
            val apiBase = TrainingApiClient.apiBaseFor(target.url, BuildConfig.DEFAULT_API_BASE)
                ?: return@runCatching null
            onProgress("Nutrición…")
            val pendingDiario = db.offlineDao().pendingAll()
                .filter { it.domain == "diario" }
                .map { it.fecha }
                .toSet()
            NutritionSyncPass.run(
                apiBase = apiBase,
                token = token,
                gateway = gateway,
                publishDao = db.nutritionPublishDao(),
                manager = HealthConnectManager(gateway),
                pendingFechas = pendingDiario,
            )
        }.getOrNull()
        return SyncReport(
            typesSynced = sourceResults.size,
            delivered = upload.delivered,
            failed = upload.failed,
            permanentError = upload.permanentError,
            quarantined = upload.quarantined,
            quarantineSample = upload.quarantineSample,
            nutritionPublished = nutrition?.published ?: 0,
            nutritionFailed = nutrition?.failed ?: 0,
        )
    }
}
