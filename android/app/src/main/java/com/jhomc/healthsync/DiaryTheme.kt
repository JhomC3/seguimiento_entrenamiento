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

/** AutoComplete no hereda editTextStyle del tema: mismos valores que Cell.Input. */
fun AutoCompleteTextView.asCellInput() {
    setBackgroundColor(context.getColor(R.color.overlay_row))
    setTextColor(context.getColor(R.color.neutral_100))
    setHintTextColor(context.getColor(R.color.neutral_500))
    textSize = 14f
    minHeight = (44 * resources.displayMetrics.density).toInt()
}
