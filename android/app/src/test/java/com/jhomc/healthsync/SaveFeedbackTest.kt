package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Tabla de decisión de la confirmación de guardado (pura, sin Android).
 * Regla honesta: el evento nace del drenado real, nunca del tap.
 */
class SaveFeedbackTest {

    @Test
    fun `sin peticion de guardado nunca emite aunque haya entrega`() {
        assertNull(resolveSaveEvent(requested = false, delivered = true, sessionPendingAfter = 0, reconciled = false))
    }

    @Test
    fun `reconciliacion inhibe aunque haya entrega`() {
        assertNull(resolveSaveEvent(requested = true, delivered = true, sessionPendingAfter = 0, reconciled = true))
    }

    @Test
    fun `entrega confirma sincronizada`() {
        assertEquals(
            SaveEvent.Synced,
            resolveSaveEvent(requested = true, delivered = true, sessionPendingAfter = 0, reconciled = false),
        )
    }

    @Test
    fun `sin entrega pero con cola confirma solo-local`() {
        assertEquals(
            SaveEvent.LocalOnly,
            resolveSaveEvent(requested = true, delivered = false, sessionPendingAfter = 2, reconciled = false),
        )
    }

    @Test
    fun `sin entrega ni cola no confirma (no-op)`() {
        assertNull(resolveSaveEvent(requested = true, delivered = false, sessionPendingAfter = 0, reconciled = false))
    }

    @Test
    fun `rechazo definitivo sin cola no confirma exito`() {
        // Descarte 400/409: la op salió de la cola sin Ok → silencio;
        // el refresco posterior muestra la verdad del servidor.
        assertNull(resolveSaveEvent(requested = true, delivered = false, sessionPendingAfter = 0, reconciled = false))
    }

    @Test
    fun `sin foto fresca no hay coincidencia (se envia)`() {
        val drafts = listOf(TrainingSetDraft("Press", "80", "8", "1", "", "", ""))
        assertEquals(false, draftsMatchServer(drafts, null))
    }

    @Test
    fun `borrador igual al servidor coincide (no se reenvia)`() {
        val drafts = listOf(TrainingSetDraft("Press", "80", "8", "1", "90", "", ""))
        val fresh = listOf(TrainingSet(1, "Press", 80.0, 8.0, 1.0, 90.0, null))
        assertEquals(true, draftsMatchServer(drafts, fresh))
    }

    @Test
    fun `cambio de valor no coincide (se envia)`() {
        val drafts = listOf(TrainingSetDraft("Press", "82", "8", "1", "", "", ""))
        val fresh = listOf(TrainingSet(1, "Press", 80.0, 8.0, 1.0, null, null))
        assertEquals(false, draftsMatchServer(drafts, fresh))
    }

    @Test
    fun `formato distinto reenvia (idempotente, inofensivo)`() {
        val drafts = listOf(TrainingSetDraft("Press", "80.0", "8", "1", "", "", ""))
        val fresh = listOf(TrainingSet(1, "Press", 80.0, 8.0, 1.0, null, null))
        assertEquals(false, draftsMatchServer(drafts, fresh))
    }
}
