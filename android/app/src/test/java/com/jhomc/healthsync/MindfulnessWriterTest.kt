package com.jhomc.healthsync

import kotlinx.coroutines.runBlocking
import androidx.health.connect.client.feature.ExperimentalMindfulnessSessionApi
import androidx.health.connect.client.records.MindfulnessSessionRecord
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Escritor de meditaciones: completadas, idempotencia, nota y permisos. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
@OptIn(ExperimentalMindfulnessSessionApi::class)
class MindfulnessWriterTest {

    private fun finished(completed: Boolean = true) = FinishedBreathing(
        clientSessionId = "11111111-2222-4333-8444-555555555555",
        startMs = 1789282800000L,
        endMs = 1789282800000L + 120_000L,
        tzOffsetMin = 0,
        plannedS = 120,
        pattern = BreathingPattern(4.0, 0.0, 6.0, 0.0),
        completed = completed,
    )

    @Test
    fun `publica completada con clientRecordId estable`() = runBlocking {
        val fake = FakeHealthConnectGateway()
        fake.granted += HealthConnectManager(fake).mindfulnessWritePermission()
        val out = MindfulnessWriter(fake, HealthConnectManager(fake)).write(finished(), 12, 2.0)
        assertTrue(out is MindfulnessWriter.Outcome.Published)
        assertEquals(1, fake.insertedMindfulness.size)
        val record = fake.insertedMindfulness.single()
        assertEquals("Respiración", record.title)
        assertEquals(
            MindfulnessSessionRecord.MINDFULNESS_SESSION_TYPE_BREATHING,
            record.mindfulnessSessionType,
        )
        assertEquals("11111111-2222-4333-8444-555555555555", record.metadata.clientRecordId)
        assertTrue(record.notes?.contains("12 ciclos") == true)
    }

    @Test
    fun `parcial no se escribe`() = runBlocking {
        val fake = FakeHealthConnectGateway()
        val out = MindfulnessWriter(fake).write(finished(completed = false), 1, 0.1)
        assertTrue(out is MindfulnessWriter.Outcome.Skipped)
        assertTrue(fake.insertedMindfulness.isEmpty())
    }

    @Test
    fun `sin permiso se omite`() = runBlocking {
        val fake = FakeHealthConnectGateway()
        val out = MindfulnessWriter(fake, HealthConnectManager(fake)).write(finished(), 12, 2.0)
        assertEquals(MindfulnessWriter.Outcome.Skipped("sin_permiso"), out)
        assertTrue(fake.insertedMindfulness.isEmpty())
    }

    @Test
    fun `fallo de insercion no lanza`() = runBlocking {
        val fake = FakeHealthConnectGateway()
        fake.granted += HealthConnectManager(fake).mindfulnessWritePermission()
        fake.failInsertMindfulness = true
        val out = MindfulnessWriter(fake, HealthConnectManager(fake)).write(finished(), 12, 2.0)
        assertTrue(out is MindfulnessWriter.Outcome.Failed)
    }

    @Test
    fun `ventana invertida es fallo`() {
        val writer = MindfulnessWriter(FakeHealthConnectGateway())
        val bad = finished().copy(endMs = 1789282800000L - 1000L)
        assertTrue(writer.recordFor(bad, 0, 0.0) == null)
    }
}
