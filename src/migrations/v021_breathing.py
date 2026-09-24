"""v021 — sesiones de respiración pautada (B5.0, app móvil).

Tabla append-only `breathing_sessions`: el móvil ejecuta el pacer
(inhale/hold/exhale/hold + timer + rampa) y persiste cada sesión con un
`client_session_id` UUID para idempotencia de reintentos. El servidor
recalcula `ciclos_completados`/`bpm_medio`/`fecha` (nunca confía en el
cliente). `duracion_planeada_sec` NULL = Timer Off (libre).
`fecha` = día de inicio (las sesiones que cruzan medianoche se atribuyen
al día de inicio; ver plan B5.2). `hc_id` reservado para la
reconciliación con Health Connect (B5.1). Sin journal de undo en v1:
append-only + DELETE idempotente es la red (divergencia documentada en
training-api-contract.md §B5). Idempotente.
"""

VERSION = 21
NAME = "breathing"


def migrate(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS breathing_sessions (
          id INTEGER PRIMARY KEY,
          client_session_id TEXT NOT NULL UNIQUE,
          fecha TEXT NOT NULL,
          start_epoch_ms INTEGER NOT NULL CHECK (start_epoch_ms >= 0),
          end_epoch_ms INTEGER NOT NULL CHECK (end_epoch_ms >= start_epoch_ms),
          time_zone_offset_minutes INTEGER NOT NULL
            CHECK (time_zone_offset_minutes BETWEEN -840 AND 840),
          duracion_planeada_sec INTEGER NULL
            CHECK (duracion_planeada_sec IS NULL
                   OR duracion_planeada_sec BETWEEN 30 AND 7200),
          duracion_real_sec INTEGER NOT NULL
            CHECK (duracion_real_sec BETWEEN 5 AND 14400),
          inhale_s REAL NOT NULL CHECK (inhale_s BETWEEN 0.5 AND 60),
          hold_in_s REAL NOT NULL DEFAULT 0 CHECK (hold_in_s BETWEEN 0 AND 60),
          exhale_s REAL NOT NULL CHECK (exhale_s BETWEEN 0.5 AND 60),
          hold_out_s REAL NOT NULL DEFAULT 0 CHECK (hold_out_s BETWEEN 0 AND 60),
          ramp_sec INTEGER NULL
            CHECK (ramp_sec IS NULL OR ramp_sec BETWEEN 30 AND 7200),
          end_inhale_s REAL NULL,
          end_hold_in_s REAL NULL,
          end_exhale_s REAL NULL,
          end_hold_out_s REAL NULL,
          ciclos_completados INTEGER NOT NULL CHECK (ciclos_completados >= 1),
          bpm_medio REAL NOT NULL,
          completada INTEGER NOT NULL DEFAULT 1 CHECK (completada IN (0, 1)),
          hc_id TEXT NULL,
          origen TEXT NOT NULL DEFAULT 'android',
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_breathing_sessions_fecha ON breathing_sessions(fecha)"
    )
