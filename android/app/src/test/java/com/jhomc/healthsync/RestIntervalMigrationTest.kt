package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.MIGRATION_6_7
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Migración 6→7: crea rest_intervals con su índice sin tocar lo demás. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RestIntervalMigrationTest {

    @Test
    fun `migration v6 to v7 crea rest_intervals`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v6-v7.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v6-v7.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(6) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE t6 (a TEXT NOT NULL PRIMARY KEY)")
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        )
        val db = helper.writableDatabase
        try {
            MIGRATION_6_7.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='rest_intervals'").use {
                assertTrue(it.moveToFirst())
            }
            db.query("SELECT name FROM sqlite_master WHERE type='index' AND name='index_rest_intervals_fecha_start'").use {
                assertTrue(it.moveToFirst())
            }
            db.execSQL(
                "INSERT INTO rest_intervals (fecha, ejercicio, client_set_uuid, set_orden_aparente, " +
                    "start_wall_ms, start_elapsed_ms, estado, created_at_epoch_ms) " +
                    "VALUES ('2026-09-12', 'Press', 'u1', 1, 1000, 5000, 'ABIERTO', 1000)",
            )
            db.query("SELECT ejercicio, estado FROM rest_intervals WHERE client_set_uuid='u1'").use {
                it.moveToFirst()
                assertEquals("Press", it.getString(0))
                assertEquals("ABIERTO", it.getString(1))
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v6-v7.db")
        }
    }
}
