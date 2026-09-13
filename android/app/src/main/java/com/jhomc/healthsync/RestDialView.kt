package com.jhomc.healthsync

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View

/**
 * Mini-dial del descanso: ruedita pequeña con el tiempo dentro. Anillo
 * burdeos fijo corriendo (sin barrido: era distracción); tenue en reposo.
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

    private val dm = resources.displayMetrics.density
    private val sp = resources.displayMetrics.scaledDensity
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 12f * dm
        strokeCap = Paint.Cap.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = context.getColor(R.color.detail_white)
        textSize = 28f * sp
        textAlign = Paint.Align.CENTER
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val want = (96 * dm).toInt()
        val size = resolveSize(want, widthMeasureSpec)
        setMeasuredDimension(size, size)
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = (minOf(width, height) / 2f) - ringPaint.strokeWidth
        if (r <= 0) return
        // Anillo tenue en reposo, burdeos sólido corriendo (colores de la web).
        ringPaint.color = context.getColor(
            if (running) R.color.burgundy_400 else R.color.neutral_500,
        )
        ringPaint.alpha = if (running) 255 else 60
        canvas.drawCircle(cx, cy, r, ringPaint)
        canvas.drawText(formatMmSs(ms / 1000), cx, cy + textPaint.textSize / 3f, textPaint)
    }
}
