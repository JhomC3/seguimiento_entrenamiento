package com.jhomc.healthsync

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** Pulso corto de vibración (permiso VIBRATE declarado en el manifest). */
internal class BreathingVibration(context: Context) {

    private val appContext = context.applicationContext

    @Suppress("DEPRECATION")
    fun pulse() {
        if (Build.VERSION.SDK_INT >= 31) {
            val manager = appContext.getSystemService(VibratorManager::class.java) ?: return
            manager.defaultVibrator.vibrate(
                VibrationEffect.createOneShot(PULSE_MS, VibrationEffect.DEFAULT_AMPLITUDE),
            )
        } else {
            val vibrator = appContext.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator ?: return
            if (Build.VERSION.SDK_INT >= 26) {
                vibrator.vibrate(VibrationEffect.createOneShot(PULSE_MS, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                vibrator.vibrate(PULSE_MS)
            }
        }
    }

    companion object {
        const val PULSE_MS = 60L
    }
}
