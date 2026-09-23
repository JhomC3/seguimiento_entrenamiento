package com.jhomc.healthsync

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Handler
import android.os.Looper
import android.util.AttributeSet
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration

/**
 * Círculo del pacer Y botón principal (como el dial de descanso): crece al
 * inhalar, se vacía al exhalar, quieto en sostén. Colores del port de
 * design-tokens (nada fuera de colors.xml). Sin animaciones propias: el
 * llamante fija [stage] en cada tick; con animadores desactivados se pinta
 * el estado de la fase (cues por tono + texto, sin movimiento).
 *
 * Gestos: toque = [onTap] (iniciar/pausar/reanudar lo decide el llamante);
 * mantener 3 s sin mover el dedo = [onHoldReset] (terminar y guardar).
 * Accesible como botón: focable, Enter/Espacio = toque, descripción según
 * [mode]. Con el dedo en movimiento es scroll y el hold se cancela.
 */
class BreathCircleView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    enum class Mode { IDLE, RUNNING, PAUSED }

    /** Toque corto (lo decide el llamante). */
    var onTap: (() -> Unit)? = null

    /** Mantener 3 s (lo decide el llamante). */
    var onHoldReset: (() -> Unit)? = null

    var mode: Mode = Mode.IDLE
        set(value) {
            field = value
            refreshDescription()
        }

    var phase: BreathPhase = BreathPhase.INHALE
        private set
    private var fraction: Float = 0f

    /** Color actual pintado (el fundido lo acerca al objetivo por dibujado). */
    private var ringBlend: Int? = null
    internal fun ringBlendForTest(): Int? = ringBlend

    /** Un paso de fundido hacia el objetivo (puro, sin recursos: testeable). */
    internal fun nextBlend(current: Int?, target: Int): Int {
        val blended = lerpColor(current ?: target, target, 0.35f)
        return if (channelDiff(blended, target) <= 6) target else blended
    }

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4f * resources.displayMetrics.density
    }

    private val handler = Handler(Looper.getMainLooper())
    private val slop = ViewConfiguration.get(context).scaledTouchSlop * 1.5f
    private var downX: Float = 0f
    private var downY: Float = 0f
    private var holdFired: Boolean = false
    /** Reloj inyectable (tests avanzan el tiempo a mano). */
    internal var nowMs: () -> Long = { System.currentTimeMillis() }
    internal fun holdProgressForTest(): Float = holdFraction
    internal fun holdingForTest(): Boolean = holding

    private val holdRunnable = Runnable {
        holdFired = true
        performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        onHoldReset?.invoke()
    }

    /**
     * Fundido del hold idéntico al dial de descanso: pasado el retardo
     * (500 ms), el anillo funde a gris (como apagándose) y se completa justo
     * al disparar (aquí 1.5 s en vez de 3 s). Los taps y scrolls nunca lo ven.
     * La fracción avanza por handler (testeable con reloj inyectado); el
     * observable es el mismo que con el ValueAnimator del dial.
     */
    private var holding: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            refreshDescription()
            invalidate()
        }
    private val holdFeedbackRunnable = Runnable { holding = true }

    /** 0..1 del fundido gris; -1 = sin hold en curso. */
    private var holdFraction: Float = -1f
    private val holdTick = object : Runnable {
        override fun run() {
            if (holdFired) return
            val elapsed = nowMs() - holdStartMs
            holdFraction = ((elapsed - GRAY_DELAY_MS).toFloat() / (HOLD_RESET_MS - GRAY_DELAY_MS))
                .coerceIn(0f, 1f)
                .let { if (elapsed < GRAY_DELAY_MS) -1f else it }
            if (holding) invalidate()
            if (elapsed < HOLD_RESET_MS) handler.postDelayed(this, HOLD_TICK_MS)
        }
    }
    private var holdStartMs: Long = 0L

    init {
        isFocusable = true
        isClickable = true
        refreshDescription()
    }

    /** Fase + fracción 0..1 transcurrida de la fase. Repinta. */
    fun setStage(phase: BreathPhase, fraction: Float) {
        this.phase = phase
        this.fraction = fraction.coerceIn(0f, 1f)
        refreshDescription()
        invalidate()
    }

    fun reset() {
        phase = BreathPhase.INHALE
        fraction = 0f
        refreshDescription()
        invalidate()
    }

    private fun refreshDescription() {
        contentDescription = when (mode) {
            Mode.IDLE -> "Respiración detenida. Toca para empezar."
            Mode.PAUSED -> "Respiración en pausa (${phase.label}). Toca para continuar."
            Mode.RUNNING -> "Respiración: ${phase.label}. Toca para pausar, mantén para terminar."
        }
    }

    override fun performClick(): Boolean {
        super.performClick()
        onTap?.invoke()
        return true
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_ENTER || keyCode == KeyEvent.KEYCODE_SPACE) {
            return performClick()
        }
        return super.onKeyUp(keyCode, event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                // Solo el círculo dibujado responde; fuera, scroll normal.
                val cx = width / 2f
                val cy = height / 2f
                val maxR = (minOf(width, height) / 2f) * 0.92f
                val dx0 = event.x - cx
                val dy0 = event.y - cy
                if (dx0 * dx0 + dy0 * dy0 > (maxR * 1.05f) * (maxR * 1.05f)) return false
                holdFired = false
                downX = event.x
                downY = event.y
                holdStartMs = nowMs()
                // El padre no roba el gesto: el hold completa salvo scroll real.
                parent?.requestDisallowInterceptTouchEvent(true)
                handler.postDelayed(holdRunnable, HOLD_RESET_MS)
                handler.postDelayed(holdFeedbackRunnable, GRAY_DELAY_MS)
                handler.post(holdTick)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.x - downX
                val dy = event.y - downY
                if (dx * dx + dy * dy > slop * slop) {
                    // Scroll real: se devuelve el gesto al padre y muere el hold.
                    parent?.requestDisallowInterceptTouchEvent(false)
                    cancelHold()
                    return false
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                cancelHold()
                if (!holdFired) performClick()
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                cancelHold()
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    private fun cancelHold() {
        handler.removeCallbacks(holdRunnable)
        handler.removeCallbacks(holdFeedbackRunnable)
        handler.removeCallbacks(holdTick)
        parent?.requestDisallowInterceptTouchEvent(false)
        holding = false
        if (holdFraction != -1f) {
            holdFraction = -1f
            refreshDescription()
            invalidate()
        }
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(holdRunnable)
        handler.removeCallbacks(holdFeedbackRunnable)
        handler.removeCallbacks(holdTick)
        super.onDetachedFromWindow()
    }

    /** Interpolación lineal de colores (fundido a gris del hold, como el dial). */
    private fun channelDiff(a: Int, b: Int): Int {
        return kotlin.math.abs(Color.red(a) - Color.red(b)) +
            kotlin.math.abs(Color.green(a) - Color.green(b)) +
            kotlin.math.abs(Color.blue(a) - Color.blue(b))
    }

    private fun lerpColor(from: Int, to: Int, f: Float): Int {
        val t = f.coerceIn(0f, 1f)
        return android.graphics.Color.argb(
            (android.graphics.Color.alpha(from) + (android.graphics.Color.alpha(to) - android.graphics.Color.alpha(from)) * t).toInt(),
            (android.graphics.Color.red(from) + (android.graphics.Color.red(to) - android.graphics.Color.red(from)) * t).toInt(),
            (android.graphics.Color.green(from) + (android.graphics.Color.green(to) - android.graphics.Color.green(from)) * t).toInt(),
            (android.graphics.Color.blue(from) + (android.graphics.Color.blue(to) - android.graphics.Color.blue(from)) * t).toInt(),
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cx = width / 2f
        val cy = height / 2f
        val maxR = (minOf(width, height) / 2f) * 0.92f
        val scale = when (phase) {
            BreathPhase.INHALE -> 0.55f + 0.45f * fraction
            BreathPhase.EXHALE -> 1f - 0.45f * fraction
            BreathPhase.HOLD_IN -> 1f
            BreathPhase.HOLD_OUT -> 0.55f
            BreathPhase.REST -> 0.8f
        }
        val gray = context.getColor(R.color.neutral_500)
        val target = context.getColor(
            when (phase) {
                BreathPhase.INHALE -> R.color.burgundy_400
                BreathPhase.HOLD_IN -> R.color.burgundy_300
                BreathPhase.EXHALE -> R.color.class_jalon
                BreathPhase.HOLD_OUT -> R.color.neutral_500
                BreathPhase.REST -> R.color.neutral_600
            },
        )
        // El color acompaña al giro: interpola hacia el objetivo en cada
        // dibujado (~200 ms de convergencia) en vez de saltar en seco.
        var color = nextBlend(ringBlend, target)
        ringBlend = color
        var fillAlpha = 90
        // Fundido del hold: el anillo pasa a gris (como apagándose) y el
        // relleno muere. Solo visible pasado el retardo; se completa al disparar.
        if (holding && holdFraction > 0f) {
            val f = holdFraction.coerceIn(0f, 1f)
            color = lerpColor(color, gray, f)
            fillAlpha = (90 * (1f - f)).toInt()
        }
        ring.color = color
        ring.alpha = 160
        canvas.drawCircle(cx, cy, maxR, ring)
        fill.color = color
        fill.alpha = fillAlpha
        canvas.drawCircle(cx, cy, maxR * scale, fill)
    }

    companion object {
        const val HOLD_RESET_MS = 1500L
        const val GRAY_DELAY_MS = 500L
        const val HOLD_TICK_MS = 50L
    }
}
