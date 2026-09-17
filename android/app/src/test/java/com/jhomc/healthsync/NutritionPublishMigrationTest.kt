package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.MIGRATION_11_12
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Migración 11→12: crea nutrition_publish sin tocar lo demás. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class NutritionPublishMigrationTest {

    @Test
    fun `migration v11 to v12 crea nutrition_publish`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v11-v12.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v11-v12.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(11) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE t11 (a TEXT NOT NULL PRIMARY KEY)")
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        )
        val db = helper.writableDatabase
        try {
            MIGRATION_11_12.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='nutrition_publish'").use {
                assertTrue(it.moveToFirst())
            }
            db.execSQL(
                "INSERT INTO nutrition_publish (fecha, day_hash, client_ids, status, detail, updated_at_epoch_ms) " +
                    "VALUES ('2026-09-15', 'abc', 'gym-diario-2026-09-15-1', 'OK', 'insert:1 delete:0', 1000)",
            )
            db.query("SELECT status FROM nutrition_publish WHERE fecha='2026-09-15'").use {
                it.moveToFirst()
                assertEquals("OK", it.getString(0))
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v11-v12.db")
        }
    }
}
