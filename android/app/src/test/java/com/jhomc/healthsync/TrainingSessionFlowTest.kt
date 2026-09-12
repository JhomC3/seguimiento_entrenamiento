package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Fase 1 modo entreno: máquina pura (sin Android ni Room).
 * - Agrupado por ejercicio preservando orden.
 * - Avance/colapso con un solo expandido.
 * - doneSets reversible sin tocar los borradores.
 * - RestTimer: single-running, reloj dual, N intervalos por serie.
 */
class TrainingSessionFlowTest {

    private fun draft(ej: String, kg: String = "80", reps: String = "8", rir: String = "1") =
        TrainingSetDraft(ej, kg, reps, rir, "")

    @Test
    fun `build agrupa por ejercicio y oculta blancos`() {
        val drafts = listOf(
            draft("Press"), draft("Press"), draft("Remo"), TrainingSetDraft("", "", "", "", ""),
        )
        val (groups, uuids) = SessionFlowState.build(drafts)
        assertEquals(4, uuids.size)
        assertEquals(2, groups.size)
        assertEquals("Press", groups[0].ejercicio)
        assertEquals(2, groups[0].items.size)
        assertEquals("Remo", groups[1].ejercicio)
        assertEquals(1, groups[0].items[0].aparenteOrden)
        assertEquals(3, groups[1].items[0].aparenteOrden)
    }

    @Test
    fun `build preserva uuids por indice`() {
        val drafts = listOf(draft("Press"), draft("Remo"))
        val (_, uuids1) = SessionFlowState.build(drafts)
        val (groups2, uuids2) = SessionFlowState.build(drafts, uuids1)
        assertEquals(uuids1, uuids2)
        assertEquals(uuids1[0], groups2[0].items[0].uuid)
    }

    @Test
    fun `nextPending recorre y da la vuelta`() {
        val drafts = listOf(draft("Press"), draft("Press"), draft("Remo"))
        val (groups, _) = SessionFlowState.build(drafts)
        val flat = SessionFlowState.flattened(groups)
        assertEquals(3, flat.size)
        val first = SessionFlowState.nextPending(groups, emptySet(), null)
        assertEquals(flat[0].uuid, first?.uuid)
        val second = SessionFlowState.nextPending(groups, setOf(flat[0].uuid), flat[0].uuid)
        assertEquals(flat[1].uuid, second?.uuid)
        // Todo hecho excepto el primero: da la vuelta.
        val done = setOf(flat[1].uuid, flat[2].uuid)
        assertEquals(flat[0].uuid, SessionFlowState.nextPending(groups, done, flat[2].uuid)?.uuid)
        // Todo hecho: null.
        assertNull(SessionFlowState.nextPending(groups, flat.map { it.uuid }.toSet(), flat[0].uuid))
    }

    @Test
    fun `progress cuadra con guardadas`() {
        val drafts = listOf(draft("Press"), draft("Remo"))
        val (groups, _) = SessionFlowState.build(drafts)
        val flat = SessionFlowState.flattened(groups)
        val done = setOf(flat[0].uuid)
        val (total, doneCount, pending) = SessionFlowState.progress(groups, done)
        assertEquals(2, total)
        assertEquals(1, doneCount)
        assertEquals(1, pending)
    }

    @Test
    fun `ir abre trabajo y guardar avanza sin descanso final`() {
        val drafts = listOf(draft("Press"), draft("Remo"))
        val (groups, _) = SessionFlowState.build(drafts)
        val flat = SessionFlowState.flattened(groups)
        // Ir sin descanso previo: solo abre trabajo.
        var eff = SessionFlowState.WorkoutFlow.ir(flat[0].uuid, null, emptySet())
        assertNull(eff.closeRestOwner)
        assertEquals(flat[0].uuid, eff.openWork)
        // Doble Ir: se ignora.
        eff = SessionFlowState.WorkoutFlow.ir(flat[0].uuid, null, setOf(flat[0].uuid))
        assertNull(eff.closeRestOwner)
        // Ir siguiente con descanso corriendo: lo cierra y anota al previo.
        eff = SessionFlowState.WorkoutFlow.ir(flat[1].uuid, flat[0].uuid, setOf(flat[0].uuid))
        assertEquals(flat[0].uuid, eff.closeRestOwner)
        // Guardar intermedio: abre siguiente y arranca descanso.
        var g = SessionFlowState.WorkoutFlow.guardar(flat[0].uuid, emptySet(), groups)
        assertEquals(flat[0].uuid, g.saved)
        assertEquals(flat[1].uuid, g.nextToExpand)
        assertTrue(g.startRest)
        // Guardar la última: sin siguiente ni descanso post-entreno.
        g = SessionFlowState.WorkoutFlow.guardar(flat[1].uuid, setOf(flat[0].uuid), groups)
        assertNull(g.nextToExpand)
        assertFalse(g.startRest)
    }

    @Test
    fun `collectDrafts no se ve afectado por doneSets`() {
        // Los borradores son la fuente; doneSets es solo presentación.
        val drafts = listOf(draft("Press", "80", "8"), draft("Remo", "60", "10"))
        val (groups, _) = SessionFlowState.build(drafts)
        val flat = SessionFlowState.flattened(groups)
        val done = setOf(flat[0].uuid)
        assertEquals(2, drafts.size)
        assertEquals("80", drafts[0].kg)
        assertEquals(1, done.size)
    }

    @Test
    fun `toggleExpanded alterna solo la suya`() {
        val a = "u1"
        val b = "u2"
        var open = SessionFlowState.toggleExpanded(emptySet(), a)
        assertEquals(setOf(a), open)
        open = SessionFlowState.toggleExpanded(open, b)
        assertEquals(setOf(a, b), open)
        // Cerrar una no toca la otra.
        open = SessionFlowState.toggleExpanded(open, a)
        assertEquals(setOf(b), open)
    }

    @Test
    fun `draftsFromSession preserva descanso_seg oculto`() {
        val sets = listOf(
            TrainingSet(1, "Press", 80.0, 8.0, 1.0, 90.0, 103.9),
            TrainingSet(2, "HIIT", null, null, null, null, null, 12.0, 7.5),
        )
        val drafts = SessionFlowState.draftsFromSession(sets)
        assertEquals(2, drafts.size)
        assertEquals("90", drafts[0].descansoSeg)
        assertEquals("80", drafts[0].kg)
        assertEquals("12", drafts[1].velocidadKmh)
        assertEquals("7.5", drafts[1].dificultad)
    }

    @Test
    fun `descansoSecsFor redondea a 1 decimal`() {
        assertEquals(95.4, SessionFlowState.descansoSecsFor(95_440L), 0.0)
        assertEquals(95.0, SessionFlowState.descansoSecsFor(95_040L), 0.0)
        assertEquals(0.0, SessionFlowState.descansoSecsFor(-50L), 0.0)
        assertEquals("95.4", SessionFlowState.descansoText(95.4))
        assertEquals("95", SessionFlowState.descansoText(95.0))
        assertEquals("–", SessionFlowState.descansoText(null))
    }

    @Test
    fun `formatMmSs pinta MM_SS`() {
        assertEquals("00:00", formatMmSs(0))
        assertEquals("02:05", formatMmSs(125))
        assertEquals("02:15", formatMmSsFromMs(135_000))
    }

    // --- RestTimer -----------------------------------------------------------

    @Test
    fun `start-pause cierra intervalo con duracion monotonica`() {
        val t = RestTimer()
        t.onOpened(1L, "u1", 1_000L, 10_000L)
        assertTrue(t.isRunning("u1"))
        assertEquals(5_000L, t.elapsedFor("u1", 15_000L))
        val closed = t.onClosed(17_000L)
        assertEquals("u1" to 7_000L, closed)
        assertEquals(7_000L, t.elapsedFor("u1", 99_000L))
    }

    @Test
    fun `reanudar abre otro intervalo y acumula`() {
        val t = RestTimer()
        t.onOpened(1L, "u1", 1_000L, 10_000L)
        t.onClosed(15_000L) // 5s
        t.onOpened(2L, "u1", 20_000L, 30_000L)
        t.onClosed(33_000L) // +3s
        assertEquals(8_000L, t.elapsedFor("u1", 99_000L))
    }

    @Test
    fun `pendingClose expone el running para single-running`() {
        val t = RestTimer()
        assertNull(t.pendingClose())
        t.onOpened(7L, "uA", 1_000L, 5_000L)
        val toClose = t.pendingClose()
        assertNotNull(toClose)
        assertEquals(7L, toClose!!.intervalId)
        assertEquals("uA", toClose.uuid)
    }

    @Test
    fun `cambio de serie conserva acumulados`() {
        val t = RestTimer()
        t.onOpened(1L, "u1", 1_000L, 10_000L)
        t.onClosed(12_000L)
        t.onOpened(2L, "u2", 2_000L, 20_000L)
        assertEquals(2_000L, t.elapsedFor("u1", 99_000L))
        assertEquals(5_000L, t.elapsedFor("u2", 25_000L))
    }

}
