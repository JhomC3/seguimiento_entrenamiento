package com.jhomc.healthsync

import com.jhomc.healthsync.data.BreathingDao
import com.jhomc.healthsync.data.BreathingPendingEntity
import com.jhomc.healthsync.data.BreathingSessionEntity
import org.json.JSONObject
import java.util.TimeZone
import java.util.UUID

/**
 * Respiración B5.0: presets locales + historial local + entrega idempotente.
 *
 * - Terminar una sesión la guarda en Room y la encola (una op por
 *   `client_session_id`, lo último gana, como `health_outbox`).
 * - [drain] entrega la cola en orden: `ApiError` (400/401/404/409/413)
 *   descarta la op (permanente), `NetworkError`/5xx la conserva.
 * - El servidor recalcula ciclos/BPM/fecha; aquí solo viaja el patrón.
 */
class BreathingRepository(
    private val dao: BreathingDao,
    private val client: TrainingApiClient = TrainingApiClient(),
    private val nowMs: () -> Long = { System.currentTimeMillis() },
    private val tzOffsetMin: () -> Int = { TimeZone.getDefault().getOffset(nowMs()) / 60000 },
) {

    suspend fun history(fecha: String): List<BreathingSessionEntity> = dao.sessionsFor(fecha)

    /**
     * Guarda la sesión terminada en local + cola. null si no completa ni un
     * ciclo (misma regla que el servidor: lo condenado no se encola).
     */
    suspend fun finishSession(finished: FinishedBreathing): String? {
        val id = finished.clientSessionId.ifBlank { UUID.randomUUID().toString() }
        // Mismos inputs y fórmula que el servidor (round(ms/1000) + simulate):
        // la estimación local coincide con lo que devolverá la API.
        val realS = secsFromMs(finished.endMs - finished.startMs).toInt().coerceAtLeast(1)
        val engine = BreathingEngine(finished.pattern)
        val (cycles, estimatedBpm) = engine.simulate(realS)
        if (cycles < 1) return null
        dao.putSession(
            BreathingSessionEntity(
                clientSessionId = id,
                fecha = localFecha(finished.startMs),
                startMs = finished.startMs,
                endMs = finished.endMs,
                tzOffsetMin = finished.tzOffsetMin,
                plannedS = finished.plannedS,
                realS = realS,
                patternJson = finished.pattern.toJson().toString(),
                ciclos = cycles,
                bpm = estimatedBpm,
                completada = finished.completed,
                delivered = false,
                createdAtMs = nowMs(),
            ),
        )
        dao.enqueue(
            BreathingPendingEntity(
                clientSessionId = id,
                op = "SAVE",
                payloadJson = savePayload(
                    id, finished.startMs, finished.endMs, finished.tzOffsetMin,
                    finished.plannedS, finished.pattern, finished.completed,
                ).toString(),
                createdAtMs = nowMs(),
            ),
        )
        return id
    }

    /** Borra en local y encola el DELETE (idempotente en servidor). */
    suspend fun deleteSession(id: String) {
        dao.deleteSession(id)
        dao.enqueue(
            BreathingPendingEntity(
                clientSessionId = id,
                op = "DELETE",
                payloadJson = JSONObject().put("client_session_id", id).toString(),
                createdAtMs = nowMs(),
            ),
        )
    }

    /** Fila local para el espejo HC (null si ya no existe). */
    suspend fun sessionById(id: String): BreathingSessionEntity? = dao.sessionById(id)

    suspend fun pendingCount(): Int = dao.pendingCount()

    /** Resultado del drenado: entregadas, restantes, fallo de red y rechazos del servidor. */
    data class DrainResult(
        val done: Int,
        val rest: Int,
        val fault: String?,
        val rejected: Int,
        val rejectedStatus: Int?,
    )

    /**
     * Drena la cola en orden. Nunca lanza: el fallo de red conserva la op
     * para el próximo drenado; el rechazo del servidor (400/401/404/409/413)
     * la descarta y se cuenta en `rejected` (nunca en silencio).
     */
    suspend fun drain(apiBase: String, token: String): DrainResult {
        var done = 0
        var fault: String? = null
        var rejected = 0
        var rejectedStatus: Int? = null
        for (op in dao.pendingAll()) {
            val delivered = if (op.op == "DELETE") {
                when (val res = client.deleteBreathingSession(apiBase, token, op.clientSessionId)) {
                    is TrainingResult.Ok -> true
                    is TrainingResult.ApiError -> {
                        rejected++
                        rejectedStatus = res.status
                        false
                    }
                    is TrainingResult.NetworkError -> {
                        fault = res.detail
                        return DrainResult(done, dao.pendingCount(), fault, rejected, rejectedStatus)
                    }
                }
            } else {
                when (val saved = client.saveBreathingSession(apiBase, token, JSONObject(op.payloadJson))) {
                    is TrainingResult.Ok -> {
                        runCatching {
                            dao.markDelivered(saved.value.clientSessionId, saved.value.ciclos, saved.value.bpm)
                        }
                        true
                    }
                    is TrainingResult.ApiError -> {
                        rejected++
                        rejectedStatus = saved.status
                        false
                    }
                    is TrainingResult.NetworkError -> {
                        fault = saved.detail
                        return DrainResult(done, dao.pendingCount(), fault, rejected, rejectedStatus)
                    }
                }
            }
            dao.ack(op.clientSessionId)
            if (delivered) done++
        }
        return DrainResult(done, dao.pendingCount(), fault, rejected, rejectedStatus)
    }

    /** Huérfanas: guardadas en local pero sin op en cola (un rechazo las dejó tiradas). */
    suspend fun orphanSessions(): List<BreathingSessionEntity> = dao.orphans()

    /** Re-encola una huérfana reconstruyendo su SAVE. false si ya no existe o está corrupta. */
    suspend fun reenqueue(id: String): Boolean {
        val row = dao.sessionById(id) ?: return false
        val pattern = runCatching {
            BreathingPattern.fromJson(JSONObject(row.patternJson))
        }.getOrNull() ?: return false
        dao.enqueue(
            BreathingPendingEntity(
                clientSessionId = id,
                op = "SAVE",
                payloadJson = savePayload(
                    id, row.startMs, row.endMs, row.tzOffsetMin,
                    row.plannedS, pattern, row.completada,
                ).toString(),
                createdAtMs = nowMs(),
            ),
        )
        return true
    }

    private fun localFecha(startMs: Long): String {
        val tz = TimeZone.getDefault()
        val local = startMs + tz.getOffset(startMs)
        return java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(java.util.Date(local))
    }

    companion object {
        fun savePayload(
            clientSessionId: String,
            startMs: Long,
            endMs: Long,
            tzOffsetMin: Int,
            plannedS: Int?,
            pattern: BreathingPattern,
            completed: Boolean,
        ): JSONObject = JSONObject()
            .put("client_session_id", clientSessionId)
            .put("start_epoch_ms", startMs)
            .put("end_epoch_ms", endMs)
            .put("time_zone_offset_minutes", tzOffsetMin)
            .put("duracion_planeada_sec", plannedS ?: JSONObject.NULL)
            .put("completada", completed)
            .put("patron", pattern.toJson())
    }
}
