package com.jhomc.healthsync

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.MIGRATION_8_9
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Migración 8→9: crea work_intervals sin tocar lo demás. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class WorkIntervalMigrationTest {

    @Test
    fun `migration v8 to v9 crea work_intervals`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v8-v9.db")
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v8-v9.db")
                .callback(object : SupportSQLiteOpenHelper.Callback(8) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE t8 (a TEXT NOT NULL PRIMARY KEY)")
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
                })
                .build(),
        )
        val db = helper.writableDatabase
        try {
            MIGRATION_8_9.migrate(db)
            db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='work_intervals'").use {
                assertTrue(it.moveToFirst())
            }
            db.execSQL(
                "INSERT INTO work_intervals (fecha, ejercicio, client_set_uuid, set_orden_aparente, " +
                    "start_wall_ms, start_elapsed_ms, estado, created_at_epoch_ms) " +
                    "VALUES ('2026-09-12', 'Press', 'u1', 1, 1000, 5000, 'ABIERTO', 1000)",
            )
            db.query("SELECT ejercicio, estado FROM work_intervals WHERE client_set_uuid='u1'").use {
                it.moveToFirst()
                assertEquals("Press", it.getString(0))
                assertEquals("ABIERTO", it.getString(1))
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-v8-v9.db")
        }
    }
}
