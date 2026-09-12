package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.MIGRATION_7_8
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Migración 7→8: crea entreno_drafts sin tocar lo demás. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class EntrenoDraftsMigrationTest {

    @Test
    fun `migration v7 to v8 crea entreno_drafts`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v7-v8.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v7-v8.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(7) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE t7 (a TEXT NOT NULL PRIMARY KEY)")
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        )
        val db = helper.writableDatabase
        try {
            MIGRATION_7_8.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='entreno_drafts'").use {
                assertTrue(it.moveToFirst())
            }
            db.execSQL(
                "INSERT INTO entreno_drafts (fecha, payload_json, done_json, base_hash, updated_at_epoch_ms) " +
                    "VALUES ('2026-09-12', '[]', '[\"u1\"]', 'abc', 5)",
            )
            db.query("SELECT done_json, base_hash FROM entreno_drafts WHERE fecha='2026-09-12'").use {
                it.moveToFirst()
                assertEquals("[\"u1\"]", it.getString(0))
                assertEquals("abc", it.getString(1))
            }
            // Lo previo sobrevive.
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='t7'").use {
                assertTrue(it.moveToFirst())
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v7-v8.db")
        }
    }
}
