package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_1_2
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
