package com.jhomc.healthsync

import android.app.Activity
import android.os.Build
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val message = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            "HealthSync\nHealth Connect: comprobar disponibilidad"
        } else {
            "HealthSync\nNo compatible: Health Connect requiere Android 9+"
        }
        val label = TextView(this).apply {
            text = message
            textSize = 18f
            setPadding(32, 32, 32, 32)
        }
        setContentView(LinearLayout(this).apply { addView(label) })
    }
}
