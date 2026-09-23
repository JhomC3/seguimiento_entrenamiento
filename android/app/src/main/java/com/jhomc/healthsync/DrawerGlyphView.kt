package com.jhomc.healthsync

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View

/**
 * Glifo del panel: dos líneas redondeadas, la segunda más corta. Sin texto
 * ni emoji: el mismo lenguaje lo usa [ChevronView] en el acordeón.
 */
class DrawerGlyphView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    /** Toque corto (abrir el panel lo decide el llamante). */
    var onTap: (() -> Unit)? = null

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = context.getColor(R.color.neutral_100)
    }

    private var downX = 0f
    private var downY = 0f

    init {
        isFocusable = true
        isClickable = true
        contentDescription = "Abrir ajustes"
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val d = resources.displayMetrics.density
        paint.strokeWidth = 2.5f * d
        val x0 = 10f * d
        val x1 = 26f * d
        val y1 = height / 2f - 4f * d
        val y2 = height / 2f + 4f * d
        canvas.drawLine(x0, y1, x1, y1, paint)
        // Segunda línea más corta (60 %).
        canvas.drawLine(x0, y2, x0 + (x1 - x0) * 0.6f, y2, paint)
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
                downX = event.x
                downY = event.y
                return true
            }
            MotionEvent.ACTION_UP -> {
                val slop = 24f * resources.displayMetrics.density
                if (kotlin.math.abs(event.x - downX) <= slop &&
                    kotlin.math.abs(event.y - downY) <= slop
                ) {
                    performClick()
                }
                return true
            }
            MotionEvent.ACTION_CANCEL -> return true
        }
        return super.onTouchEvent(event)
    }
}

/**
 * Chevron del acordeón: V que apunta abajo (cerrado) o arriba (abierto).
 */
class ChevronView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    var expanded: Boolean = false
        set(value) {
            field = value
            contentDescription = if (value) "Contraer" else "Expandir"
            invalidate()
        }

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = context.getColor(R.color.burgundy_400)
    }

    init {
        isFocusable = false
        isClickable = false
        contentDescription = "Expandir"
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val d = resources.displayMetrics.density
        paint.strokeWidth = 2.5f * d
        val cx = width / 2f
        val cy = height / 2f
        val arm = 7f * d
        val rise = 5f * d
        val dir = if (expanded) -1f else 1f
        canvas.drawLine(cx - arm, cy - dir * rise / 2, cx, cy + dir * rise / 2, paint)
        canvas.drawLine(cx, cy + dir * rise / 2, cx + arm, cy - dir * rise / 2, paint)
    }
}
