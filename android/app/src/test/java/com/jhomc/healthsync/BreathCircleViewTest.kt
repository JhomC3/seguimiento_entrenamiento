package com.jhomc.healthsync

import android.content.Context
import android.view.KeyEvent
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

/** Círculo-botón: toque, teclado y descripciones por modo. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class BreathCircleViewTest {

    private fun view(): BreathCircleView {
        val context = ApplicationProvider.getApplicationContext<Context>()
        return BreathCircleView(context)
    }

    @Test
    fun `es focable y clicable como boton`() {
        val v = view()
        assertTrue(v.isFocusable)
        assertTrue(v.isClickable)
    }

    @Test
    fun `toque dispara onTap`() {
        val v = view()
        var taps = 0
        v.onTap = { taps++ }
        v.performClick()
        assertEquals(1, taps)
    }

    @Test
    fun `enter y espacio disparan onTap`() {
        val v = view()
        var taps = 0
        v.onTap = { taps++ }
        v.onKeyUp(KeyEvent.KEYCODE_ENTER, null)
        v.onKeyUp(KeyEvent.KEYCODE_SPACE, null)
        assertEquals(2, taps)
    }

    @Test
    fun `descripciones por modo`() {
        val v = view()
        v.mode = BreathCircleView.Mode.IDLE
        assertTrue(v.contentDescription.contains("empezar"))
        v.mode = BreathCircleView.Mode.RUNNING
        v.setStage(BreathPhase.EXHALE, 0.5f)
        assertTrue(v.contentDescription.contains("Exhale"))
        v.mode = BreathCircleView.Mode.PAUSED
        assertTrue(v.contentDescription.contains("pausa"))
    }

    @Test
    fun `gris aparece tras el retardo y dispara al total`() {
        val v = view()
        v.measure(
            android.view.View.MeasureSpec.makeMeasureSpec(600, android.view.View.MeasureSpec.EXACTLY),
            android.view.View.MeasureSpec.makeMeasureSpec(600, android.view.View.MeasureSpec.EXACTLY),
        )
        v.layout(0, 0, 600, 600)
        var fake = 0L
        v.nowMs = { fake }
        var holds = 0
        v.onHoldReset = { holds++ }
        val shadows = Shadows.shadowOf(android.os.Looper.getMainLooper())
        v.dispatchTouchEvent(
            android.view.MotionEvent.obtain(0, 0, android.view.MotionEvent.ACTION_DOWN, 300f, 300f, 0),
        )
        fun step(ms: Long) {
            fake += ms
            shadows.idleFor(java.time.Duration.ofMillis(ms))
        }
        step(200L)
        assertEquals(-1f, v.holdProgressForTest())
        repeat(8) { step(100L) }
        assertTrue(v.holdProgressForTest() in 0f..1f)
        repeat(10) { step(100L) }
        assertEquals(1, holds)
        v.dispatchTouchEvent(
            android.view.MotionEvent.obtain(0, 0, android.view.MotionEvent.ACTION_UP, 300f, 300f, 0),
        )
        shadows.idle()
        assertEquals(1, holds)
    }

    @Test
    fun `soltar antes cancela el hold y es toque`() {
        val v = view()
        var fake = 0L
        v.nowMs = { fake }
        var taps = 0
        var holds = 0
        v.onTap = { taps++ }
        v.onHoldReset = { holds++ }
        val shadows = Shadows.shadowOf(android.os.Looper.getMainLooper())
        v.dispatchTouchEvent(
            android.view.MotionEvent.obtain(0, 0, android.view.MotionEvent.ACTION_DOWN, 300f, 300f, 0),
        )
        repeat(5) {
            fake += 100L
            shadows.idle()
        }
        v.dispatchTouchEvent(
            android.view.MotionEvent.obtain(0, 0, android.view.MotionEvent.ACTION_UP, 300f, 300f, 0),
        )
        repeat(20) {
            fake += 100L
            shadows.idle()
        }
        assertEquals(1, taps)
        assertEquals(0, holds)
    }

    @Test
    fun `setStage actualiza fase`() {
        val v = view()
        v.setStage(BreathPhase.INHALE, 0.25f)
        assertEquals(BreathPhase.INHALE, v.phase)
        v.reset()
        assertEquals(BreathPhase.INHALE, v.phase)
    }

    @Test
    fun `color converge al objetivo sin saltos`() {
        val v = view()
        val target = 0xFFE56D88.toInt()
        val start = 0xFF9B1B30.toInt()
        var c: Int? = null
        c = v.nextBlend(c, target)
        assertEquals(target, c)
        c = start
        var mid = c
        repeat(3) { mid = v.nextBlend(mid, target) }
        // Avanza sin saltar al objetivo de golpe.
        assertTrue(mid != start && mid != target)
        repeat(40) { mid = v.nextBlend(mid, target) }
        assertEquals(target, mid)
    }
}
