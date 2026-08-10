package com.jhomc.healthsync

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Regression guard: Health Connect (providers 2025+) only registers apps that
 * declare the permissions-rationale handler (privacy policy link) in their
 * manifest. Without it the app never appears in HC's app list and the
 * permission dialog opens empty — verified on-device (Redmi/Android 13, HC
 * v268669). This test fails if the declaration is ever removed.
 */
class ManifestContractTest {

    private val manifest: File =
        File("src/main/AndroidManifest.xml").takeIf { it.exists() }
            ?: File("../src/main/AndroidManifest.xml")

    @Test
    fun manifest_declares_permissions_rationale_handler() {
        assertTrue("manifest no encontrado para verificar", manifest.exists())
        val content = manifest.readText()
        assertTrue(
            "falta ACTION_SHOW_PERMISSIONS_RATIONALE en queries",
            content.contains("androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE"),
        )
        assertTrue(
            "falta intent-filter ACTION_SHOW_PERMISSIONS_RATIONALE en la activity",
            content.contains(
                "<intent-filter>\n" +
                    "                <action android:name=\"androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE\" />",
            ),
        )
    }
}
