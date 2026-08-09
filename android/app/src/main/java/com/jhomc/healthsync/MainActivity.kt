package com.jhomc.healthsync

import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContract
import androidx.lifecycle.lifecycleScope
import com.jhomc.healthsync.data.SecureTargetStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val manager: HealthConnectManager by lazy {
        HealthConnectManager(RealHealthConnectGateway(this))
    }

    private val targetStore: SecureTargetStore by lazy { SecureTargetStore(this) }

    private lateinit var permissionLauncher: ActivityResultLauncher<Set<String>>
    private lateinit var statusView: TextView
    private lateinit var urlInput: EditText
    private lateinit var tokenInput: EditText

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

        // --- Destino HTTPS (config local; el token va cifrado al Keystore) ---
        root.addView(TextView(this).apply { text = "\nDestino HTTPS (URL del servidor)" })
        urlInput = EditText(this).apply {
            hint = "https://mac.local:8443/sync/health-connect"
            inputType = InputType.TYPE_TEXT_VARIATION_URI
        }
        root.addView(urlInput)
        tokenInput = EditText(this).apply {
            hint = "Token de sincronización (X-Sync-Token)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        root.addView(tokenInput)

        val saveTargetButton = Button(this).apply {
            text = "Guardar destino y programar sync"
            setOnClickListener { saveTarget() }
        }
        root.addView(saveTargetButton)

        val syncNowButton = Button(this).apply {
            text = "Sincronizar ahora"
            setOnClickListener {
                SyncScheduler.syncNow(this@MainActivity)
                statusView.text = "Sync programada (WorkManager). Revisa en unos segundos."
            }
        }
        root.addView(syncNowButton)

        setContentView(ScrollView(this).apply { addView(root) })

        permissionLauncher = registerForActivityResult(
            permissionContract(),
            ActivityResultCallbackAdapter { refreshStates() },
        )
        refreshStates()
        loadTarget()
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

    private fun saveTarget() {
        val url = urlInput.text.toString().trim()
        val token = tokenInput.text.toString().trim()
        lifecycleScope.launch {
            val client = HealthSyncClient()
            when {
                url.isEmpty() -> statusView.text = "URL requerida."
                client.validateTargetUrl(url).isFailure ->
                    statusView.text = "URL inválida: usa https:// (HTTP está prohibido)."
                token.isEmpty() -> statusView.text = "Token requerido."
                else -> {
                    withContext(Dispatchers.IO) {
                        targetStore.saveTarget(url, "default")
                        targetStore.saveToken(token)
                    }
                    SyncScheduler.schedulePeriodic(this@MainActivity)
                    statusView.text = "Destino guardado y sync periódica programada (1h)."
                }
            }
        }
    }

    private fun loadTarget() {
        lifecycleScope.launch {
            val target = withContext(Dispatchers.IO) { targetStore.target() }
            val tokenSet = withContext(Dispatchers.IO) { targetStore.token() != null }
            urlInput.setText(target?.url ?: "")
            if (tokenSet) statusView.text = "Destino configurado. Token: guardado (cifrado)."
        }
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

private class ActivityResultCallbackAdapter(
    private val onResult: (Set<String>) -> Unit,
) : androidx.activity.result.ActivityResultCallback<Set<String>> {
    override fun onActivityResult(result: Set<String>) = onResult(result)
}
