package com.jhomc.healthsync.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class SecureTargetStoreTest {

    @Test
    fun `hex and alnum tokens pass`() {
        assertTrue(SecureTargetStore.isValidSyncToken("72eb4c204b51fb27932079d03bf088e84d4d05c54c7497944277207bdf62b60e"))
        assertTrue(SecureTargetStore.isValidSyncToken("abc123-_XYZ"))
    }

    @Test
    fun `em dash from copy paste is rejected`() {
        assertFalse(SecureTargetStore.isValidSyncToken("72eb4c20\u201451fb27932079"))
    }

    @Test
    fun `spaces and empty tokens are rejected`() {
        assertFalse(SecureTargetStore.isValidSyncToken("con espacio"))
        assertFalse(SecureTargetStore.isValidSyncToken(""))
    }
}
