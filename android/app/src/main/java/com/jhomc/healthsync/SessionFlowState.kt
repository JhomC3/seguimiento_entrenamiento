package com.jhomc.healthsync

import java.util.UUID

/**
 * Máquina pura del modo entreno (sin Android, testeable con JUnit puro).
 *
 * - Agrupa borradores por ejercicio preservando orden de primera aparición.
 * - Cada fila tiene un client_set_uuid estable en memoria (nunca viaja al
 *   servidor; solo correlación local con rest_intervals).
 * - Un solo expandido a la vez; doneSets reversible (segundo tap desmarca).
 * - Sin pager en Fase 1: lista agrupada con scroll (menos taps).
 */
data class EntrenoItem(
    val uuid: String,
    val ejercicio: String,
    val kg: String,
    val reps: String,
    val rir: String,
    val velocidadKmh: String = "",
    val dificultad: String = "",
    /** Orden aparente 1..N (informativo; el servidor reasigna set_orden). */
    val aparenteOrden: Int = 0,
) {
    fun isHiit(): Boolean = ejercicio.trim().equals("HIIT", ignoreCase = true)

    fun summaryLine(timerText: String, done: Boolean): String {
        val mark = if (done) "✓" else timerText
        return if (isHiit()) {
            val vel = velocidadKmh.ifBlank { "–" }
            val dif = dificultad.ifBlank { "–" }
            "Serie $aparenteOrden · HIIT ${vel}x$dif · $mark"
        } else {
            val kgT = kg.ifBlank { "–" }
            val repsT = reps.ifBlank { "–" }
            val rirT = rir.ifBlank { "–" }
            "Serie $aparenteOrden · ${kgT}x$repsT · RIR $rirT · $mark"
        }
    }
}

data class EntrenoGroup(
    val ejercicio: String,
    val items: List<EntrenoItem>,
)

object SessionFlowState {
    /**
     * Construye grupos desde borradores. [uuidsByIndex] alinea UUIDs con la
     * posición del borrador; los huecos se generan nuevos. Las filas en
     * blanco se ocultan en entreno (no se puede entrenar un vacío).
     */
    fun build(
        drafts: List<TrainingSetDraft>,
        uuidsByIndex: List<String?> = emptyList(),
    ): Pair<List<EntrenoGroup>, List<String>> {
        val outUuids = mutableListOf<String>()
        val visible = mutableListOf<Triple<Int, TrainingSetDraft, String>>()
        var orden = 0
        drafts.forEachIndexed { index, d ->
            val existing = uuidsByIndex.getOrNull(index)
            val uuid = existing ?: UUID.randomUUID().toString()
            outUuids += uuid
            if (!d.isBlank()) {
                orden++
                visible += Triple(orden, d, uuid)
            }
        }
        val groups = visible.groupBy({ it.second.ejercicio.trim() }, { it })
            .entries.map { (ejercicio, rows) ->
                EntrenoGroup(
                    ejercicio = ejercicio.ifBlank { "(sin nombre)" },
                    items = rows.map { (aparente, d, uuid) ->
                        EntrenoItem(
                            uuid = uuid,
                            ejercicio = d.ejercicio,
                            kg = d.kg,
                            reps = d.reps,
                            rir = d.rir,
                            velocidadKmh = d.velocidadKmh,
                            dificultad = d.dificultad,
                            aparenteOrden = aparente,
                        )
                    },
                )
            }
        return groups to outUuids
    }

    fun flattened(groups: List<EntrenoGroup>): List<EntrenoItem> = groups.flatMap { it.items }

    /** Siguiente pendiente tras [uuid] (o primera pendiente si es null). */
    fun nextPending(
        groups: List<EntrenoGroup>,
        done: Set<String>,
        uuid: String?,
    ): EntrenoItem? {
        val flat = flattened(groups)
        if (flat.isEmpty()) return null
        val start = if (uuid == null) 0 else {
            val i = flat.indexOfFirst { it.uuid == uuid }
            if (i < 0) 0 else i + 1
        }
        for (i in start until flat.size) if (flat[i].uuid !in done) return flat[i]
        for (i in 0 until start.coerceAtMost(flat.size)) if (flat[i].uuid !in done) return flat[i]
        return null
    }

    fun progress(groups: List<EntrenoGroup>, done: Set<String>): Triple<Int, Int, Int> {
        val flat = flattened(groups)
        val total = flat.size
        val doneCount = flat.count { it.uuid in done }
        return Triple(total, doneCount, total - doneCount)
    }

    fun toggleDone(done: Set<String>, uuid: String): Set<String> =
        if (uuid in done) done - uuid else done + uuid

    /** Apertura múltiple: alterna solo la suya, las demás intactas. */
    fun toggleExpanded(expanded: Set<String>, uuid: String): Set<String> =
        if (uuid in expanded) expanded - uuid else expanded + uuid

    /**
     * Borradores desde la sesión del servidor (misma conversión que el editor
     * clásico). Preserva TODOS los campos incluido descanso_seg oculto.
     */
    fun draftsFromSession(sets: List<TrainingSet>): List<TrainingSetDraft> =
        sets.map {
            TrainingSetDraft(
                it.ejercicio, numText(it.kg), numText(it.reps), numText(it.rir),
                numText(it.descansoSeg), numText(it.velocidadKmh), numText(it.dificultad),
            )
        }

    private fun numText(v: Double?): String {
        if (v == null) return ""
        return if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()
    }
}
