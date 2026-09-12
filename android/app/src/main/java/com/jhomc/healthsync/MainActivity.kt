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
import androidx.lifecycle.repeatOnLifecycle
import com.jhomc.healthsync.data.SecureTargetStore
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val manager: HealthConnectManager by lazy {
        HealthConnectManager(RealHealthConnectGateway(this))
    }

    private val targetStore: SecureTargetStore by lazy { SecureTargetStore(this) }

    private lateinit var permissionLauncher: ActivityResultLauncher<Set<String>>
    private lateinit var notificationPermissionLauncher: ActivityResultLauncher<String>
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (intent?.action == RATIONALE_ACTION) {
            showPrivacyPolicy()
            return
        }
        // Worker periódico: 1 h, sincroniza solo tipos vencidos (agenda por
        // ventanas). El botón "Sincronizar AHORA" fuerza todo al instante.
        SyncScheduler.schedulePeriodic(this)
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
        statusView.asSummary()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(statusView)
        }

        // --- Permisos esenciales (un solo diálogo con los 17) ---
        root.addView(Button(this).apply {
            text = "Permisos esenciales"
            setOnClickListener { requestPermissions(manager.corePermissions()) }
        })

        // --- Sincronizar todo ahora (fuerza, pantalla apagada OK) ---
        root.addView(primaryButton("Sincronizar AHORA").apply {
            setOnClickListener { runDirectSync() }
        })

        // --- Diario de entrenamiento (API v1, ver + editar por fecha) ---
        root.addView(Button(this).apply {
            text = "Diario de entrenamiento"
            setOnClickListener {
                startActivity(android.content.Intent(this@MainActivity, TrainingDiaryActivity::class.java))
            }
        })

        setContentView(ScrollView(this).apply { addView(root) })

        permissionLauncher = registerForActivityResult(
            permissionContract(),
            ActivityResultCallbackAdapter { granted ->
                (manager.gateway() as? RealHealthConnectGateway)?.invalidatePermissionCache()
                statusView.text = "Permisos concedidos: ${granted.size}."
            },
        )
        notificationPermissionLauncher = registerForActivityResult(
            androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
        ) { /* sin notificación visible el servicio sigue funcionando */ }
        observeSyncProgress()
        loadTarget()
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
                "Usa 'Permisos esenciales' y concede los permisos desde allí, " +
                "o activa 'Abrir ventanas en segundo plano' para HealthSync en Ajustes de MIUI."
        }
    }

    /**
     * Siembra el destino preconfigurado (build debug) o avisa de que falta.
     * El worker de sync lee URL/token directamente del store, no de la UI.
     */
    private fun loadTarget() {
        lifecycleScope.launch {
            try {
                val existing = withContext(kotlinx.coroutines.Dispatchers.IO) { targetStore.target() }
                if (existing != null) {
                    statusView.text = "Destino: preconfigurado (${existing.url})"
                    return@launch
                }
                val url = BuildConfig.DEFAULT_SYNC_URL
                val token = BuildConfig.DEFAULT_SYNC_TOKEN
                if (url.isEmpty() || token.isEmpty()) {
                    statusView.text = "Sin destino configurado (build release sin pairing).\n" +
                        "Instala el APK debug para sincronizar."
                    return@launch
                }
                withContext(kotlinx.coroutines.Dispatchers.IO) {
                    targetStore.saveTarget(url, "default")
                    targetStore.saveToken(token)
                }
                statusView.text = "Destino: preconfigurado (${url})"
            } catch (e: Exception) {
                statusView.text = "No se pudo leer la configuración: $e"
            }
        }
    }

    /** Mensaje visible siempre (Toast) + en el panel de estado. */
    private fun showMessage(message: String) {
        statusView.text = message
        android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show()
    }

    /**
     * Ejecuta el pipeline en un servicio en primer plano: sigue trabajando
     * aunque se apague la pantalla (Health Connect acepta las lecturas porque
     * el servicio mantiene la app activa). El panel se actualiza vía
     * [SyncService.progress].
     */
    private fun runDirectSync() {
        requestNotificationPermissionIfNeeded()
        SyncService.start(this)
        showMessage("Sincronizando… (sigue aunque se apague la pantalla)")
    }

    /** Observa el progreso del servicio para pintarlo en el panel. */
    private fun observeSyncProgress() {
        lifecycleScope.launch {
            repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.STARTED) {
                SyncService.progress.collect { stage ->
                    when (stage) {
                        is SyncStage.Idle -> {}
                        is SyncStage.Running -> statusView.text = "Sincronizando… ${stage.stage}"
                        is SyncStage.Done -> showSyncResult(stage.report)
                        is SyncStage.Failed -> statusView.text = "Error de sync:\n${stage.error}"
                    }
                }
            }
        }
    }

    private fun showSyncResult(report: SyncReport) {
        if (report.notice == "rate_limited") {
            statusView.text = "Cuota de Health Connect agotada (rate limit).\n" +
                "Health Connect limita las llamadas por hora de las apps nuevas.\n" +
                "Espera unos minutos y vuelve a pulsar el botón."
            return
        }
        if (report.notice == "foreground_requerido") {
            statusView.text = "Health Connect requiere que la app esté en primer plano\n" +
                "para leer Steps/StepsCadence.\n" +
                "Si aparece, activa 'Acceso en segundo plano' en Health Connect →\n" +
                "Permisos de las apps → HealthSync."
            return
        }
        if (report.notice == "timeout_lectura") {
            statusView.text = "Health Connect no respondió (timeout de lectura).\n" +
                "El progreso ya guardado no se pierde: vuelve a pulsar el botón\n" +
                "y continúa donde quedó."
            return
        }
        SyncService.noticeMessage(report)?.let {
            statusView.text = it
            return
        }
        statusView.text = SyncService.summaryOf(report)
    }

    /** Android 13+: pide el permiso de notificaciones la primera vez. */
    private fun requestNotificationPermissionIfNeeded() {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) !=
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
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
