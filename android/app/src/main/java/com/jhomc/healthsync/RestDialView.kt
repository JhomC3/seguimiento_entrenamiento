package com.jhomc.healthsync

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View

/**
 * Dial del descanso en curso: ruedita con el tiempo dentro. Anillo verde
 * (success_text, ya en paleta) barriendo mientras corre; apagado en reposo.
 * Sin Compose/XML, como el resto de vistas programáticas.
 */
class RestDialView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    var ms: Long = 0L
        set(value) {
            field = value
            contentDescription = if (running) {
                "Descanso en curso ${formatMmSs(value / 1000)}"
            } else {
                "Descanso ${formatMmSs(value / 1000)}"
            }
            invalidate()
        }

    var running: Boolean = false
        set(value) {
            field = value
            invalidate()
        }

    /** Etiqueta pequeña ("Descanso tras Press"): solo informativa. */
    var label: String = ""
        set(value) {
            field = value
            invalidate()
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
        textSize = 40f * sp
        textAlign = Paint.Align.CENTER
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.neutral_400)
        textSize = 12f * sp
        textAlign = Paint.Align.CENTER
    }

    /** Barrido por minuto: da una vuelta por cada 60 s de descanso. */
    private fun sweepDeg(): Float = ((ms / 1000) % 60) / 60f * 360f

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val want = (160 * dm).toInt()
        val size = resolveSize(want, widthMeasureSpec)
        setMeasuredDimension(size, (size * 0.75f).toInt())
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f - 8f * dm
        val r = (minOf(width, height) / 2f) - ringPaint.strokeWidth
        // Pista apagada siempre.
        ringPaint.color = context.getColor(R.color.neutral_500)
        ringPaint.alpha = 60
        canvas.drawCircle(cx, cy, r, ringPaint)
        // Arco verde solo corriendo.
        if (running && r > 0) {
            ringPaint.color = context.getColor(R.color.success_text)
            ringPaint.alpha = 255
            canvas.drawArc(cx - r, cy - r, cx + r, cy + r, -90f, sweepDeg(), false, ringPaint)
        }
        val t = formatMmSs(ms / 1000)
        canvas.drawText(t, cx, cy + textPaint.textSize / 3f, textPaint)
        if (label.isNotBlank()) {
            canvas.drawText(label, cx, height - 4f * dm, labelPaint)
        }
    }
}
