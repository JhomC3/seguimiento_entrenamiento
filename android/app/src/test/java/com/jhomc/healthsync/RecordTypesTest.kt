package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordTypesTest {

    @Test
    fun `type names are unique`() {
        val names = RecordTypes.all.map { it.typeName }
        assertEquals(names.size, names.distinct().size)
    }

    @Test
    fun `permissions resolve to the health prefix`() {
        // getReadPermission may return the same permission for grouped types
        // (e.g. sleep/session), so uniqueness is NOT a contract; validity is.
        RecordTypes.all.forEach { entry ->
            assertTrue(entry.typeName, entry.permission.startsWith("android.permission.health."))
            assertFalse(entry.permission.isBlank())
        }
    }

    @Test
    fun `every entry has permission and family`() {
        RecordTypes.all.forEach { entry ->
            assertTrue(entry.typeName.isNotBlank())
            assertTrue(entry.permission.startsWith("android.permission.health."))
            assertFalse(entry.family.name.isBlank())
        }
    }

    @Test
    fun `sensitive types are not in the core batch`() {
        RecordTypes.core.forEach { assertFalse(it.sensitivity == Sensitivity.SENSITIVE) }
    }

    @Test
    fun `core batch is non empty and every family is grouped`() {
        assertTrue(RecordTypes.core.isNotEmpty())
        val optional = RecordTypes.all.size - RecordTypes.core.size
        assertEquals(optional, RecordTypes.optionalByFamily.values.sumOf { it.size })
    }

    @Test
    fun `medical family is fully sensitive`() {
        RecordTypes.optionalByFamily[MappingFamily.MEDICAL].orEmpty().forEach {
            assertEquals(Sensitivity.SENSITIVE, it.sensitivity)
        }
    }

    @Test
    fun `type lookup is case-sensitive and stable`() {
        assertEquals("STEPS", RecordTypes.byTypeName("STEPS")?.typeName)
        assertEquals(null, RecordTypes.byTypeName("steps"))
    }
}
