package com.jhomc.healthsync

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * El tema Android es un port de static/design-tokens.json (única fuente).
 * Falla si la app vuelve al tema claro de sistema o los hex canónicos
 * cambian sin actualizar los tokens.
 */
class ThemeContractTest {

    private fun res(name: String): File =
        File("src/main/res/values/$name").takeIf { it.exists() }
            ?: File("../src/main/res/values/$name")

    private val manifest: File =
        File("src/main/AndroidManifest.xml").takeIf { it.exists() }
            ?: File("../src/main/AndroidManifest.xml")

    @Test
    fun manifest_usa_app_theme() {
        val content = manifest.readText()
        assertTrue(content.contains("@style/AppTheme"))
        assertTrue(!content.contains("@android:style/Theme.Material\""))
    }

    @Test
    fun colores_canonicos_de_los_tokens() {
        val content = res("colors.xml").readText()
        for (hex in listOf("#0A0A0A", "#9B1B30", "#E56D88", "#F5F5F5", "#800020")) {
            assertTrue("falta $hex en colors.xml", content.contains(hex, ignoreCase = true))
        }
    }

    @Test
    fun vocabulario_de_estilos_existe() {
        val content = res("styles.xml").readText()
        for (style in listOf("Btn.Primary", "Btn.Outline", "Btn.Ghost", "Diary.Title", "Diary.ExerciseName", "Cell.Input")) {
            assertTrue("falta $style en styles.xml", content.contains(style))
        }
    }
}
