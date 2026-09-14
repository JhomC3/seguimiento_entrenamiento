package com.jhomc.healthsync

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Handler
import android.os.Looper
import android.util.AttributeSet
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration

/**
 * Dial del descanso: ruedita grande (180dp) con el tiempo dentro, legible a
 * brazo extendido. Corriendo: anillo rojo neón con halo (como la web);
 * pausado: rojo tenue congelado; reposo: gris tenue. Sin Compose/XML, como el
 * resto de vistas programáticas.
 *
 * Gestos: toque = pausar/reanudar ([onTap]); mantener 3 s = reiniciar
 * ([onHoldReset]). Si el dedo se mueve es scroll y el hold se cancela.
 */
class RestDialView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    companion object {
        const val HOLD_RESET_MS = 3000L

        /** El gris del hold aparece tras este retardo (los taps no lo ven). */
        const val HOLD_FEEDBACK_DELAY_MS = 500L
    }

    /** Toque corto (pausar/reanudar lo decide el llamante). */
    var onTap: (() -> Unit)? = null

    /** Mantener 3 s (reiniciar lo decide el llamante). */
    var onHoldReset: (() -> Unit)? = null

    var ms: Long = 0L
        set(value) {
            field = value
            refreshContentDescription()
            invalidate()
        }

    var running: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            refreshContentDescription()
            invalidate()
        }

    /** Pausado: número congelado, anillo tenue (excluye el tramo del anotado). */
    var paused: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            refreshContentDescription()
            invalidate()
        }

    /** Ejercicio dueño del descanso (accesibilidad: "Descanso para X …"). */
    var ownerName: String = ""
        set(value) {
            field = value
            refreshContentDescription()
            invalidate()
        }

    /** La serie puede arrancar su descanso con tap (pendiente en reposo). */
    var startable: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            refreshContentDescription()
            invalidate()
        }

    private fun refreshContentDescription() {
        val base = ownerName.trim().takeIf { it.isNotEmpty() }?.let { "Descanso para $it" } ?: "Descanso"
        val t = formatMmSs(ms / 1000)
        contentDescription = when {
            running -> "$base en curso $t. Toca para pausar. Mantén 3 segundos para reiniciar."
            paused -> "$base en pausa $t. Toca para reanudar. Mantén 3 segundos para reiniciar."
            startable -> "$base $t. Toca para iniciar el descanso."
            else -> "$base $t"
        }
    }

    init {
        isClickable = true
        isFocusable = true
        // La sombra del neón no se pinta en capa hardware.
        setLayerType(LAYER_TYPE_SOFTWARE, null)
    }

    private val holdHandler = Handler(Looper.getMainLooper())
    private var holdFired = false
    private var downX = 0f
    private var downY = 0f
    private val holdSlop = ViewConfiguration.get(context).scaledTouchSlop * 1.5f
    private val holdRunnable = Runnable {
        holdFired = true
        performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        onHoldReset?.invoke()
    }

    /**
     * Feedback del hold: pasado el retardo, el anillo funde de rojo a gris
     * (como apagándose) durante el resto del hold y se completa justo al
     * disparar. Los taps y scrolls nunca lo ven.
     */
    private var holding: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            refreshContentDescription()
            invalidate()
        }
    private val holdFeedbackRunnable = Runnable { holding = true }

    /** Progreso 0..1 del sweep gris sobre los 3 s del hold. */
    private var holdFraction: Float = 0f
    private var holdAnimator: ValueAnimator? = null

    private fun startHoldSweep() {
        cancelHoldSweep()
        holdAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = HOLD_RESET_MS
            addUpdateListener {
                holdFraction = it.animatedValue as Float
                if (holding) invalidate()
            }
            start()
        }
    }

    private fun cancelHoldSweep() {
        holdAnimator?.cancel()
        holdAnimator = null
        if (holdFraction != 0f) {
            holdFraction = 0f
            invalidate()
        }
    }

    private fun cancelHold() {
        holdHandler.removeCallbacks(holdRunnable)
        holdHandler.removeCallbacks(holdFeedbackRunnable)
        parent?.requestDisallowInterceptTouchEvent(false)
        holding = false
        cancelHoldSweep()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                holdFired = false
                downX = event.x
                downY = event.y
                // El padre no roba el gesto: el hold completa salvo scroll real.
                parent?.requestDisallowInterceptTouchEvent(true)
                holdHandler.postDelayed(holdRunnable, HOLD_RESET_MS)
                holdHandler.postDelayed(holdFeedbackRunnable, HOLD_FEEDBACK_DELAY_MS)
                startHoldSweep()
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.x - downX
                val dy = event.y - downY
                if (dx * dx + dy * dy > holdSlop * holdSlop) {
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

    override fun performClick(): Boolean {
        super.performClick()
        onTap?.invoke()
        return true
    }

    private val dm = resources.displayMetrics.density
    private val sp = resources.displayMetrics.scaledDensity
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 12f * dm
        strokeCap = Paint.Cap.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.detail_white)
        textSize = 48f * sp
        textAlign = Paint.Align.CENTER
    }

    /** Interpolación lineal de colores (fundido rojo→gris del hold). */
    private fun lerpColor(from: Int, to: Int, f: Float): Int {
        val t = f.coerceIn(0f, 1f)
        return Color.argb(
            (Color.alpha(from) + (Color.alpha(to) - Color.alpha(from)) * t).toInt(),
            (Color.red(from) + (Color.red(to) - Color.red(from)) * t).toInt(),
            (Color.green(from) + (Color.green(to) - Color.green(from)) * t).toInt(),
            (Color.blue(from) + (Color.blue(to) - Color.blue(from)) * t).toInt(),
        )
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val want = (180 * dm).toInt()
        val w = resolveSize(want, widthMeasureSpec)
        val h = resolveSize(want, heightMeasureSpec)
        val s = minOf(w, h).coerceAtMost(want)
        setMeasuredDimension(s, s)
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = (minOf(width, height) / 2f) - ringPaint.strokeWidth
        if (r <= 0) return
        // Corriendo: rojo neón con halo (glow de la web). Pausado: rojo tenue
        // sin halo. Reposo: gris tenue.
        val neonRed = context.getColor(R.color.burgundy_500)
        val gray = context.getColor(R.color.neutral_500)
        val white = context.getColor(R.color.detail_white)
        var glowRadius = 0f
        when {
            running -> {
                ringPaint.color = neonRed
                ringPaint.alpha = 255
                glowRadius = 24f * dm
            }
            paused -> {
                ringPaint.color = neonRed
                ringPaint.alpha = 110
            }
            else -> {
                ringPaint.color = gray
                ringPaint.alpha = 60
            }
        }
        textPaint.color = white
        // Fundido del hold: el anillo pasa de rojo a gris y el halo muere,
        // como apagándose. Solo visible pasado el retardo; la fracción manda.
        if (holding && holdFraction > 0f) {
            val f = holdFraction.coerceIn(0f, 1f)
            ringPaint.color = lerpColor(ringPaint.color, gray, f)
            glowRadius *= (1f - f)
            textPaint.color = lerpColor(white, gray, f)
        }
        if (glowRadius < 0.5f) {
            ringPaint.clearShadowLayer()
        } else {
            ringPaint.setShadowLayer(glowRadius, 0f, 0f, ringPaint.color)
        }
        canvas.drawCircle(cx, cy, r, ringPaint)
        // Auto-ajuste: el número manda y siempre cabe (tope 48sp, mínimo 20sp).
        val t = formatMmSs(ms / 1000)
        val inner = (r * 2f) * 0.90f
        var size = 48f * sp
        textPaint.textSize = size
        while (size > 20f * sp && textPaint.measureText(t) > inner) {
            size -= 1f * sp
            textPaint.textSize = size
        }
        val dy = -(textPaint.fontMetrics.ascent + textPaint.fontMetrics.descent) / 2f
        canvas.drawText(t, cx, cy + dy, textPaint)
    }
}
