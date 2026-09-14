package com.jhomc.healthsync

/**
 * Máquina pura del cronómetro libre (sin Android ni Room).
 *
 * Invariante explícita: un solo cronómetro corriendo. [start] cierra
 * automáticamente cualquier intervalo abierto de otra serie antes de abrir
 * el nuevo (evita "dos descansos simultáneos" en la futura curva de FC).
 *
 * Reloj dual: el llamante aporta wall (join con HC) y elapsed (duración).
 * Esta clase solo calcula; la persistencia la hace el ViewModel en Room.
 */
class RestTimer {
    data class Running(
        val intervalId: Long,
        val uuid: String,
        val startWall: Long,
        val startElapsed: Long,
    )

    /** uuid -> ms acumulados de intervalos CERRADOS. */
    private val accum = mutableMapOf<String, Long>()

    var running: Running? = null
        private set

    /** Lo que debe cerrar el llamante antes de abrir lo nuevo (o null). */
    data class ToClose(val intervalId: Long, val uuid: String, val startElapsed: Long)

    fun pendingClose(): ToClose? = running?.let { ToClose(it.intervalId, it.uuid, it.startElapsed) }

    fun onOpened(intervalId: Long, uuid: String, startWall: Long, startElapsed: Long) {
        running = Running(intervalId, uuid, startWall, startElapsed)
    }

    /**
     * Cierra el running actual. Devuelve (uuid, duración del intervalo) o null
     * si no había nada corriendo. Acumula la duración cerrada.
     */
    fun onClosed(endElapsed: Long): Pair<String, Long>? {
        val r = running ?: return null
        val dur = (endElapsed - r.startElapsed).coerceAtLeast(0)
        accum[r.uuid] = (accum[r.uuid] ?: 0L) + dur
        running = null
        return r.uuid to dur
    }

    fun seedAccum(uuid: String, ms: Long) {
        accum[uuid] = (accum[uuid] ?: 0L) + ms
    }

    /**
     * Descarta el running de [uuid] sin acumular (reset 3 s): el intervalo ya
     * quedó ABANDONADO en Room y lo contado se olvida. Devuelve true si era él.
     */
    fun abandonRunning(uuid: String): Boolean {
        if (running?.uuid != uuid) return false
        running = null
        accum.remove(uuid)
        return true
    }

    /** Olvida lo acumulado de [uuid] (reset o arranque fresco desde 0). */
    fun clearAccumFor(uuid: String) {
        accum.remove(uuid)
    }

    /** Reinicio total del día: suelta el running y olvida todo lo contado. */
    fun resetAll() {
        running = null
        accum.clear()
    }

    fun clearAccum(uuids: Set<String>) {
        accum.keys.retainAll(uuids)
        if (running?.uuid !in uuids) running = null
    }

    /** Ms a pintar para [uuid] en [nowElapsed] (acumulado + tramo en curso). */
    fun elapsedFor(uuid: String, nowElapsed: Long): Long {
        val base = accum[uuid] ?: 0L
        val r = running
        return if (r != null && r.uuid == uuid) base + (nowElapsed - r.startElapsed).coerceAtLeast(0) else base
    }

    fun isRunning(uuid: String): Boolean = running?.uuid == uuid

    fun runningUuid(): String? = running?.uuid

    /** Id del intervalo en curso (cursor del piip; null sin running). */
    fun runningIntervalId(): Long? = running?.intervalId
}
