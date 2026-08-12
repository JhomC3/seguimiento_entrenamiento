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
import kotlinx.coroutines.flow.first
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
        // Mientras dure la investigación de la cuota: los workers cancelados
        // al arrancar evitan reintentos de fondo que mantienen el rate limit.
        SyncScheduler.cancelAll(this)
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

        val directSyncButton = Button(this).apply {
            text = "Sincronizar AHORA (directo, sin WorkManager)"
            setOnClickListener { runDirectSync() }
        }
        root.addView(directSyncButton)

        val binderDiagButton = Button(this).apply {
            text = "Diagnóstico del binder (paso a paso)"
            setOnClickListener { runBinderDiagnostics() }
        }
        root.addView(binderDiagButton)

        val inventoryButton = Button(this).apply {
            text = "Inventario HOY (Health Connect)"
            setOnClickListener { runTodayInventory() }
        }
        root.addView(inventoryButton)

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
                (manager.gateway() as? RealHealthConnectGateway)?.invalidatePermissionCache()
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
                // El token guardado nunca se vuelca al campo (seguridad);
                // se muestra un marcador para que no parezca vacío.
                tokenInput.setText(if (tokenSet) "(guardado — no se muestra)" else "")
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
            val wm = androidx.work.WorkManager.getInstance(this@MainActivity)
            val periodic = withContext(Dispatchers.IO) {
                wm.getWorkInfosForUniqueWorkFlow("health_connect_sync").first()
            }
            val oneTime = withContext(Dispatchers.IO) {
                wm.getWorkInfosForUniqueWorkFlow("health_connect_sync_now").first()
            }
            val sb = StringBuilder("Estado del worker de sync:\n")
            sb.append("Periódico (1h): ")
            sb.append(periodic.firstOrNull()?.state ?: "nunca programado")
            sb.append("\n")
            val now = oneTime.firstOrNull()
            if (now == null) {
                sb.append("Manual: nunca ejecutado (pulsa 'Sincronizar ahora')\n")
            } else {
                sb.append("Manual: ${now.state}\n")
                sb.append("  intentos: ${now.runAttemptCount}\n")
                now.outputData.keyValueMap.forEach { (k, v) -> sb.append("  $k: $v\n") }
            }
            statusView.text = sb.toString()
            android.widget.Toast.makeText(this@MainActivity, "Estado en el panel superior", android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    /** Ejecuta el pipeline completo en primer plano; resultado visible al instante. */
    private fun runDirectSync() {
        lifecycleScope.launch {
            showMessage("Sincronizando…")
            try {
                val report = withContext(Dispatchers.IO) {
                    SyncExecutor.run(this@MainActivity) { stage ->
                        // El callback corre en el hilo IO: sube al main el progreso.
                        runOnUiThread { statusView.text = "Sincronizando… $stage" }
                    }
                }
                if (report.notice == "rate_limited") {
                    statusView.text = "Cuota de Health Connect agotada (rate limit).\n" +
                        "Health Connect limita las llamadas por hora de las apps nuevas.\n" +
                        "Espera unos minutos y vuelve a pulsar el botón."
                    return@launch
                }
                if (report.notice == "foreground_requerido") {
                    statusView.text = "Health Connect requiere que la app esté en primer plano\n" +
                        "para leer Steps/StepsCadence.\n" +
                        "Mantén la app abierta con la pantalla encendida al sincronizar,\n" +
                        "o activa 'Acceso en segundo plano' en Health Connect →\n" +
                        "Permisos de las apps → HealthSync."
                    return@launch
                }
                val msg = buildString {
                    append("Tipos leídos: ${report.typesSynced} | Entregados: ${report.delivered}")
                    if (report.failed > 0) append(" | Fallos: ${report.failed}")
                    report.notice?.let { append(" | Aviso: $it") }
                    report.permanentError?.let { append(" | Error: $it") }
                }
                showMessage(msg)
            } catch (e: Exception) {
                // Error completo con cadena de causas en el panel (sin cortes).
                statusView.text = "Error de sync:\n" + fullErrorChain(e)
            }
        }
    }

    /** Cadena de causas (x: Clase: mensaje) hasta 5 niveles. */
    private fun fullErrorChain(e: Throwable): String {
        val sb = StringBuilder()
        var current: Throwable? = e
        var depth = 0
        while (current != null && depth < 5) {
            sb.append("$depth: ${current::class.java.simpleName}: ${current.message}\n")
            current = current.cause
            depth++
        }
        return sb.toString()
    }

    /** Ejecuta el binder de Health Connect paso a paso para localizar el fallo. */
    private fun runBinderDiagnostics() {
        lifecycleScope.launch {
            val gateway = RealHealthConnectGateway(this@MainActivity)
            val sb = StringBuilder("Diagnóstico del binder (1/2/3):\n")
            // 1) Permisos concedidos (binder básico)
            try {
                val granted = withContext(Dispatchers.IO) { gateway.grantedPermissions() }
                sb.append("1. getGrantedPermissions: OK (${granted.size})\n")
                sb.append("   ${granted.joinToString(", ")}\n\n")
            } catch (e: Exception) {
                sb.append("1. getGrantedPermissions: FALLO\n${fullErrorChain(e)}\n\n")
            }
            // 2) Agregación de pasos 24h (binder + lectura de datos)
            try {
                val now = java.time.Instant.now()
                val steps = withContext(Dispatchers.IO) {
                    gateway.stepsCountTotal(now.minusSeconds(86400), now)
                }
                sb.append("2. aggregate pasos 24h: ${steps ?: "null (sin datos o sin permiso)"}\n\n")
            } catch (e: Exception) {
                sb.append("2. aggregate: FALLO\n${fullErrorChain(e)}\n\n")
            }
            // 3) Changes API (la operación más nueva del protocolo)
            try {
                withContext(Dispatchers.IO) {
                    gateway.getChangesToken(setOf(androidx.health.connect.client.records.StepsRecord::class))
                }
                sb.append("3. getChangesToken(STEPS): OK\n\n")
            } catch (e: Exception) {
                sb.append("3. getChangesToken: FALLO\n${fullErrorChain(e)}\n\n")
            }
            // 4) Lectura por rango (el modo de respaldo estructural)
            try {
                val now = java.time.Instant.now()
                val page = withContext(Dispatchers.IO) {
                    gateway.readRecords(
                        androidx.health.connect.client.records.StepsRecord::class,
                        now.minusSeconds(86400),
                        now,
                        null,
                    )
                }
                sb.append("4. readRecords(STEPS 24h): OK (${page.records.size} registros)\n")
            } catch (e: Exception) {
                sb.append("4. readRecords: FALLO\n${fullErrorChain(e)}\n")
            }
            statusView.text = sb.toString()
        }
    }

    /** Qué datos hay HOY en Health Connect, por tipo (una página por tipo). */
    private fun runTodayInventory() {
        lifecycleScope.launch {
            statusView.text = "Inventario…"
            val inventory = HealthInventory(RealHealthConnectGateway(this@MainActivity))
            val rows = withContext(Dispatchers.IO) { inventory.todayInventory() }
            val sb = StringBuilder("Inventario de hoy (${rows.size} tipos con permiso):\n\n")
            for (r in rows) {
                sb.append(r.typeName)
                sb.append(": ${r.recordsToday} reg")
                sb.append(if (r.hasMore) " +más (denso)" else "")
                r.aggregateTotal?.let { sb.append(" | total hoy: $it") }
                r.error?.let { sb.append(" | ERROR: $it") }
                sb.append("\n")
            }
            statusView.text = sb.toString()
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
