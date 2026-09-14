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

    /** Apertura múltiple: alterna solo la suya, las demás intactas. */
    fun toggleExpanded(expanded: Set<String>, uuid: String): Set<String> =
        if (uuid in expanded) expanded - uuid else expanded + uuid

    /**
     * Descanso medido en segundos con 1 decimal (mismo redondeo que RIR 0.1:
     * el binario acumula error sin esto). 95440 ms → 95.4.
     */
    fun descansoSecsFor(elapsedMs: Long): Double =
        (kotlin.math.round(elapsedMs / 100.0) / 10.0).coerceAtLeast(0.0)

    fun descansoText(v: Double?): String {
        if (v == null) return "–"
        return if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()
    }

    /**
     * Marcas de piip cruzadas en (lastMs, nowMs]: cada marca suena una vez
     * por descanso. Puro y testeable; el llamante guarda el cursor por
     * intervalo (nuevo intervalo = cursor fresco, sin refires).
     */
    fun crossedThresholds(lastMs: Long, nowMs: Long, marksSec: List<Long>): List<Long> {
        if (nowMs <= lastMs) return emptyList()
        return marksSec.filter { m -> lastMs < m * 1000 && m * 1000 <= nowMs }
    }

    /**
     * Pausa persistente derivada (sin migración): una serie pendiente con
     * intervalos CERRADOS y sin running estaba pausada al morir el proceso
     * (pausar cierra; guardar marca done; reset abandona, no cierra). Al
     * reabrir el día, el tap cae en Resume y continúa desde el acumulado
     * en vez de arrancar de cero.
     */
    fun derivePaused(
        closedUuids: Collection<String>,
        done: Set<String>,
        running: String?,
        validIds: Collection<String>,
    ): Set<String> =
        closedUuids.toSet() - done - setOfNotNull(running) intersect validIds.toSet()

    /**
     * Máquina pura del flujo por serie: pendiente → en trabajo (Ir) →
     * guardada (check). Sin Android ni Room. El ViewModel la posee para
     * transiciones; solo cablea Room/reloj/red alrededor.
     *
     * El descanso pertenece a la SERIE SIGUIENTE: al guardar N se abre el
     * descanso a nombre de N+1 (su dial late visible) y al guardar N+1 se
     * cierra y se anota en N+1. La primera serie nunca tiene descanso previo.
     */
    object WorkoutFlow {
        /** Guardar: colapsa esta, abre la siguiente y arranca su descanso. */
        data class GuardarEffect(
            val saved: String,
            val nextToExpand: String?,
            val startRest: Boolean,
        )

        fun guardar(
            uuid: String,
            done: Set<String>,
            groups: List<EntrenoGroup>,
        ): GuardarEffect {
            val next = nextPending(groups, done + uuid, uuid)
            // Última serie: no se arranca descanso (post-entreno sin sentido).
            return GuardarEffect(saved = uuid, nextToExpand = next?.uuid, startRest = next != null)
        }

        /**
         * Decisión pura del tap en el dial (play/pausa/start). Semántica de
         * cronómetro: el tramo pausado se EXCLUYE del descanso anotado (cada
         * cierre anota a su dueño; reanudar acumula encima).
         * - `Pause`: corre [uuid] → cerrarlo (se anota) y marcarlo pausado.
         * - `Resume`: [uuid] pausado → abrirle tramo nuevo; si corre otro
         *   ([closeOther]), cerrarlo primero (también se anota a su dueño).
         * - `Start`: [uuid] pendiente en reposo sin nadie corriendo → abrirle
         *   su descanso (así un cronómetro reseteado vuelve a andar con tap).
         * - `Nothing`: serie hecha o corre otra (jamás tumbar timer ajeno).
         */
        sealed interface DialTapDecision {
            data object Nothing : DialTapDecision
            data class Pause(val uuid: String) : DialTapDecision
            data class Resume(val uuid: String, val closeOther: String?) : DialTapDecision
            data class Start(val uuid: String) : DialTapDecision
        }

        fun resolveDialTap(
            runningOwner: String?,
            paused: Set<String>,
            uuid: String,
            isDone: Boolean,
        ): DialTapDecision = when {
            runningOwner == uuid -> DialTapDecision.Pause(uuid)
            uuid in paused -> DialTapDecision.Resume(uuid, closeOther = runningOwner)
            runningOwner == null && !isDone -> DialTapDecision.Start(uuid)
            else -> DialTapDecision.Nothing
        }
    }

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
