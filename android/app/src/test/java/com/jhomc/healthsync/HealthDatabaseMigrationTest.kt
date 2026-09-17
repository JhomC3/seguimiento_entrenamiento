package com.jhomc.healthsync

import android.content.Context
import androidx.room.Room
import androidx.sqlite.db.SimpleSQLiteQuery
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_1_2
import com.jhomc.healthsync.data.MIGRATION_2_3
import com.jhomc.healthsync.data.MIGRATION_3_4
import com.jhomc.healthsync.data.MIGRATION_4_5
import com.jhomc.healthsync.data.MIGRATION_5_6
import com.jhomc.healthsync.data.MIGRATION_6_7
import com.jhomc.healthsync.data.MIGRATION_7_8
import com.jhomc.healthsync.data.MIGRATION_8_9
import com.jhomc.healthsync.data.MIGRATION_9_10
import com.jhomc.healthsync.data.MIGRATION_10_11
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthDatabaseMigrationTest {

    private fun createV1(db: SupportSQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE health_records (hc_id TEXT NOT NULL PRIMARY KEY, record_type TEXT NOT NULL, " +
                "start_epoch_ms INTEGER NOT NULL, end_epoch_ms INTEGER, last_modified_epoch_ms INTEGER NOT NULL, " +
                "data_origin_package TEXT, time_zone_offset_minutes INTEGER, payload_schema_version INTEGER NOT NULL, " +
                "value_json TEXT NOT NULL, deleted_at_epoch_ms INTEGER, source_updated_at_epoch_ms INTEGER NOT NULL)"
        )
        db.execSQL(
            "CREATE TABLE health_sync_state (record_type TEXT NOT NULL PRIMARY KEY, changes_token TEXT, " +
                "permission_granted INTEGER NOT NULL DEFAULT 0, last_successful_read_at_epoch_ms INTEGER)"
        )
        db.execSQL(
            "CREATE TABLE sync_targets (target_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, url TEXT NOT NULL, " +
                "name TEXT NOT NULL, active INTEGER NOT NULL, created_at_epoch_ms INTEGER NOT NULL)"
        )
        db.execSQL(
            "CREATE TABLE health_outbox (target_id INTEGER NOT NULL, hc_id TEXT NOT NULL, operation TEXT NOT NULL, " +
                "revision INTEGER NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0, created_at_epoch_ms INTEGER NOT NULL, " +
                "PRIMARY KEY (target_id, hc_id))"
        )
        db.execSQL(
            "CREATE TABLE sync_meta (meta_key TEXT NOT NULL PRIMARY KEY, meta_value TEXT NOT NULL)"
        )
    }

    /** v2 real: v1 + columnas de scheduling + sync_meta (esquema actual del teléfono). */
    private fun upgradeToV2(db: SupportSQLiteDatabase) {
        MIGRATION_1_2.migrate(db)
    }

    private fun openV2Database(context: Context, name: String): SupportSQLiteDatabase {
        context.deleteDatabase(name)
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name(name)
                .callback(object : SupportSQLiteOpenHelper.Callback(2) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        createV1(db)
                        upgradeToV2(db)
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build()
        )
        return helper.writableDatabase
    }

    @Test
    fun `migration v2 to v3 purges non-essential types from state records and outbox`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = openV2Database(context, "migration-v2-v3.db")
        try {
            // Estado de un tipo esencial y de uno recortado
            db.execSQL(
                "INSERT INTO health_sync_state (record_type, changes_token, permission_granted, last_successful_read_at_epoch_ms, " +
                    "next_due_at_epoch_ms, cooldown_until_epoch_ms, priority, bootstrap_page_token, " +
                    "bootstrap_start_epoch_ms, empty_runs) VALUES " +
                    "('STEPS', 'tok-steps', 1, 111, 222, NULL, 1, NULL, NULL, 0), " +
                    "('SPEED', 'tok-speed', 1, 333, NULL, NULL, 1, NULL, NULL, 0), " +
                    "('BLOOD_PRESSURE', 'tok-bp', 0, NULL, NULL, NULL, 1, NULL, NULL, 0)"
            )
            // Registros espejo: esencial, recortado y el agregado interno HR
            for ((hcId, type) in listOf(
                "hc-steps" to "STEPS",
                "hc-speed" to "SPEED",
                "hc-hr5" to "HEART_RATE_5MIN",
            )) {
                db.execSQL(
                    "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, " +
                        "last_modified_epoch_ms, data_origin_package, time_zone_offset_minutes, " +
                        "payload_schema_version, value_json, deleted_at_epoch_ms, source_updated_at_epoch_ms) VALUES " +
                        "(?, ?, 1000, 2000, 5, 'com.samsung.health', NULL, 1, '{}', NULL, 5)",
                    arrayOf(hcId, type),
                )
            }
            // Outbox: operación pendiente del tipo recortado + una del esencial
            db.execSQL(
                "INSERT INTO health_outbox (target_id, hc_id, operation, revision, attempt_count, created_at_epoch_ms) VALUES " +
                    "(1, 'hc-speed', 'UPSERT', 5, 0, 100), " +
                    "(1, 'hc-steps', 'UPSERT', 5, 0, 100)"
            )
            MIGRATION_2_3.migrate(db)
            // El estado esencial sobrevive; los recortados no.
            db.query("SELECT record_type FROM health_sync_state").use { c ->
                val types = mutableListOf<String>()
                while (c.moveToNext()) types += c.getString(0)
                assertEquals(listOf("STEPS"), types)
            }
            // Los registros espejo esenciales y el agregado HR sobreviven; el recortado no.
            db.query("SELECT hc_id FROM health_records ORDER BY hc_id").use { c ->
                val ids = mutableListOf<String>()
                while (c.moveToNext()) ids += c.getString(0)
                assertEquals(listOf("hc-hr5", "hc-steps"), ids)
            }
            // El outbox pierde la operación del tipo recortado.
            db.query("SELECT hc_id FROM health_outbox").use { c ->
                val ids = mutableListOf<String>()
                while (c.moveToNext()) ids += c.getString(0)
                assertEquals(listOf("hc-steps"), ids)
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v2-v3.db")
        }
    }

    @Test
    fun `migration v3 to v4 creates training cache tables`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = openV2Database(context, "migration-v3-v4.db")
        try {
            MIGRATION_2_3.migrate(db)
            MIGRATION_3_4.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('training_cache','training_cache_meta')").use { c ->
                val names = mutableListOf<String>()
                while (c.moveToNext()) names += c.getString(0)
                assertTrue(names.contains("training_cache"))
                assertTrue(names.contains("training_cache_meta"))
            }
            // La caché admite escritura inmediata tras migrar.
            db.execSQL(
                "INSERT INTO training_cache_meta (fecha, semana, dia, has_data, updated_at_epoch_ms) " +
                    "VALUES ('2026-09-07', 19, 'LUNES', 1, 5)",
            )
            db.execSQL(
                "INSERT INTO training_cache (fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm) " +
                    "VALUES ('2026-09-07', 1, 'Press', 80.0, 8.0, 1.0, NULL, 103.9)",
            )
            db.query("SELECT ejercicio, rm FROM training_cache WHERE fecha='2026-09-07'").use { c ->
                c.moveToFirst()
                assertEquals("Press", c.getString(0))
                assertEquals(103.9, c.getDouble(1), 0.001)
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v3-v4.db")
        }
    }

    @Test
    fun `migration v1 to v2 preserves state and outbox and adds scheduling columns`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-test.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-test.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(1) {
                    override fun onCreate(db: SupportSQLiteDatabase) = createV1(db)
                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build()
        )
        val db = helper.writableDatabase
        try {
            db.execSQL(
                "INSERT INTO health_sync_state (record_type, changes_token, permission_granted, last_successful_read_at_epoch_ms) " +
                    "VALUES ('STEPS', 'tok-1', 1, 111)"
            )
            db.execSQL(
                "INSERT INTO health_outbox (target_id, hc_id, operation, revision, attempt_count, created_at_epoch_ms) " +
                    "VALUES (1, 'hc-1', 'UPSERT', 5, 0, 100)"
            )
            MIGRATION_1_2.migrate(db)
            db.query("SELECT changes_token, permission_granted, last_successful_read_at_epoch_ms FROM health_sync_state WHERE record_type='STEPS'").use { c ->
                assertNotNull(c)
                c.moveToFirst()
                assertEquals("tok-1", c.getString(0))
                assertEquals(1, c.getInt(1))
                assertEquals(111L, c.getLong(2))
            }
            db.query(
                "SELECT hc_id, operation, revision FROM health_outbox WHERE target_id=1 AND hc_id='hc-1'",
            ).use { c ->
                c.moveToFirst()
                assertEquals("UPSERT", c.getString(1))
                assertEquals(5L, c.getLong(2))
            }
            db.query("PRAGMA table_info(health_sync_state)").use { c ->
                val cols = mutableListOf<String>()
                while (c.moveToNext()) cols += c.getString(1)
                for (expected in listOf(
                    "next_due_at_epoch_ms", "cooldown_until_epoch_ms", "priority",
                    "bootstrap_page_token", "bootstrap_start_epoch_ms", "empty_runs",
                )) assertTrue("falta columna $expected", cols.contains(expected))
            }
            db.query("PRAGMA table_info(sync_meta)").use { c ->
                assertTrue("sync_meta debe existir", c.moveToFirst())
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-test.db")
        }
    }

    @Test
    fun `full chain v9 to v11 converges every known lineage`() {
        // Prueba el camino REAL del teléfono: una BD generada por Room (como
        // todas las v9/v10 en uso) degradada al PEOR linaje conocido —
        // tabla nutrition_publish (rama de nutrición, v10 divergente),
        // training_cache sin DEFAULT NULL (artefacto de MIGRATION_5_6) e
        // índice de work_intervals ausente — sellada como v9, abierta con
        // Room.databaseBuilder + la lista de migraciones de producción.
        // Room valida TODAS las tablas al migrar: en verde, cualquier
        // teléfono abre.
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-chain-v9-v11.db")
        Room.databaseBuilder(context, HealthDatabase::class.java, "migration-chain-v9-v11.db")
            .allowMainThreadQueries()
            .build()
            .apply {
                // Room crea las tablas en diferido: forzar la apertura.
                runBlocking { healthDao().getState("STEPS") }
                close()
            }
        val raw = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-chain-v9-v11.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(11) {
                    override fun onCreate(db: SupportSQLiteDatabase) {}
                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        ).writableDatabase
        raw.execSQL("PRAGMA user_version = 9")
        raw.execSQL(
            "CREATE TABLE nutrition_publish (fecha TEXT NOT NULL PRIMARY KEY, day_hash TEXT NOT NULL, " +
                "client_ids TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, updated_at_epoch_ms INTEGER NOT NULL)",
        )
        // training_cache "antigua": mismas columnas, sin DEFAULT NULL.
        raw.execSQL("ALTER TABLE training_cache RENAME TO training_cache_old")
        raw.execSQL(
            "CREATE TABLE training_cache (rowId INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                "fecha TEXT NOT NULL, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, " +
                "kg REAL, reps REAL, rir REAL, descanso_seg REAL, rm REAL, " +
                "velocidad_kmh REAL, dificultad REAL)",
        )
        raw.execSQL(
            "INSERT INTO training_cache (rowId, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm, velocidad_kmh, dificultad) " +
                "SELECT rowId, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm, velocidad_kmh, dificultad " +
                "FROM training_cache_old",
        )
        raw.execSQL("DROP TABLE training_cache_old")
        raw.execSQL(
            "INSERT INTO training_cache (fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm, velocidad_kmh, dificultad) " +
                "VALUES ('2026-09-07', 1, 'Press', 80.0, 8.0, 1.0, NULL, 103.9, NULL, NULL)",
        )
        raw.execSQL("DROP INDEX IF EXISTS index_work_intervals_fecha_start")
        raw.execSQL(
            "INSERT INTO health_sync_state (record_type, changes_token, permission_granted, last_successful_read_at_epoch_ms, " +
                "next_due_at_epoch_ms, cooldown_until_epoch_ms, priority, bootstrap_page_token, " +
                "bootstrap_start_epoch_ms, empty_runs) VALUES " +
                "('STEPS', 'tok-steps', 1, 111, 222, NULL, 1, NULL, NULL, 0)",
        )
        raw.execSQL(
            "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, " +
                "last_modified_epoch_ms, data_origin_package, time_zone_offset_minutes, " +
                "payload_schema_version, value_json, deleted_at_epoch_ms, source_updated_at_epoch_ms) VALUES " +
                "('hc-raw', 'STEPS', 1000, 2000, 5, 'com.samsung.health', NULL, 1, '{}', NULL, 5)",
        )
        raw.close()

        // Apertura real como en producción: migra 9→10→11 y valida identidad.
        val db = Room.databaseBuilder(context, HealthDatabase::class.java, "migration-chain-v9-v11.db")
            .addMigrations(
                MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5,
                MIGRATION_5_6, MIGRATION_6_7, MIGRATION_7_8, MIGRATION_8_9,
                MIGRATION_9_10, MIGRATION_10_11,
            )
            .allowMainThreadQueries()
            .build()
        try {
            runBlocking {
                assertNull("el crudo retirado no sobrevive a la cadena", db.healthDao().getState("STEPS"))
                db.healthDao().upsertState(
                    com.jhomc.healthsync.data.HealthSyncStateEntity(recordType = "STEPS_H1"),
                )
                assertNotNull(db.healthDao().getState("STEPS_H1"))
            }
            db.query(SimpleSQLiteQuery("SELECT name FROM sqlite_master WHERE type='table' AND name='nutrition_publish'")).use {
                assertTrue("nutrition_publish debe desaparecer", !it.moveToFirst())
            }
            // La fila de training_cache sobrevive al rebuild con sus valores.
            db.query(SimpleSQLiteQuery("SELECT ejercicio, kg FROM training_cache WHERE fecha='2026-09-07'")).use {
                assertTrue(it.moveToFirst())
                assertEquals("Press", it.getString(0))
                assertEquals(80.0, it.getDouble(1), 0.001)
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-chain-v9-v11.db")
        }
    }

    @Test
    fun `migration v9 to v10 retires raw interval types for hourly sums`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = openV2Database(context, "migration-v9-v10.db")
        try {
            db.execSQL(
                "INSERT INTO health_sync_state (record_type, changes_token, permission_granted, last_successful_read_at_epoch_ms, " +
                    "next_due_at_epoch_ms, cooldown_until_epoch_ms, priority, bootstrap_page_token, " +
                    "bootstrap_start_epoch_ms, empty_runs) VALUES " +
                    "('STEPS', 'tok-steps', 1, 111, 222, NULL, 1, NULL, NULL, 0), " +
                    "('DISTANCE', 'tok-dist', 1, 111, 222, NULL, 1, NULL, NULL, 0), " +
                    "('STEPS_H1', 'tok-h1', 1, 111, 222, NULL, 1, NULL, NULL, 0), " +
                    "('SLEEP_SESSION', 'tok-sleep', 1, 111, 222, NULL, 1, NULL, NULL, 0)"
            )
            for ((hcId, type) in listOf(
                "hc-raw-steps" to "STEPS",
                "hc-raw-dist" to "DISTANCE",
                "hc-h1" to "STEPS_H1",
                "hc-sleep" to "SLEEP_SESSION",
            )) {
                db.execSQL(
                    "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, " +
                        "last_modified_epoch_ms, data_origin_package, time_zone_offset_minutes, " +
                        "payload_schema_version, value_json, deleted_at_epoch_ms, source_updated_at_epoch_ms) VALUES " +
                        "(?, ?, 1000, 2000, 5, 'com.samsung.health', NULL, 1, '{}', NULL, 5)",
                    arrayOf(hcId, type),
                )
            }
            db.execSQL(
                "INSERT INTO health_outbox (target_id, hc_id, operation, revision, attempt_count, created_at_epoch_ms) VALUES " +
                    "(1, 'hc-raw-steps', 'UPSERT', 5, 0, 100), " +
                    "(1, 'hc-raw-dist', 'UPSERT', 5, 0, 100), " +
                    "(1, 'hc-h1', 'UPSERT', 5, 0, 100)"
            )
            MIGRATION_9_10.migrate(db)
            db.query("SELECT record_type FROM health_sync_state ORDER BY record_type").use { c ->
                val types = mutableListOf<String>()
                while (c.moveToNext()) types += c.getString(0)
                assertEquals(listOf("SLEEP_SESSION", "STEPS_H1"), types)
            }
            db.query("SELECT hc_id FROM health_records ORDER BY hc_id").use { c ->
                val ids = mutableListOf<String>()
                while (c.moveToNext()) ids += c.getString(0)
                assertEquals(listOf("hc-h1", "hc-sleep"), ids)
            }
            db.query("SELECT hc_id FROM health_outbox").use { c ->
                val ids = mutableListOf<String>()
                while (c.moveToNext()) ids += c.getString(0)
                assertEquals(listOf("hc-h1"), ids)
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v9-v10.db")
        }
    }

    @Test
    fun `migration v4 to v5 creates nutrition cache and outbox`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = openV2Database(context, "migration-v4-v5.db")
        try {
            MIGRATION_2_3.migrate(db)
            MIGRATION_3_4.migrate(db)
            MIGRATION_4_5.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('nutrition_cache','pending_writes')").use { c ->
                val names = mutableListOf<String>()
                while (c.moveToNext()) names += c.getString(0)
                assertTrue(names.contains("nutrition_cache"))
                assertTrue(names.contains("pending_writes"))
            }
            db.execSQL(
                "INSERT INTO nutrition_cache (fecha, payload_json, updated_at_epoch_ms) " +
                    "VALUES ('2026-09-07', '{\"a\":1}', 5)",
            )
            db.execSQL(
                "INSERT INTO pending_writes (domain, fecha, op, payload_json, created_at_epoch_ms) " +
                    "VALUES ('sesion', '2026-09-07', 'SAVE', '{}', 5)",
            )
            db.query("SELECT payload_json FROM nutrition_cache WHERE fecha='2026-09-07'").use { c ->
                c.moveToFirst()
                assertEquals("{\"a\":1}", c.getString(0))
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v4-v5.db")
        }
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class TrainingCacheHiitMigrationTest {

    @Test
    fun `migration v5 to v6 adds hiit columns preserving rows`() {        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v5-v6.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v5-v6.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(5) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL(
                            "CREATE TABLE training_cache (rowId INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                                "fecha TEXT NOT NULL, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, " +
                                "kg REAL, reps REAL, rir REAL, descanso_seg REAL, rm REAL)",
                        )
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        )
        val db = helper.writableDatabase
        try {
            db.execSQL(
                "INSERT INTO training_cache (fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg, rm) " +
                    "VALUES ('2026-09-07', 1, 'Press', 80.0, 8.0, 1.0, NULL, 103.9)",
            )
            MIGRATION_5_6.migrate(db)
            db.execSQL(
                "INSERT INTO training_cache (fecha, set_orden, ejercicio, velocidad_kmh, dificultad) " +
                    "VALUES ('2026-09-07', 2, 'HIIT', 12.3, 7.5)",
            )
            db.query("SELECT ejercicio, kg, velocidad_kmh, dificultad FROM training_cache ORDER BY set_orden").use { c ->
                c.moveToFirst()
                assertEquals("Press", c.getString(0))
                assertTrue(c.isNull(2))
                c.moveToNext()
                assertEquals("HIIT", c.getString(0))
                assertTrue(c.isNull(1))
                assertEquals(12.3, c.getDouble(2), 0.001)
                assertEquals(7.5, c.getDouble(3), 0.001)
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v5-v6.db")
        }
    }
}
