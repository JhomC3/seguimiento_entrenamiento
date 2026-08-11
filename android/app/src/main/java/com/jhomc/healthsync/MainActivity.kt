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
        if (intent?.action == RATIONALE_ACTION) {
            showPrivacyPolicy()
            return
        }
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

        val openHcButton = Button(this).apply {
            text = "Abrir Health Connect (permisos manuales)"
            setOnClickListener { openHealthConnect() }
        }

        val singlePermissionButton = Button(this).apply {
            text = "Probar: pedir SOLO pasos (1 permiso)"
            setOnClickListener {
                val stepsPermission = RecordTypes.byTypeName("STEPS")?.permission ?: return@setOnClickListener
                requestPermissions(setOf(stepsPermission))
            }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(statusView)
            addView(coreButton)
            addView(openHcButton)
            addView(singlePermissionButton)
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
                showMessage("Sync programada. Los datos llegarán en segundos.")
            }
        }
        root.addView(syncNowButton)

        val diagnosticsButton = Button(this).apply {
            text = "Diagnóstico (ver qué ve el sistema)"
            setOnClickListener { runDiagnostics() }
        }
        root.addView(diagnosticsButton)

        val syncStateButton = Button(this).apply {
            text = "Estado de la sync (WorkManager)"
            setOnClickListener { showSyncState() }
        }
        root.addView(syncStateButton)

        setContentView(ScrollView(this).apply { addView(root) })

        permissionLauncher = registerForActivityResult(
            permissionContract(),
            ActivityResultCallbackAdapter { granted ->
                statusView.text = "Permisos concedidos: ${granted.size} tipos."
                refreshStates()
            },
        )
        refreshStates()
        loadTarget()
    }

    override fun onResume() {
        super.onResume()
        refreshStates()
    }

    /**
     * Health Connect (ACTION_SHOW_PERMISSIONS_RATIONALE): pantalla de política
     * de privacidad exigida por el contrato del proveedor cuando el usuario
     * toca el enlace en el diálogo de permisos.
     */
    private fun showPrivacyPolicy() {
        val privacyView = TextView(this).apply {
            text = "Privacidad de HealthSync\n\n" +
                "HealthSync lee tus datos de salud (pasos, frecuencia cardíaca, " +
                "sueño, ejercicio, peso y composición) SOLO para tu propio " +
                "análisis personal.\n\n" +
                "Los datos se envían únicamente a tu servidor personal (por " +
                "defecto, tu propio Mac en tu red) mediante HTTPS con un token " +
                "secreto. No se comparten con terceros, no se venden y no salen " +
                "de tu infraestructura.\n\n" +
                "Puedes revocar los permisos en cualquier momento desde " +
                "Health Connect."
            textSize = 16f
            setPadding(32, 32, 32, 32)
        }
        val okButton = Button(this).apply {
            text = "Entendido"
            setOnClickListener { finish() }
        }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                addView(privacyView)
                addView(okButton)
            },
        )
    }

    private fun permissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        RealHealthConnectGateway(this).permissionContract()

    private fun requestPermissions(permissions: Set<String>) {
        if (permissions.isEmpty()) return
        try {
            permissionLauncher.launch(permissions)
        } catch (e: Exception) {
            // MIUI bloquea a veces el lanzamiento de la pantalla de Health
            // Connect; nunca dejar el fallo en silencio.
            statusView.text = "No se pudo abrir Health Connect ($e).\n" +
                "Usa el botón 'Abrir Health Connect' y concede los permisos desde allí, " +
                "o activa 'Abrir ventanas en segundo plano' para HealthSync en Ajustes de MIUI."
        }
    }

    private fun openHealthConnect() {
        val packageName = "com.google.android.apps.healthdata"
        val enabled = runCatching {
            packageManager.getApplicationEnabledSetting(packageName)
        }.getOrDefault(android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DEFAULT)
        if (enabled == android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED) {
            statusView.text = "Health Connect está DESHABILITADA.\n" +
                "Vé a Ajustes > Apps > Health Connect > Habilitar, y reintenta."
            return
        }
        val playStore = android.content.Intent(
            android.content.Intent.ACTION_VIEW,
            android.net.Uri.parse("market://details?id=$packageName"),
        )
        val launcher = android.content.Intent(android.content.Intent.ACTION_MAIN).apply {
            addCategory(android.content.Intent.CATEGORY_LAUNCHER)
            `package` = packageName
        }
        runCatching {
            startActivity(launcher)
        }.onFailure {
            runCatching { startActivity(playStore) }
                .onFailure { statusView.text = "No se pudo abrir Health Connect: $it" }
        }
    }

    private fun saveTarget() {
        val url = urlInput.text.toString().trim()
        val token = tokenInput.text.toString().trim()
        lifecycleScope.launch {
            val client = HealthSyncClient()
            when {
                url.isEmpty() -> showMessage("URL requerida.")
                client.validateTargetUrl(url, allowHttp = BuildConfig.DEBUG).isFailure ->
                    showMessage("URL inválida: usa https:// (HTTP solo en versiones de prueba).")
                token.isEmpty() -> showMessage("Token requerido.")
                else -> {
                    withContext(Dispatchers.IO) {
                        targetStore.saveTarget(url, "default")
                        targetStore.saveToken(token)
                    }
                    SyncScheduler.schedulePeriodic(this@MainActivity)
                    showMessage("Destino guardado y sync periódica programada (1h).")
                }
            }
        }
    }

    /** Mensaje visible siempre (Toast) + en el panel de estado. */
    private fun showMessage(message: String) {
        statusView.text = message
        android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show()
    }

    private fun loadTarget() {
        lifecycleScope.launch {
            try {
                val target = withContext(Dispatchers.IO) { targetStore.target() }
                val tokenSet = withContext(Dispatchers.IO) { targetStore.token() != null }
                urlInput.setText(target?.url ?: "")
                if (tokenSet) statusView.text = "Destino configurado. Token: guardado (cifrado)."
            } catch (e: Exception) {
                statusView.text = "No se pudo leer la configuración: $e"
            }
        }
    }

    private fun refreshStates() {
        lifecycleScope.launch {
            try {
                val compatible = withContext(Dispatchers.IO) { manager.isCompatible() }
                if (!compatible) {
                    val detail = withContext(Dispatchers.IO) { manager.providerDetail() }
                    val installed = detail.installedVersionCode?.toString() ?: "no instalada"
                    statusView.text = "Health Connect: NO disponible (SDK status ${manager.sdkStatus()}).\n" +
                        "Proveedor ${detail.packageName}: v$installed " +
                        "(mínimo requerido v${detail.minRequiredVersionCode}).\n" +
                        "Pulsa 'Abrir Health Connect' para instalarla/actualizarla."
                    return@launch
                }
                val background = withContext(Dispatchers.IO) { manager.backgroundReadAvailable() }
                val detail = withContext(Dispatchers.IO) { manager.providerDetail() }
                val states = withContext(Dispatchers.IO) { manager.typeStates() }
                val granted = states.count { it.status == TypeStatus.READY || it.status == TypeStatus.SYNCED }
                val sb = StringBuilder()
                sb.append("Health Connect: disponible")
                detail.installedVersionCode?.let { sb.append(" (v$it)") }
                sb.append("\n")
                sb.append("Lectura en segundo plano: ${if (background) "disponible" else "NO disponible"}\n")
                sb.append("Permisos: $granted/${states.size}\n\n")
                states.forEach { state ->
                    sb.append(
                        "${statusText(state.status)} ${state.entry.typeName} " +
                            "(${state.entry.family.name.lowercase()})" +
                            if (state.entry.sensitivity == Sensitivity.SENSITIVE) " [sensible]" else "",
                    )
                    sb.append("\n")
                }
                statusView.text = sb.toString()
            } catch (e: Exception) {
                // El servicio de Health Connect puede no responder durante el
                // arranque; la app nunca debe morir por ello.
                statusView.text = "Health Connect: pendiente de conectar… ($e)"
            }
        }
    }

    private fun readStepsSmoke() {
        lifecycleScope.launch {
            try {
                val count = withContext(Dispatchers.IO) { manager.stepsLast24h() }
                statusView.text = if (count != null) {
                    "Pasos últimas 24h (agregado): $count"
                } else {
                    "Sin datos de pasos en las últimas 24h (o permiso no concedido)."
                }
            } catch (e: Exception) {
                statusView.text = "Fallo al leer pasos: $e"
            }
        }
    }

    private fun runDiagnostics() {
        lifecycleScope.launch {
            val sb = StringBuilder()
            // 1) Qué permisos ve el SISTEMA en el APK instalado de HealthSync.
            val requested = runCatching {
                packageManager.getPackageInfo(
                    packageName,
                    android.content.pm.PackageManager.GET_PERMISSIONS,
                ).requestedPermissions?.toList() ?: emptyList()
            }.getOrDefault(emptyList())
            val healthPerms = requested.filter { it.startsWith("android.permission.health.") }
            sb.append("Permisos health que el sistema ve en HealthSync:\n")
            sb.append(if (healthPerms.isEmpty()) "  NINGUNO\n" else "  ${healthPerms.size}: ${healthPerms.joinToString(", ")}\n")
            sb.append("\n")

            // 2) El intent de permisos: ¿lo resuelve el sistema a alguna activity?
            try {
                val contract = androidx.health.connect.client.PermissionController
                    .createRequestPermissionResultContract()
                val intent = contract.createIntent(this@MainActivity, manager.corePermissions())
                val resolved = intent.resolveActivity(packageManager)
                sb.append("Intent de permisos: ${intent.action}\n")
                sb.append("  paquete: ${intent.`package`}\n")
                sb.append(
                    if (resolved != null) {
                        "  RESUELTO a: ${resolved.flattenToString()}\n"
                    } else {
                        "  NO RESUELTO (el sistema no encuentra la pantalla de permisos)\n"
                    },
                )
            } catch (e: Exception) {
                sb.append("Error al construir el intent de permisos: $e\n")
            }

            // 3) Estado del proveedor.
            val detail = withContext(Dispatchers.IO) { manager.providerDetail() }
            sb.append("\nProveedor: ${detail.packageName}\n")
            sb.append("  instalado v${detail.installedVersionCode ?: "NO"}\n")
            sb.append("  mínimo requerido v${detail.minRequiredVersionCode}\n")
            sb.append("  SDK status: ${manager.sdkStatus()}\n")

            // 4) Launcher del proveedor (¿existe activity principal?)
            val launcherIntent = android.content.Intent(android.content.Intent.ACTION_MAIN).apply {
                addCategory(android.content.Intent.CATEGORY_LAUNCHER)
                `package` = detail.packageName
            }
            val launcher = launcherIntent.resolveActivity(packageManager)
            sb.append("  launcher HC: ${if (launcher != null) launcher.flattenToString() else "NO existe (por eso no hay icono)"}\n")

            statusView.text = sb.toString()
        }
    }

    private fun showSyncState() {
        lifecycleScope.launch {
            val infos = withContext(Dispatchers.IO) {
                kotlinx.coroutines.flow.first(
                    androidx.work.WorkManager.getInstance(this@MainActivity)
                        .getWorkInfosForUniqueWorkFlow("health_connect_sync"),
                )
            }
            val sb = StringBuilder("Estado del worker de sync:\n")
            if (infos.isEmpty()) {
                sb.append("  nunca se programó (pulsa 'Guardar destino' o 'Sincronizar ahora')\n")
            } else {
                val info = infos.first()
                sb.append("  estado: ${info.state}\n")
                sb.append("  intentos: ${info.runAttemptCount}\n")
                info.outputData.keyValueMap.forEach { (k, v) -> sb.append("  $k: $v\n") }
            }
            statusView.text = sb.toString()
            android.widget.Toast.makeText(this@MainActivity, "Estado en el panel superior", android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    private fun statusText(status: TypeStatus): String = when (status) {
        TypeStatus.READY, TypeStatus.SYNCED -> "OK "
        TypeStatus.NOT_AUTHORIZED -> "SIN"
        TypeStatus.NOT_AVAILABLE -> "N/D"
        TypeStatus.ERROR -> "ERR"
    }

    companion object {
        private const val RATIONALE_ACTION = "androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE"
    }
}

private class ActivityResultCallbackAdapter(
    private val onResult: (Set<String>) -> Unit,
) : androidx.activity.result.ActivityResultCallback<Set<String>> {
    override fun onActivityResult(result: Set<String>) = onResult(result)
}
