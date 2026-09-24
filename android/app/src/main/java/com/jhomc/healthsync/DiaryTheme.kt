package com.jhomc.healthsync

import android.content.Context
import android.view.ContextThemeWrapper
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.TextView

/**
 * Aplicación del tema web en Views programáticas (sin XML de layouts).
 * Los Button() planos ya salen Btn.Outline por AppTheme; aquí solo los
 * acentos: primario, peligro, títulos y estados (nunca solo color).
 */

fun Context.primaryButton(text: String): Button =
    Button(ContextThemeWrapper(this, R.style.Btn_Primary)).apply { this.text = text }

fun Button.asDanger() {
    setTextColor(context.getColor(R.color.danger_text))
}

fun TextView.asTitle() {
    setTextAppearance(context, R.style.Diary_Title)
}

fun TextView.asSectionTitle() {
    setTextAppearance(context, R.style.Diary_SectionTitle)
}

/** Nombre del ejercicio en el diario: grande, centrado (modo registro). */
fun TextView.asExerciseName() {
    setTextAppearance(context, R.style.Diary_ExerciseName)
    textSize = 22f
    setTypeface(typeface, android.graphics.Typeface.BOLD)
    if (this is Button) isAllCaps = false
    gravity = android.view.Gravity.CENTER
    maxLines = 2
    ellipsize = android.text.TextUtils.TruncateAt.END
    includeFontPadding = false
}

fun TextView.asSummary() {
    setTextAppearance(context, R.style.Diary_Summary)
}

/** Estado con texto + estilo (el error lleva prefijo, nunca es solo rojo). */
fun TextView.asStatus(text: String, kind: StatusKind) {
    this.text = text
    setTextAppearance(
        context,
        when (kind) {
            StatusKind.ERROR -> R.style.Status_Error
            StatusKind.SUCCESS -> R.style.Status_Success
            StatusKind.NOTICE -> R.style.Status_Notice
        },
    )
}

enum class StatusKind { ERROR, SUCCESS, NOTICE }

/** Guardar del pacer: fantasma idéntico a Descartar (mismo todo). */
fun Context.friendlyButton(text: String): Button =
    Button(this).apply {
        this.text = text
        textSize = 16f
        minHeight = (52 * resources.displayMetrics.density).toInt()
        setTextColor(context.getColor(R.color.neutral_100))
        background = glassBg(fill = 0x00000000, stroke = 0x00000000)
        asBreather(bold = false)
    }

/** Descartar del pacer: fantasma idéntico a Guardar (mismo todo). */
fun Context.friendlyOutlineButton(text: String): Button =
    Button(this).apply {
        this.text = text
        textSize = 16f
        minHeight = (52 * resources.displayMetrics.density).toInt()
        setTextColor(context.getColor(R.color.neutral_100))
        background = glassBg(fill = 0x00000000, stroke = 0x00000000)
        asBreather(bold = false)
    }

/** Botón de texto del pacer (acción terciaria, mismo alto táctil). */
fun Context.friendlyTextButton(text: String): Button =
    Button(this).apply {
        this.text = text
        textSize = 15f
        minHeight = (48 * resources.displayMetrics.density).toInt()
        setTextColor(context.getColor(R.color.burgundy_400))
        background = pillBg(fill = 0x00000000, stroke = 0x00000000)
        asBreather()
    }

private fun pillBg(fill: Int, stroke: Int): android.graphics.drawable.Drawable {
    val d = density()
    return android.graphics.drawable.GradientDrawable().apply {
        shape = android.graphics.drawable.GradientDrawable.RECTANGLE
        cornerRadius = 26f * d
        setColor(fill)
        if (stroke != 0) setStroke((1.5f * d).toInt(), stroke)
    }
}

/** Fondo glass: esquinas 14dp, borde hairline opcional (0 = sin borde). */
private fun glassBg(fill: Int, stroke: Int): android.graphics.drawable.Drawable {
    val d = density()
    return android.graphics.drawable.GradientDrawable().apply {
        shape = android.graphics.drawable.GradientDrawable.RECTANGLE
        cornerRadius = 14f * d
        setColor(fill)
        if (stroke != 0) setStroke(d.coerceAtLeast(1f).toInt(), stroke)
    }
}

private fun density(): Float = android.content.res.Resources.getSystem().displayMetrics.density

private fun roundedBg(color: Int): android.graphics.drawable.Drawable {
    val normal = android.graphics.drawable.GradientDrawable().apply {
        shape = android.graphics.drawable.GradientDrawable.RECTANGLE
        cornerRadius = 14f
        setColor(color)
    }
    return normal
}

/** Tipografía del pacer (Comfortaa); si falla, la del sistema. */
fun TextView.asBreather(bold: Boolean = false) {
    runCatching {
        typeface = resources.getFont(if (bold) R.font.comfortaa_bold else R.font.comfortaa)
    }
    if (bold) paint.isFakeBoldText = true
}

fun Button.asBreather(bold: Boolean = false) {
    runCatching {
        typeface = resources.getFont(if (bold) R.font.comfortaa_bold else R.font.comfortaa)
    }
    if (bold) paint.isFakeBoldText = true
    minHeight = (48 * resources.displayMetrics.density).toInt()
}

/** AutoComplete no hereda editTextStyle del tema: mismos valores que Cell.Input. */
fun AutoCompleteTextView.asCellInput() {
    setBackgroundColor(context.getColor(R.color.overlay_row))
    setTextColor(context.getColor(R.color.neutral_100))
    setHintTextColor(context.getColor(R.color.neutral_500))
    textSize = 14f
    minHeight = (44 * resources.displayMetrics.density).toInt()
}
