package com.jhomc.healthsync

import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack

/**
 * Reproductor estático del pacer: un `AudioTrack MODE_STATIC` por buffer de
 * fase, precargado una vez y reutilizado cada ciclo (sin hilos, sin trozos,
 * sin reloj). Mismo tubo que el piip de descanso (`TrainingDiaryViewModel`):
 * sonar = `play()` atómico, así que el altavoz nunca se queda sin datos.
 *
 * - 22050 Hz y `STREAM_MUSIC` fijos (la nativa deja mudo este aparato).
 * - Los REST no suenan: el servicio llama [stopCurrent] (silencio por
 *   ausencia, sin pistas de ceros).
 * - Pausa = `pause()` (retiene cabezal: continuar retoma el punto exacto);
 *   cambio de fase = `stop()` anterior + `play()` nueva desde cero (los
 *   bordes ya caen a ~0 por los fundidos del buffer).
 * - Cierre a mitad de fase (timer/stop) = [stopAllWithFade] (rampa corta de
 *   volumen para no chascar).
 */
class StaticPhasePlayer internal constructor(
    private val slots: List<StaticSlot?>,
) {
    interface StaticSlot {
        fun playFromStart()
        fun pause()
        fun resume()
        fun stop()
        fun release()
        fun fadeOutAndStop()
    }

    /** True si algún buffer no cargó (sin audio; el llamante avisa una vez). */
    var broken: Boolean = slots.any { it == null }
        private set

    private var current: Int = -1

    /** Suena `i` desde cero; si ya suena, nada (sin reinicios). */
    fun playAt(i: Int) {
        if (i == current) return
        slots.getOrNull(current)?.stop()
        current = i
        val slot = slots.getOrNull(i)
        if (slot == null) {
            broken = true
            return
        }
        runCatching { slot.playFromStart() }.onFailure { broken = true }
    }

    /** Silencio por ausencia (REST): para lo que suena sin arrancar nada. */
    fun stopCurrent() {
        slots.getOrNull(current)?.let { runCatching { it.stop() } }
        current = -1
    }

    /** Pausa: retiene el cabezal (continuar retoma exacto). */
    fun pause() {
        slots.getOrNull(current)?.let { runCatching { it.pause() } }
    }

    /** Continúa desde el cabezal retenido (nada si estaba en REST). */
    fun resume() {
        slots.getOrNull(current)?.let { runCatching { it.resume() } }
    }

    /** Cierre a mitad de fase: fundido corto y stop (solo al terminar). */
    fun stopAllWithFade() {
        slots.getOrNull(current)?.let { runCatching { it.fadeOutAndStop() } }
        current = -1
    }

    fun release() {
        slots.forEach { runCatching { it?.release() } }
        current = -1
    }

    companion object {
        /** Crea el reproductor cargando cada PCM una vez (fábrica inyectable). */
        fun create(
            pcms: List<ShortArray>,
            factory: (ShortArray) -> StaticSlot? = ::androidSlot,
        ): StaticPhasePlayer = StaticPhasePlayer(pcms.map { runCatching { factory(it) }.getOrNull() })

        internal fun androidSlot(pcm: ShortArray): StaticSlot? {
            val track = runCatching {
                AudioTrack(
                    AudioManager.STREAM_MUSIC, SessionTone.SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, pcm.size * 2, AudioTrack.MODE_STATIC,
                )
            }.getOrNull() ?: return null
            val written = runCatching { track.write(pcm, 0, pcm.size) }.getOrDefault(0)
            if (written != pcm.size) {
                runCatching { track.release() }
                return null
            }
            return AndroidStaticSlot(track)
        }
    }
}

/** Slot real sobre `AudioTrack` estático. */
internal class AndroidStaticSlot(private val track: AudioTrack) : StaticPhasePlayer.StaticSlot {
    override fun playFromStart() {
        runCatching {
            track.stop()
            track.reloadStaticData()
            track.play()
        }
    }

    override fun pause() {
        runCatching { track.pause() }
    }

    override fun resume() {
        runCatching { track.play() }
    }

    override fun stop() {
        runCatching { track.stop() }
    }

    override fun release() {
        runCatching {
            track.stop()
            track.flush()
            track.release()
        }
    }

    override fun fadeOutAndStop() {
        runCatching {
            // Rampa 1→0 en ~120 ms: el corte a mitad de pendiente no chasca.
            repeat(6) { step ->
                track.setVolume(1f - (step + 1) / 6f)
                Thread.sleep(20)
            }
            track.stop()
            track.setVolume(1f)
        }.onFailure {
            runCatching { track.stop() }
        }
    }
}
