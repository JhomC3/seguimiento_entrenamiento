package com.jhomc.healthsync

import com.jhomc.healthsync.data.DraftRow
import com.jhomc.healthsync.data.canonicalRowsHash

/**
 * Confirmación del botón "Guardar entrenamiento" (un solo disparo).
 *
 * El botón no guarda por sí mismo: fuerza el drenado de la cola + recarga.
 * El evento solo nace del resultado real de ese drenado, nunca del tap.
 */
sealed interface SaveEvent {
    /** La sesión del día llegó al servidor (op `sesion` confirmada). */
    data object Synced : SaveEvent

    /** Sin red o sin autorización: la sesión queda en el móvil, en cola. */
    data object LocalOnly : SaveEvent
}

/**
 * Decisión pura: ¿qué confirma el botón tras el drenado?
 *
 * - [requested]: solo el tap en guardar puede emitir (navegar/recargar no).
 * - [reconciled]: la reconciliación soltó lo local (mandó la web) → inhibe:
 *   confirmar "guardada" tras descartar lo del usuario mentiría.
 * - [delivered]: la op `sesion` de la fecha obtuvo Ok del servidor.
 * - Sin entrega pero con op en cola ([sessionPendingAfter] > 0): LocalOnly.
 * - Sin entrega ni cola: no-op o rechazo definitivo del servidor → null
 *   (el refresco posterior ya muestra la verdad del servidor).
 */
fun resolveSaveEvent(
    requested: Boolean,
    delivered: Boolean,
    sessionPendingAfter: Int,
    reconciled: Boolean,
): SaveEvent? {
    if (!requested || reconciled) return null
    if (delivered) return SaveEvent.Synced
    if (sessionPendingAfter > 0) return SaveEvent.LocalOnly
    return null
}

/**
 * ¿Los borradores visibles ya son lo que tiene el servidor?
 *
 * Evita backup+undo redundantes por tap: pulsar guardar sin cambios no
 * reenvía (y vuelve al silencio no-op, ahora sí correcto). Comparación por
 * hash canónico (misma convención que la reconciliación: orden + campos de
 * valor, sin uuid). Sin foto fresca ([freshSets] null) no se puede afirmar:
 * se envía. Comparación exacta de texto: "80.0" tecleado vs 80.0 servido
 * reenvía (idempotente, inofensivo).
 */
fun draftsMatchServer(drafts: List<TrainingSetDraft>, freshSets: List<TrainingSet>?): Boolean {
    if (freshSets == null) return false
    return canonicalRowsHash(drafts.map {
        DraftRow("", it.ejercicio, it.kg, it.reps, it.rir, it.descansoSeg, it.velocidadKmh, it.dificultad)
    }) == canonicalRowsHash(freshSets.map {
        DraftRow("", it.ejercicio, num(it.kg), num(it.reps), num(it.rir), num(it.descansoSeg), num(it.velocidadKmh), num(it.dificultad))
    })
}

private fun num(v: Double?): String {
    if (v == null) return ""
    return if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()
}
