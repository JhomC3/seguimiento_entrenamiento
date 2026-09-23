package com.jhomc.healthsync

import androidx.health.connect.client.records.MindfulnessSessionRecord
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.feature.ExperimentalMindfulnessSessionApi
import java.time.Instant
import java.time.ZoneId

/**
 * Escribe sesiones de respiración COMPLETADAS como meditaciones en Health
 * Connect (solo escritura; el servidor ya tiene la sesión vía API, esto es
 * el espejo para el ecosistema). Idempotente por `clientRecordId` (el UUID
 * de la sesión): reintentar no duplica. Sin permiso o sin HC, se omite con
 * log; nunca bloquea el guardado.
 */
@OptIn(ExperimentalMindfulnessSessionApi::class)
class MindfulnessWriter(
    private val gateway: HealthConnectGateway,
    private val manager: HealthConnectManager? = null,
) {

    sealed interface Outcome {
        data object Published : Outcome
        data class Skipped(val reason: String) : Outcome
        data class Failed(val detail: String) : Outcome
    }

    suspend fun write(finished: FinishedBreathing, ciclos: Int, minutos: Double): Outcome {
        if (!finished.completed) return Outcome.Skipped("parcial")
        if (!hasWritePermission()) return Outcome.Skipped("sin_permiso")
        val record = recordFor(finished, ciclos, minutos) ?: return Outcome.Failed("ventana_invalida")
        return runCatching {
            gateway.insertMindfulness(listOf(record))
            Outcome.Published
        }.getOrElse { Outcome.Failed(it.message ?: "insert") }
    }

    fun recordFor(finished: FinishedBreathing, ciclos: Int, minutos: Double): MindfulnessSessionRecord? {
        val start = Instant.ofEpochMilli(finished.startMs)
        val end = Instant.ofEpochMilli(finished.endMs)
        if (!start.isBefore(end)) return null
        val zone = ZoneId.systemDefault()
        val p = finished.pattern
        val notes = "${trim(p.inhaleS)}/${trim(p.holdInS)}/${trim(p.exhaleS)}/${trim(p.holdOutS)}s" +
            " · $ciclos ciclos · ${"%.1f".format(minutos)} min"
        return MindfulnessSessionRecord(
            mindfulnessSessionType = MindfulnessSessionRecord.MINDFULNESS_SESSION_TYPE_BREATHING,
            startTime = start,
            startZoneOffset = zone.rules.getOffset(start),
            endTime = end,
            endZoneOffset = zone.rules.getOffset(end),
            title = "Respiración",
            notes = notes,
            metadata = Metadata.manualEntry(finished.clientSessionId, 1),
        )
    }

    private fun trim(v: Double): String = if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()

    private suspend fun hasWritePermission(): Boolean {
        val mgr = manager ?: return true
        return runCatching {
            gateway.grantedPermissions().contains(mgr.mindfulnessWritePermission())
        }.getOrDefault(false)
    }
}
