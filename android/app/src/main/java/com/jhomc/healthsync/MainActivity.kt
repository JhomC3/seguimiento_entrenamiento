package com.jhomc.healthsync

import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContract
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val manager: HealthConnectManager by lazy {
        HealthConnectManager(RealHealthConnectGateway(this))
    }

    private lateinit var permissionLauncher: ActivityResultLauncher<Set<String>>
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            setContentView(
                TextView(this).apply {
                    text = "HealthSync\nNo compatible: Health Connect requiere Android 9+ (API 28)"
                    textSize = 18f
                    setPadding(32, 32, 32, 32)
                },
            )
            return
        }

        statusView = TextView(this).apply { textSize = 14f; setPadding(8, 8, 8, 8) }

        val coreButton = Button(this).apply {
            text = "Permisos: núcleo (Samsung Health)"
            setOnClickListener { requestPermissions(manager.corePermissions()) }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(statusView)
            addView(coreButton)
        }

        // Botones opcionales por familia (nunca en el lote inicial).
        RecordTypes.optionalByFamily.forEach { (family, entries) ->
            val label = family.name.lowercase().replaceFirstChar { it.uppercase() } +
                " (${entries.size})"
            val familyButton = Button(this).apply {
                text = if (entries.any { it.sensitivity == Sensitivity.SENSITIVE }) {
                    "$label — sensibles, con explicación"
                } else {
                    label
                }
                setOnClickListener {
                    if (entries.any { it.sensitivity == Sensitivity.SENSITIVE }) {
                        statusView.text = "Los tipos sensibles se explican antes de pedirlos."
                    }
                    requestPermissions(manager.familyPermissions(family))
                }
            }
            root.addView(familyButton)
        }

        val stepsButton = Button(this).apply {
            text = "Pasos últimas 24h (agregado)"
            setOnClickListener { readStepsSmoke() }
        }
        root.addView(stepsButton)

        setContentView(ScrollView(this).apply { addView(root) })

        permissionLauncher = registerForActivityResult(
            permissionContract(),
            ActivityResultCallbackAdapter { refreshStates() },
        )
        refreshStates()
    }

    override fun onResume() {
        super.onResume()
        refreshStates()
    }

    private fun permissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        RealHealthConnectGateway(this).permissionContract()

    private fun requestPermissions(permissions: Set<String>) {
        if (permissions.isEmpty()) return
        permissionLauncher.launch(permissions)
    }

    private fun refreshStates() {
        lifecycleScope.launch {
            val compatible = withContext(Dispatchers.IO) { manager.isCompatible() }
            if (!compatible) {
                statusView.text = "Health Connect no disponible en este dispositivo."
                return@launch
            }
            val background = withContext(Dispatchers.IO) { manager.backgroundReadAvailable() }
            val states = withContext(Dispatchers.IO) { manager.typeStates() }
            val granted = states.count { it.status != TypeStatus.NOT_AUTHORIZED }
            val sb = StringBuilder()
            sb.append("Health Connect: disponible\n")
            sb.append("Lectura en segundo plano: ${if (background) "disponible" else "NO disponible"}\n")
            sb.append("Permisos: $granted/${states.size}\n\n")
            states.forEach { state ->
                sb.append(
                    "${statusMark(state.status)} ${state.entry.typeName} " +
                        "(${state.entry.family.name.lowercase()})" +
                        if (state.entry.sensitivity == Sensitivity.SENSITIVE) " [sensible]" else "",
                )
                sb.append("\n")
            }
            statusView.text = sb.toString()
        }
    }

    private fun readStepsSmoke() {
        lifecycleScope.launch {
            val count = withContext(Dispatchers.IO) { manager.stepsLast24h() }
            statusView.text = if (count != null) {
                "Pasos últimas 24h (agregado): $count"
            } else {
                "Sin datos de pasos en las últimas 24h (o permiso no concedido)."
            }
        }
    }

    private fun statusMark(status: TypeStatus): String = when (status) {
        TypeStatus.READY, TypeStatus.SYNCED -> "✓"
        TypeStatus.NOT_AUTHORIZED -> "○"
        TypeStatus.NOT_AVAILABLE -> "✗"
        TypeStatus.ERROR -> "!"
    }
}

/**
 * android.app.Activity cannot register lifecycle observers without the
 * lifecycle-runtime; ComponentActivity requires a plain (result) -> Unit
 * callback, so adapt it here.
 */
private class ActivityResultCallbackAdapter(
    private val onResult: (Set<String>) -> Unit,
) : androidx.activity.result.ActivityResultCallback<Set<String>> {
    override fun onActivityResult(result: Set<String>) = onResult(result)
}
