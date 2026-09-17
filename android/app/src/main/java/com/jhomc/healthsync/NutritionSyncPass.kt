package com.jhomc.healthsync

import com.jhomc.healthsync.data.NutritionPublishDao

/**
 * Pase de publicación nutricional dentro del pipeline de sincronización
 * ("Sincronizar AHORA" y worker periódico).
 *
 * Motivación: el diario móvil no tiene vista de alimentación cableada en la
 * Activity, así que lo guardado en la web nunca pasaba por el ViewModel que
 * publica. Este pase hace que el sync empuje a Health Connect todos los días
 * con datos del servidor que aún no estén publicados (reconciliación por
 * hash: lo ya publicado es no-op, sin duplicar).
 *
 * Reglas:
 * - Solo días con `hasData == true` se publican. Un día vacío/prefill nunca
 *   se publica (el prefill heredaría el día anterior duplicándolo); en ese
 *   caso se borra lo que hubiera publicado de esa fecha (huérfanos).
 * - Tope [MAX_DAYS_PER_RUN] (recientes primero): acota llamadas HC/red por
 *   ejecución (1 fechas + 1 GET por día, timeouts cortos LAN); el resto sale
 *   en el siguiente sync.
 * - Días con escritura móvil pendiente de drenar (`pendingFechas`) se saltan
 *   ese run: el drenado pisa el servidor después y el siguiente sync publica
 *   ya reconciliado (evita publicar y que el drenado lo pise).
 * - Sin permiso WRITE → skip global `sin_permiso` (sin tocar HC ni Room).
 * - Sin red o fechas ilegibles → skip `sin_red` (reintenta el próximo sync).
 * - Nunca lanza: fallos de lectura de un día se saltan; fallos de escritura
 *   cuentan en `failed` sin tumbar el resto.
 */
object NutritionSyncPass {

    const val MAX_DAYS_PER_RUN = 10

    data class PassReport(
        val published: Int = 0,
        val deleted: Int = 0,
        val failed: Int = 0,
        val skippedReason: String? = null,
    )

    suspend fun run(
        apiBase: String,
        token: String,
        training: TrainingApiClient = TrainingApiClient(),
        gateway: HealthConnectGateway,
        publishDao: NutritionPublishDao,
        manager: HealthConnectManager,
        pendingFechas: Set<String> = emptySet(),
    ): PassReport {
        val granted = runCatching { gateway.grantedPermissions() }.getOrNull()
            ?: return PassReport(skippedReason = "hc_error")
        if (!granted.contains(manager.nutritionWritePermission())) {
            return PassReport(skippedReason = "sin_permiso")
        }
        val fechas = when (val r = training.getFechas(apiBase, token, "alimentacion")) {
            is TrainingResult.Ok -> r.value
            else -> return PassReport(skippedReason = "sin_red")
        }
        val publisher = NutritionPublisher(gateway, publishDao, manager)
        var published = 0
        var deleted = 0
        var failed = 0
        for (fecha in fechas.sortedDescending().take(MAX_DAYS_PER_RUN)) {
            if (fecha in pendingFechas) continue
            val day = when (val d = training.getNutritionDay(apiBase, token, fecha)) {
                is TrainingResult.Ok -> d.value
                else -> continue
            }
            if (!day.hasData) {
                when (publisher.deleteDay(fecha)) {
                    is NutritionPublisher.Outcome.Published -> deleted++
                    is NutritionPublisher.Outcome.Skipped -> {}
                    is NutritionPublisher.Outcome.Failed -> failed++
                }
            } else {
                when (val o = publisher.publishDay(day)) {
                    is NutritionPublisher.Outcome.Published -> published += o.inserted
                    is NutritionPublisher.Outcome.Skipped -> {}
                    is NutritionPublisher.Outcome.Failed -> failed++
                }
            }
        }
        return PassReport(published, deleted, failed, null)
    }
}
