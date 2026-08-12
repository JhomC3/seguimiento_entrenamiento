package com.jhomc.healthsync

import java.time.Instant
import java.time.ZoneId

/**
 * Agenda de sincronización por VENTANAS DIARIAS fijas (pura, sin I/O):
 *
 *  - Mañana (9:00): sueño, FC en reposo y composición corporal — datos que
 *    solo existen al despertar o se miden por la mañana.
 *  - Mediodía (13:00) y tarde (19:00): sesiones de ejercicio y calorías —
 *    frescura del entreno sin despertadas continuas.
 *  - Tarde (19:00): pasos, HR (tramos de 5 min) y el resto.
 *
 * El worker despierta cada hora pero solo sincroniza tipos vencidos: la
 * mayoría de las horas NO hace llamadas. El botón directo fuerza todo.
 */
object HealthSyncPlanner {

    /** Ventanas por tipo: horas del día (0-23) en que se sincroniza. */
    fun windowHours(typeName: String): Set<Int> = when (typeName) {
        "SLEEP_SESSION",
        "RESTING_HEART_RATE",
        "WEIGHT",
        "HEIGHT",
        "BODY_FAT",
        "BONE_MASS",
        "BODY_WATER_MASS",
        "LEAN_BODY_MASS",
        -> setOf(9)
        "EXERCISE_SESSION",
        "ACTIVE_CALORIES_BURNED",
        "TOTAL_CALORIES_BURNED",
        -> setOf(13, 19)
        else -> setOf(19) // STEPS, HEART_RATE y el resto
    }

    /** Primera ventana del día para ordenar candidatos. */
    fun nextWindowHour(typeName: String): Int = windowHours(typeName).min()

    /**
     * Próxima ocurrencia de la ventana del tipo después de [nowMs]
     * (la hora actual no cuenta: evita re-sync inmediato).
     */
    fun nextDueMs(typeName: String, nowMs: Long, zoneId: ZoneId): Long {
        val now = Instant.ofEpochMilli(nowMs).atZone(zoneId)
        val hours = windowHours(typeName).sorted()
        for (hour in hours) {
            val candidate = now.toLocalDate().atTime(hour, 0).atZone(zoneId).toInstant().toEpochMilli()
            if (candidate > nowMs) return candidate
        }
        return now.toLocalDate().plusDays(1)
            .atTime(hours.first(), 0)
            .atZone(zoneId)
            .toInstant()
            .toEpochMilli()
    }
}
