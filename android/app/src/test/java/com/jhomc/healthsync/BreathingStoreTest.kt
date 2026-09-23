package com.jhomc.healthsync

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.BreathingPendingEntity
import com.jhomc.healthsync.data.BreathingSessionEntity
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_12_13
import com.jhomc.healthsync.data.MIGRATION_13_14
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Room B5.0: sesiones, cola + migraciones 12→13 y 13→14. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class BreathingStoreTest {

    private lateinit var db: HealthDatabase

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun `migration 13 to 14 retira presets sin tocar sesiones`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v13-v14.db")
        val helper = androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory().create(
            androidx.sqlite.db.SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v13-v14.db")
                .callback(object : androidx.sqlite.db.SupportSQLiteOpenHelper.Callback(13) {
                    override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                        db.execSQL(
                            "CREATE TABLE breathing_presets (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, " +
                                "nombre TEXT NOT NULL, pattern_json TEXT NOT NULL, duration_s INTEGER, " +
                                "updated_at_epoch_ms INTEGER NOT NULL)",
                        )
                        db.execSQL(
                            "CREATE TABLE breathing_sessions (client_session_id TEXT NOT NULL PRIMARY KEY, " +
                                "fecha TEXT NOT NULL, start_epoch_ms INTEGER NOT NULL, " +
                                "end_epoch_ms INTEGER NOT NULL, tz_offset_min INTEGER NOT NULL, " +
                                "planned_s INTEGER, real_s INTEGER NOT NULL, pattern_json TEXT NOT NULL, " +
                                "ciclos INTEGER NOT NULL, bpm REAL NOT NULL, completada INTEGER NOT NULL, " +
                                "delivered INTEGER NOT NULL, created_at_epoch_ms INTEGER NOT NULL)",
                        )
                    }

                    override fun onUpgrade(
                        db: androidx.sqlite.db.SupportSQLiteDatabase,
                        oldVersion: Int,
                        newVersion: Int,
                    ) {
                    }
                })
                .build(),
        )
        val db13 = helper.writableDatabase
        try {
            db13.execSQL(
                "INSERT INTO breathing_presets (nombre, pattern_json, duration_s, updated_at_epoch_ms) " +
                    "VALUES ('Caja 4-4-4-4', '{}', 300, 1)",
            )
            MIGRATION_13_14.migrate(db13)
            db13.query("SELECT name FROM sqlite_master WHERE type='table' AND name='breathing_presets'").use {
                assertTrue(it.count == 0)
            }
            db13.query("SELECT name FROM sqlite_master WHERE type='table' AND name='breathing_sessions'").use {
                assertTrue(it.moveToFirst())
            }
        } finally {
            db13.close()
            context.deleteDatabase("migration-v13-v14.db")
        }
    }

    @Test
    fun `sesion roundtrip y delivered`() = runBlocking {
        val dao = db.breathingDao()
        assertNull(dao.sessionById("u1"))
        dao.putSession(
            BreathingSessionEntity(
                clientSessionId = "u1", fecha = "2026-09-13", startMs = 10L, endMs = 130_000L,
                tzOffsetMin = 0, plannedS = 120, realS = 120, patternJson = "{}",
                ciclos = 12, bpm = 6.0, completada = true, createdAtMs = 2L,
            ),
        )
        assertEquals(1, dao.sessionsFor("2026-09-13").size)
        assertEquals(0, dao.sessionsFor("2026-09-14").size)
        dao.markDelivered("u1", 12, 6.0)
        assertEquals(true, dao.sessionById("u1")?.delivered)
        dao.deleteSession("u1")
        assertNull(dao.sessionById("u1"))
    }

    @Test
    fun `cola pending upsert por pk`() = runBlocking {
        val dao = db.breathingDao()
        dao.enqueue(BreathingPendingEntity("u1", "SAVE", "{}", 1L))
        dao.enqueue(BreathingPendingEntity("u1", "SAVE", "{\"a\":1}", 2L))
        assertEquals(1, dao.pendingCount())
        assertEquals("{\"a\":1}", dao.pendingAll().single().payloadJson)
        dao.ack("u1")
        assertEquals(0, dao.pendingCount())
    }

    @Test
    fun `migration 12 to 13 crea tablas`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.deleteDatabase("migration-v12-v13.db")
        val helper = androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory().create(
            androidx.sqlite.db.SupportSQLiteOpenHelper.Configuration.builder(context)
                .name("migration-v12-v13.db")
                .callback(object : androidx.sqlite.db.SupportSQLiteOpenHelper.Callback(12) {
                    override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                        db.execSQL("CREATE TABLE t12 (a TEXT NOT NULL PRIMARY KEY)")
                    }

                    override fun onUpgrade(
                        db: androidx.sqlite.db.SupportSQLiteDatabase,
                        oldVersion: Int,
                        newVersion: Int,
                    ) {
                    }
                })
                .build(),
        )
        val db12 = helper.writableDatabase
        try {
            MIGRATION_12_13.migrate(db12)
            for (table in listOf("breathing_presets", "breathing_sessions", "breathing_pending", "t12")) {
                db12.query("SELECT name FROM sqlite_master WHERE type='table' AND name='$table'").use {
                    assertTrue("falta $table", it.moveToFirst())
                }
            }
            db12.execSQL(
                "INSERT INTO breathing_pending (client_session_id, op, payload_json, created_at_epoch_ms) " +
                    "VALUES ('u1', 'SAVE', '{}', 5)",
            )
            db12.query("SELECT op FROM breathing_pending WHERE client_session_id='u1'").use {
                it.moveToFirst()
                assertEquals("SAVE", it.getString(0))
            }
        } finally {
            db12.close()
            context.deleteDatabase("migration-v12-v13.db")
        }
    }
}
