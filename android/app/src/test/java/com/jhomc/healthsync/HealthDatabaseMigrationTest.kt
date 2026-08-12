package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_1_2
import com.jhomc.healthsync.data.MIGRATION_2_3
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
            "CREATE TABLE sync_targets (target_id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, " +
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
}
