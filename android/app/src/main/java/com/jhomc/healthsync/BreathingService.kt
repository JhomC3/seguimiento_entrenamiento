package com.jhomc.healthsync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.TimeZone
import java.util.UUID

/** Estado observable de la sesión en curso (la Activity lo colecta). */
sealed interface BreathRunState {
    data object Idle : BreathRunState
    data class Running(
        val phase: BreathPhase,
        /** 0..1 transcurrido de la fase (círculo). */
        val fraction: Float,
        /** ms restantes de fase (texto). */
        val phaseRemainingMs: Long,
        /** ms restantes totales; -1 con Timer Off. */
        val totalRemainingMs: Long,
        /** ms transcurridos activos (reloj en modo Libre). */
        val elapsedMs: Long,
        val cycle: Int,
        /** Media de la sesión con la fórmula del servidor (`simulate`). */
        val avgBpm: Double,
        /** Fase siguiente (para mostrarla durante el REST). */
        val nextPhase: BreathPhase,
    ) : BreathRunState
    data class Paused(
        val phase: BreathPhase,
        val fraction: Float,
        val phaseRemainingMs: Long,
        val totalRemainingMs: Long,
        val cycle: Int,
    ) : BreathRunState
    data class Finished(
        val clientSessionId: String,
        val ciclos: Int,
        val minutos: Double,
        val resumen: String,
    ) : BreathRunState
}

/**
 * Pacer en primer plano (tipo mediaPlayback: cues audibles): sigue aunque se
 * apague la pantalla o se abra otra app, como la app original. El tiempo lo
 * lleva [Pacer] (pausar es no avanzar: reanudar continúa con el restante
 * exacto); el servicio solo orquesta cues, notificación y persistencia.
 * Solo cuenta el tiempo ACTIVO (la pausa no engorda la sesión que ve el
 * servidor).
 */
class BreathingService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var loop: Job? = null
    private var player: StaticPhasePlayer? = null
    /** Costura de tests: fábrica del reproductor (producción = estático real). */
    internal var playerFactory: (List<ShortArray>) -> StaticPhasePlayer =
        { pcms -> StaticPhasePlayer.create(pcms) }
    private var buffers: List<SessionTone.PhaseBuffer> = emptyList()
    private var buffersAttack: List<SessionTone.PhaseBuffer> = emptyList()
    private var bounds: LongArray = longArrayOf()
    private var cycleMs: Long = 0
    private var vibrator: BreathingVibration? = null
    private var soundOn: Boolean = true
    private var soundStyle: SoundStyle = SoundStyle.AIRE
    private var soundBroken: Boolean = false
    private var vibrationOn: Boolean = false
    private var pacer: Pacer? = null
    private var pattern: BreathingPattern? = null
    private var engine: BreathingEngine? = null
    /** BPM en vuelo: solo se recalcula cuando cambian los segundos. */
    private var bpmCacheSecs: Long = Long.MIN_VALUE
    private var bpmCache: Double = 0.0
    private var totalS: Int = -1
    private var startMsWall: Long = 0L
    private var activeMs: Long = 0L
    private var lastPhase: BreathPhase? = null
    private var lastNotifiedSec: Long = -1

    override fun onCreate() {
        super.onCreate()
        createChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> {
                toggle()
                return START_STICKY
            }
            ACTION_STOP -> {
                // Stop también guarda: la sesión parcial mide adherencia.
                finishRun()
                return START_NOT_STICKY
            }
            ACTION_START -> {
                if (loop?.isActive == true || pacer != null) return START_STICKY
                val parsed = runCatching {
                    BreathingPattern.fromJson(JSONObject(intent.getStringExtra(EXTRA_PATTERN) ?: "{}"))
                }.getOrNull() ?: return START_NOT_STICKY
                pattern = parsed
                totalS = intent.getIntExtra(EXTRA_TOTAL_S, -1)
                startMsWall = System.currentTimeMillis()
                activeMs = 0L
                lastPhase = null
                lastNotifiedSec = -1
                audioWarned = false
                pacer = Pacer(parsed, totalS)
                engine = BreathingEngine(parsed)
                bpmCacheSecs = Long.MIN_VALUE
                bpmCache = 0.0
                soundOn = intent.getBooleanExtra(EXTRA_SOUND, true)
                vibrationOn = intent.getBooleanExtra(EXTRA_VIBRATION, false)
                val style = runCatching {
                    SoundStyle.valueOf(intent.getStringExtra(EXTRA_TIMBRE) ?: "AIRE")
                }.getOrDefault(SoundStyle.AIRE)
                soundStyle = style
                soundBroken = false
                player = null
                vibrator = BreathingVibration(this)
                startForegroundCompat("Respiración en curso…")
                launchLoop()
                return START_STICKY
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        loop?.cancel()
        scope.cancel()
        runCatching { player?.release() }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /** Toque del círculo / acción de la notificación: pausa ↔ continúa. */
    private fun toggle() {
        val pacer = pacer ?: return
        if (loop?.isActive == true) {
            loop?.cancel()
            loop = null
            // Pausa: retiene el cabezal (continuar retoma el punto exacto).
            player?.pause()
            val tick = pacer.snapshot()
            _state.value = BreathRunState.Paused(
                phase = tick.phase,
                fraction = tick.fraction,
                phaseRemainingMs = tick.phaseRemainingMs,
                totalRemainingMs = tick.totalRemainingMs,
                cycle = tick.cycle,
            )
            notify("En pausa: ${tick.phase.label}")
        } else if (!pacer.finished()) {
            player?.resume()
            launchLoop()
        }
    }

    private var audioWarned = false

    private fun toastMain(msg: String) {
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            runCatching {
                android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun warnAudioOnce() {
        if (audioWarned) return
        audioWarned = true
        android.util.Log.e("Breathing", "sumidero de audio roto")
        toastMain("Sin audio en este móvil (sigue la guía visual).")
    }

    /**
     * Conmuta el estático que toca según el reloj activo: si cambia la fase,
     * para la anterior y arranca la nueva desde cero (los bordes ya caen a
     * ~0 por los fundidos del buffer); el REST es silencio por ausencia. Si
     * es la misma, nada (sin reinicios: pausa/continuar no se desfasas).
     */
    private fun switchAudio() {
        if (!soundOn || soundBroken) return
        val player = player ?: return
        if (buffers.isEmpty() || cycleMs <= 0) return
        // Primer ciclo: versión con ataque; después, la estable.
        val firstCycle = activeMs < cycleMs
        val pos = activeMs % cycleMs
        val idx = buffers.indices.firstOrNull { pos < bounds[it + 1] } ?: (buffers.size - 1)
        val buf = buffers[idx]
        if (buf.phase == BreathPhase.REST) {
            player.stopCurrent()
            return
        }
        player.playAt(if (firstCycle) idx else buffers.size + idx)
        if (player.broken) {
            soundBroken = true
            warnAudioOnce()
        }
    }

    private fun launchLoop() {
        loop = scope.launch {
            val pat = pattern ?: return@launch
            if (buffers.isEmpty()) {
                // Sonidos del ciclo (una vez por arranque; cada fase suena igual siempre).
                // El primer ciclo entra suave (ataque global, como siempre).
                val tone = SessionTone(soundStyle, pat)
                buffersAttack = tone.cycleBuffers(withAttack = true)
                buffers = tone.cycleBuffers()
                val b = LongArray(buffers.size + 1)
                for (i in buffers.indices) b[i + 1] = b[i] + buffers[i].durMs
                bounds = b
                cycleMs = b.last()
            }
            if (cycleMs <= 0) return@launch
            if (soundOn && player == null) {
                // Ataque + estable precargados (cada fase suena igual siempre).
                val pcms = buffersAttack.map { it.pcm } + buffers.map { it.pcm }
                val created = runCatching { playerFactory(pcms) }.getOrNull()
                player = created
                if (created == null || created.broken) {
                    soundBroken = true
                    warnAudioOnce()
                }
            }
            // Reloj de pared por iteración: el trabajo de cada vuelta dura
            // MÁS de 50 ms reales; con deltas reales el pacer, el display y
            // el audio avanzan juntos sin deriva.
            var last = android.os.SystemClock.elapsedRealtime()
            while (true) {
                val pacer = pacer ?: break
                val now = android.os.SystemClock.elapsedRealtime()
                val delta = (now - last).coerceIn(0L, 2000L)
                last = now
                val tick = pacer.advance(delta)
                activeMs += delta
                if (tick.phase != lastPhase) {
                    // La marca es entrar al REST (o arrancar): al salir no se repite.
                    val enteringRest = tick.phase == BreathPhase.REST
                    val starting = lastPhase == null
                    lastPhase = tick.phase
                    if (vibrationOn && (enteringRest || starting)) runCatching { vibrator?.pulse() }
                }
                switchAudio()
                _state.value = BreathRunState.Running(
                    phase = tick.phase,
                    fraction = tick.fraction,
                    phaseRemainingMs = tick.phaseRemainingMs,
                    totalRemainingMs = tick.totalRemainingMs,
                    elapsedMs = tick.totalElapsedMs,
                    cycle = tick.cycle,
                    avgBpm = avgBpm(tick.totalElapsedMs),
                    nextPhase = tick.nextPhase,
                )
                val sec = tick.totalElapsedMs / 1000
                if (sec != lastNotifiedSec) {
                    lastNotifiedSec = sec
                    val label = if (tick.phase == BreathPhase.REST) {
                        "Cambio: ${tick.nextPhase.label}"
                    } else {
                        "${tick.phase.label} · ciclo ${tick.cycle}"
                    }
                    notify("Respiración: $label")
                }
                if (tick.finished) break
                delay(TICK_MS)
            }
            finishRun()
        }
    }

    /**
     * BPM con la fórmula del servidor: `simulate(pattern, secs)` sobre los
     * segundos activos redondeados como los calcula el backend — con los
     * mismos inputs, display y API devuelven el mismo número.
     */
    private fun avgBpm(elapsedMs: Long): Double {
        val engine = engine ?: return 0.0
        val secs = secsFromMs(elapsedMs)
        if (secs != bpmCacheSecs) {
            bpmCacheSecs = secs
            bpmCache = engine.avgBpm(secs.toInt())
        }
        return bpmCache
    }

    private fun finishRun() {
        val pattern = pattern
        val pacer = pacer
        this.pacer = null
        this.pattern = null
        // Cierre con fundido (el timer puede cortar a mitad de pendiente).
        runCatching { player?.stopAllWithFade() }
        loop?.cancel()
        loop = null
        if (pattern == null || pacer == null) {
            _state.value = BreathRunState.Idle
            getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
            stopSelf()
            return
        }
        val totalS = totalS
        val startMs = startMsWall
        val active = activeMs
        scope.launch(Dispatchers.IO) {
            try {
                persist(pattern, totalS, startMs, active)
            } catch (e: Exception) {
                android.util.Log.e("Breathing", "persist falló: ${e.message}", e)
                _state.value = BreathRunState.Idle
            } finally {
                runCatching { player?.release() }
                player = null
                buffers = emptyList()
                buffersAttack = emptyList()
                getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
                stopSelf()
            }
        }
    }

    private suspend fun persist(pattern: BreathingPattern, totalS: Int, startMs: Long, activeMs: Long) {
        // Sesiones de menos de un ciclo no se guardan (toque accidental).
        val realS = (activeMs / 1000).toInt()
        if (realS < 5) {
            _state.value = BreathRunState.Idle
            return
        }
        val endMs = startMs + activeMs
        val plannedS = if (totalS > 0) totalS else null
        val completed = if (plannedS == null) true else activeMs >= (plannedS * 800L)
        val finished = FinishedBreathing(
            clientSessionId = UUID.randomUUID().toString(),
            startMs = startMs,
            endMs = endMs,
            tzOffsetMin = TimeZone.getDefault().getOffset(startMs) / 60000,
            plannedS = plannedS,
            pattern = pattern,
            completed = completed,
        )
        val dao = HealthDatabaseBuilder.get(this@BreathingService).breathingDao()
        val repo = BreathingRepository(dao)
        val id = repo.finishSession(finished)
        if (id == null) {
            // Ni un ciclo completo (misma regla que el servidor): se avisa y no se guarda.
            toastMain("Muy corta (ni un ciclo): no se guarda.")
            _state.value = BreathRunState.Idle
            return
        }
        val row = dao.sessionById(id)
        val minutos = ((row?.realS ?: 0) / 60.0).let { kotlin.math.round(it * 10) / 10.0 }
        // Sin espejo HC aquí: solo "Guardar sesión" envía (la Activity).
        _state.value = BreathRunState.Finished(
            clientSessionId = id,
            ciclos = row?.ciclos ?: 0,
            minutos = minutos,
            resumen = "%.1f/%.1f/%s/%s".format(
                pattern.inhaleS, pattern.holdInS, pattern.exhaleS, pattern.holdOutS,
            ).replace(".0", ""),
        )
    }

    private fun startForegroundCompat(text: String) {
        val notification = buildNotification(this, text, paused = false)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun notify(text: String) {
        val paused = _state.value is BreathRunState.Paused
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification(this, text, paused))
    }

    companion object {
        const val CHANNEL_ID = "breathing_pacer"
        const val NOTIFICATION_ID = 2
        const val ACTION_START = "com.jhomc.healthsync.breathing.START"
        const val ACTION_TOGGLE = "com.jhomc.healthsync.breathing.TOGGLE"
        const val ACTION_STOP = "com.jhomc.healthsync.breathing.STOP"
        const val EXTRA_PATTERN = "pattern_json"
        const val EXTRA_TOTAL_S = "total_s"
        const val EXTRA_SOUND = "sound"
        const val EXTRA_VIBRATION = "vibration"
        const val EXTRA_TIMBRE = "timbre"
        const val TICK_MS = 50L

        private val _state = MutableStateFlow<BreathRunState>(BreathRunState.Idle)
        val state: StateFlow<BreathRunState> = _state

        fun start(
            context: Context,
            pattern: BreathingPattern,
            totalS: Int,
            sound: Boolean,
            vibration: Boolean,
            timbre: SoundStyle = SoundStyle.AIRE,
        ) {
            if (_state.value is BreathRunState.Running || _state.value is BreathRunState.Paused) return
            _state.value = BreathRunState.Running(BreathPhase.INHALE, 0f, 0, 0, 0, 1, 0.0, BreathPhase.INHALE)
            val intent = Intent(context, BreathingService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_PATTERN, pattern.toJson().toString())
                putExtra(EXTRA_TOTAL_S, totalS)
                putExtra(EXTRA_SOUND, sound)
                putExtra(EXTRA_VIBRATION, vibration)
                putExtra(EXTRA_TIMBRE, timbre.name)
            }
            context.startForegroundService(intent)
        }

        fun toggle(context: Context) {
            context.startService(Intent(context, BreathingService::class.java).apply { action = ACTION_TOGGLE })
        }

        fun stop(context: Context) {
            context.startService(Intent(context, BreathingService::class.java).apply { action = ACTION_STOP })
        }

        fun consumeFinished() {
            if (_state.value is BreathRunState.Finished) _state.value = BreathRunState.Idle
        }

        /** Aislamiento entre tests: el estado es compartido por la JVM. */
        @androidx.annotation.VisibleForTesting
        internal fun forceState(state: BreathRunState) {
            _state.value = state
        }

        fun createChannel(context: Context) {
            context.getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Pacer de respiración", NotificationManager.IMPORTANCE_LOW),
            )
        }

        fun buildNotification(context: Context, text: String, paused: Boolean): Notification {
            fun actionIntent(action: String, code: Int) = android.app.PendingIntent.getService(
                context, code,
                Intent(context, BreathingService::class.java).apply { this.action = action },
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE,
            )
            return NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("Respiración")
                .setContentText(text)
                .addAction(
                    android.R.drawable.ic_media_play,
                    if (paused) "Continuar" else "Pausar",
                    actionIntent(ACTION_TOGGLE, 1),
                )
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Terminar", actionIntent(ACTION_STOP, 2))
                .setOngoing(true)
                .build()
        }
    }
}
