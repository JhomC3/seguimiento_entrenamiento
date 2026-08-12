# Health Sync Quota Scheduling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **Estado (2026-08-12, cierre):** 8/8 tasks **implementadas** (commits `e4f4733`…`d0e12b7`; suite Android en verde).
> Posteriormente el diseño fue **superado y simplificado**:
> - La agenda adaptativa (prioridades 6h/24h/7d) se reemplazó por **ventanas diarias fijas** (9:00/13:00/19:00) — `4a2cba4`.
> - HEART_RATE pasó a **tramos de 5 min** (lectura por día acotada + bucketizado local; el SDK 1.1.0 no expone agregación de HR) — `6740eb6`.
> - Se añadió el **modo fuerza** (una pulsación sincroniza todos los tipos) — `969d60a`.
> - Verificado end-to-end en dispositivo (2 391 registros de los 17 tipos esenciales en `data/lifestyle.db`; la base se renombró de `gym.db`).
> El rediseño de UI a 17 tipos esenciales está en `docs/plans/archive/2026-08-12-healthsync-simplified-ui.md` (archivado).

**Goal:** Implementar §3.1 del plan `docs/plans/archive/2026-08-09-health-connect-sync.md`: que la app Android sincronice **todos** los tipos autorizados sin quemar la cuota de Health Connect — selección previa por vencimiento, rotación round-robin persistida, bootstrap reanudable con checkpoint, enfriamiento ante rate limit, ritmo entre llamadas y prioridades adaptativas.

**Architecture:** El planificador vive en `HealthRepository` + un objeto puro `HealthSyncPlanner` (sin I/O, testeable). El estado por tipo se persiste en Room (`health_sync_state` ampliada + tabla `sync_meta` para el cursor global). La sincronización deja de ser "todos los tipos en cada ejecución": una ejecución selecciona solo los tipos vencidos (no en enfriamiento), con presupuesto `MAX_TYPES_PER_RUN = 1`, rotando el cursor. El bootstrap de 30 días persiste el token reservado, el ancla de ventana y el `pageToken` de cada página en la misma transacción que la página, de modo que un corte (rate limit, crash) se reanuda donde se quedó. Toda llamada a Health Connect pasa por el gateway (falso en tests), y entre páginas hay un ritmo configurable.

**Tech Stack:** Kotlin, Room 2.6.1 (+KSP), Robolectric (tests unitarios JVM, sin dispositivo), `connect-client:1.1.0`, Gradle desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle` (máxima del sandbox). Sin cambios en el backend Python (este plan es 100 % Android).

---

## Contexto: estado actual del código (verificado)

| Problema | Dónde |
|---|---|
| `.mapNotNull { syncType(...) }.take(1)` ejecuta **todos** los tipos y luego trunca: no limita las llamadas a HC | `HealthRepository.kt:95-106` |
| Sin cursor persistido: si se limitara, STEPS sería el único tipo siempre | no existe `sync_meta` |
| El bootstrap (30 días) no persiste `pageToken`: un rate limit reinicia el backfill desde cero | `HealthRepository.kt:189-206` |
| El token reservado se pierde en un crash a mitad de backfill (solo se guarda al drenar) | `HealthRepository.kt:163-187` |
| No hay pausa entre llamadas de páginas: ráfaga → rate limit (verificado en dispositivo) | `HealthRepository.kt:194-204`, `208-264` |
| `health_sync_state` solo tiene token/permiso/`last_successful_read_at` | `data/HealthDatabase.kt:36-42` |
| Sin `next_due_at`/`cooldown`/prioridad/`empty_runs` | idem |

**Solución de diseño que implementa este plan:**

1. `health_sync_state` gana: `next_due_at_epoch_ms`, `cooldown_until_epoch_ms`, `priority` (2 alta / 1 media / 0 fría), `bootstrap_page_token`, `bootstrap_start_epoch_ms`, `empty_runs`.
2. Nueva tabla `sync_meta` (clave-valor) para el cursor round-robin global.
3. `syncAuthorizedTypes()`: filtra por permiso → excluye enfriamiento → excluye no vencidos → ordena por vencimiento → rota desde el cursor → toma `MAX_TYPES_PER_RUN`. Si no hay vencidos, **cero llamadas a HC**.
4. `firstSync()`: reserva el token y lo persiste junto al ancla de 30 días ANTES del backfill; cada página persiste su `pageToken` en la misma transacción; al terminar, drena desde el token reservado.
5. `markSynced()` tras cada tipo: calcula `hadChanges`, ajusta prioridad (sube si hubo cambios; baja tras 3 rondas vacías), fija `next_due_at = ahora + intervalo(prioridad)` (6 h alta / 24 h media / 7 días fría; siempre < caducidad de token de 30 días) y limpia el enfriamiento.
6. `markCooldown()` al recibir rate limit: `cooldown_until = ahora + 1 h`; la ejecución termina (sin reintento en bucle).
7. Ritmo: `delay(pacingMs)` entre páginas (default 2 000 ms; 0 en tests).

**Constantes:** `MAX_TYPES_PER_RUN = 1` (ya existe), `PACING_DEFAULT_MS = 2_000`, `COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000`, `EMPTY_RUNS_TO_DEMOTE = 3`, `BACKFILL_WINDOW_MS = 30 días`, intervalos 6 h / 24 h / 7 d.

---

## Task 1: Esquema Room v2 (estado ampliado + `sync_meta` + migración)

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/data/HealthDatabase.kt`
- Create: `android/app/src/test/java/com/jhomc/healthsync/HealthDatabaseMigrationTest.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/HealthDatabaseTest.kt` (ajustar si aserta shape/version)

**Step 1: Escribir el test de migración que falla**

`HealthDatabaseMigrationTest.kt`:

```kotlin
package com.jhomc.healthsync

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.HealthDatabase
import com.jhomc.healthsync.data.MIGRATION_1_2
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthDatabaseMigrationTest {

    private fun createV1(db: SQLiteDatabase) {
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
        val db = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("migration-test.db"), null)
        try {
            createV1(db)
            db.execSQL(
                "INSERT INTO health_sync_state (record_type, changes_token, permission_granted, last_successful_read_at_epoch_ms) " +
                    "VALUES ('STEPS', 'tok-1', 1, 111)"
            )
            db.execSQL(
                "INSERT INTO health_outbox (target_id, hc_id, operation, revision, attempt_count, created_at_epoch_ms) " +
                    "VALUES (1, 'hc-1', 'UPSERT', 5, 0, 100)"
            )
            MIGRATION_1_2.migrate(db)
            db.rawQuery("SELECT changes_token, permission_granted, last_successful_read_at_epoch_ms FROM health_sync_state WHERE record_type='STEPS'", null).use { c ->
                assertNotNull(c)
                c.moveToFirst()
                assertEquals("tok-1", c.getString(0))
                assertEquals(1, c.getInt(1))
                assertEquals(111L, c.getLong(2))
            }
            db.rawQuery(
                "SELECT hc_id, operation, revision FROM health_outbox WHERE target_id=1 AND hc_id='hc-1'", null,
            ).use { c ->
                c.moveToFirst()
                assertEquals("UPSERT", c.getString(1))
                assertEquals(5L, c.getLong(2))
            }
            db.rawQuery("PRAGMA table_info(health_sync_state)", null).use { c ->
                val cols = mutableListOf<String>()
                while (c.moveToNext()) cols += c.getString(1)
                for (expected in listOf(
                    "next_due_at_epoch_ms", "cooldown_until_epoch_ms", "priority",
                    "bootstrap_page_token", "bootstrap_start_epoch_ms", "empty_runs",
                )) assertTrue("falta columna $expected", cols.contains(expected))
            }
            db.rawQuery("PRAGMA table_info(sync_meta)", null).use { c ->
                assertTrue("sync_meta debe existir", c.moveToFirst())
            }
        } finally {
            db.close()
            context.deleteDatabase("migration-test.db")
        }
    }
}
```

Añade el import que falta: `import org.junit.Assert.assertTrue`.

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthDatabaseMigrationTest"`
Expected: FAIL (compilación) — `MIGRATION_1_2` no existe.

**Step 3: Implementar el esquema v2 y la migración**

En `HealthDatabase.kt`:

1. Ampliar la entidad:

```kotlin
@Entity(tableName = "health_sync_state")
data class HealthSyncStateEntity(
    @PrimaryKey @ColumnInfo(name = "record_type") val recordType: String,
    @ColumnInfo(name = "changes_token") val changesToken: String? = null,
    @ColumnInfo(name = "permission_granted") val permissionGranted: Boolean = false,
    @ColumnInfo(name = "last_successful_read_at_epoch_ms") val lastSuccessfulReadAtEpochMs: Long? = null,
    @ColumnInfo(name = "next_due_at_epoch_ms") val nextDueAtEpochMs: Long? = null,
    @ColumnInfo(name = "cooldown_until_epoch_ms") val cooldownUntilEpochMs: Long? = null,
    @ColumnInfo(name = "priority") val priority: Int = 1,
    @ColumnInfo(name = "bootstrap_page_token") val bootstrapPageToken: String? = null,
    @ColumnInfo(name = "bootstrap_start_epoch_ms") val bootstrapStartEpochMs: Long? = null,
    @ColumnInfo(name = "empty_runs") val emptyRuns: Int = 0,
)
```

2. Nueva entidad:

```kotlin
@Entity(tableName = "sync_meta")
data class SyncMetaEntity(
    @PrimaryKey @ColumnInfo(name = "meta_key") val key: String,
    @ColumnInfo(name = "meta_value") val value: String,
)
```

3. DAO (`HealthDao`):

```kotlin
@Query("SELECT * FROM sync_meta WHERE meta_key = :key")
suspend fun getMeta(key: String): SyncMetaEntity?

@Insert(onConflict = OnConflictStrategy.REPLACE)
suspend fun putMeta(meta: SyncMetaEntity)
```

4. Migración (al final del archivo):

```kotlin
val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN next_due_at_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN cooldown_until_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN priority INTEGER NOT NULL DEFAULT 1")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN bootstrap_page_token TEXT")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN bootstrap_start_epoch_ms INTEGER")
        db.execSQL("ALTER TABLE health_sync_state ADD COLUMN empty_runs INTEGER NOT NULL DEFAULT 0")
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS sync_meta (" +
                "meta_key TEXT NOT NULL PRIMARY KEY, meta_value TEXT NOT NULL)"
        )
    }
}
```

Imports: `androidx.room.migration.Migration`, `androidx.sqlite.db.SupportSQLiteDatabase`.

5. `@Database(entities = [..., SyncMetaEntity::class], version = 2, ...)`.

6. En `SyncScheduler.kt`, `HealthDatabaseBuilder.get` → `.addMigrations(MIGRATION_1_2)` antes de `.build()`.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest`
Expected: PASS (migración + tests previos).

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/data/HealthDatabase.kt android/app/src/main/java/com/jhomc/healthsync/SyncScheduler.kt android/app/src/test/java/com/jhomc/healthsync/HealthDatabaseMigrationTest.kt
git commit -m "feat: room v2 with scheduling state and round-robin meta table"
```

---

## Task 2: `HealthSyncPlanner` — lógica pura de planificación

**Files:**
- Create: `android/app/src/main/java/com/jhomc/healthsync/HealthSyncPlanner.kt`
- Create: `android/app/src/test/java/com/jhomc/healthsync/HealthSyncPlannerTest.kt`

**Step 1: Escribir los tests que fallan**

`HealthSyncPlannerTest.kt`:

```kotlin
package com.jhomc.healthsync

import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthSyncPlannerTest {

    @Test
    fun `high frequency types start at high priority`() {
        for (name in listOf("STEPS", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION", "TOTAL_CALORIES_BURNED")) {
            assertEquals(HealthSyncPlanner.PRIORITY_HIGH, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName(name)!!))
        }
    }

    @Test
    fun `composition and medical families start cold`() {
        for (name in listOf("WEIGHT", "BODY_FAT", "HEIGHT", "BLOOD_GLUCOSE", "BLOOD_PRESSURE")) {
            assertEquals(HealthSyncPlanner.PRIORITY_LOW, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName(name)!!))
        }
    }

    @Test
    fun `remaining types start medium`() {
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("DISTANCE")!!))
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("HYDRATION")!!))
        assertEquals(HealthSyncPlanner.PRIORITY_MEDIUM, HealthSyncPlanner.initialPriority(RecordTypes.byTypeName("NUTRITION")!!))
    }

    @Test
    fun `due intervals respect priority and stay below token expiry`() {
        for (p in listOf(0, 1, 2)) {
            val ms = HealthSyncPlanner.dueIntervalMs(p)
            assertTrue(ms in 1..(30L * 24 * 3_600_000))
        }
        assertEquals(6L * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_HIGH))
        assertEquals(24L * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_MEDIUM))
        assertEquals(7L * 24 * 3_600_000, HealthSyncPlanner.dueIntervalMs(HealthSyncPlanner.PRIORITY_LOW))
    }

    @Test
    fun `activity promotes one level and resets empty runs`() {
        val (p, e) = HealthSyncPlanner.adjustAfterRun(1, 2, hadChanges = true)
        assertEquals(2, p)
        assertEquals(0, e)
        val (p2, _) = HealthSyncPlanner.adjustAfterRun(2, 0, hadChanges = true)
        assertEquals(2, p2) // nunca pasa de HIGH
    }

    @Test
    fun `three empty runs demote one level`() {
        assertEquals(1 to 0, HealthSyncPlanner.adjustAfterRun(2, 2, hadChanges = false))
        assertEquals(0 to 0, HealthSyncPlanner.adjustAfterRun(1, 2, hadChanges = false))
        assertEquals(1 to 1, HealthSyncPlanner.adjustAfterRun(1, 0, hadChanges = false))
        assertEquals(0 to 0, HealthSyncPlanner.adjustAfterRun(0, 2, hadChanges = false)) // nunca baja de LOW
    }
}
```

(necesita `import org.junit.Assert.assertTrue`)

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthSyncPlannerTest"`
Expected: FAIL — `HealthSyncPlanner` no existe.

**Step 3: Implementar**

`HealthSyncPlanner.kt`:

```kotlin
package com.jhomc.healthsync

/**
 * Pure scheduling math for the per-type sync agenda (§3.1). No I/O: every
 * function is deterministic so the planner is unit-testable without Room.
 * All intervals stay below the 30-day changes-token expiry.
 */
object HealthSyncPlanner {

    const val PRIORITY_HIGH = 2
    const val PRIORITY_MEDIUM = 1
    const val PRIORITY_LOW = 0

    const val EMPTY_RUNS_TO_DEMOTE = 3

    /** Cooldown after a rate-limit response; the type is skipped until then. */
    const val COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000L

    /** Core activity types Samsung Health actually writes: synced first. */
    val HIGH_FREQUENCY_TYPES = setOf(
        "STEPS", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION",
        "ACTIVE_CALORIES_BURNED", "TOTAL_CALORIES_BURNED", "RESTING_HEART_RATE",
    )

    fun initialPriority(entry: RecordTypeEntry): Int = when {
        entry.typeName in HIGH_FREQUENCY_TYPES -> PRIORITY_HIGH
        entry.family == MappingFamily.COMPOSITION ||
            entry.family == MappingFamily.MEDICAL ||
            entry.family == MappingFamily.ROUTE -> PRIORITY_LOW
        else -> PRIORITY_MEDIUM
    }

    fun dueIntervalMs(priority: Int): Long = when (priority) {
        PRIORITY_HIGH -> 6L * 3_600_000
        PRIORITY_LOW -> 7L * 24 * 3_600_000
        else -> 24L * 3_600_000
    }

    fun nextDueMs(priority: Int, nowMs: Long): Long = nowMs + dueIntervalMs(priority)

    /** Returns (newPriority, newEmptyRuns) after one completed run of a type. */
    fun adjustAfterRun(priority: Int, emptyRuns: Int, hadChanges: Boolean): Pair<Int, Int> =
        if (hadChanges) {
            (priority + 1).coerceAtMost(PRIORITY_HIGH) to 0
        } else if (emptyRuns + 1 >= EMPTY_RUNS_TO_DEMOTE) {
            (priority - 1).coerceAtLeast(PRIORITY_LOW) to 0
        } else {
            priority to (emptyRuns + 1)
        }
}
```

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest`
Expected: PASS.

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/HealthSyncPlanner.kt android/app/src/test/java/com/jhomc/healthsync/HealthSyncPlannerTest.kt
git commit -m "feat: pure scheduling planner with adaptive priorities"
```

---

## Task 3: Selección por vencimiento + rotación round-robin + presupuesto

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/data/ChangesTokenStore.kt`
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/FakeHealthConnectGateway.kt`
- Create: `android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt`

**Step 1: Escribir los tests que fallan**

Ampliar `FakeHealthConnectGateway.kt` con registro de llamadas (sin romper el comportamiento actual):

```kotlin
// -- Registro de llamadas para aserciones de presupuesto/rotación --
val tokenLog = mutableListOf<String>()                       // typeName por getChangesToken
val readLog = mutableListOf<Pair<String, String?>>()          // (typeName, pageToken) por readRecords
val changesLog = mutableListOf<String>()                      // token por getChanges
var failNextTokenWithRateLimit = false                       // getChangesToken → RemoteException rate-limited
var failReadsWithRateLimit = false                           // readRecords → RemoteException rate-limited
val pageStore = mutableMapOf<String?, List<Record>>()         // paginación determinista para bootstrap (null = primera página)

override suspend fun getChangesToken(recordTypes: Set<KClass<out Record>>): String {
    tokenCounter++
    tokenLog += recordTypes.mapNotNull { RecordTypes.byClass(it)?.typeName }
    if (failNextTokenWithRateLimit) {
        failNextTokenWithRateLimit = false
        throw RemoteException("Rate limited request quota has been exceeded")
    }
    return "token-$tokenCounter"
}

override suspend fun readRecords(
    recordType: KClass<out Record>,
    start: Instant,
    end: Instant,
    pageToken: String?,
): ReadRecordsResponse<Record> {
    readLog += (RecordTypes.byClass(recordType)?.typeName ?: "?") to pageToken
    if (failReadsWithRateLimit) {
        failReadsWithRateLimit = false
        throw RemoteException("Rate limited request quota has been exceeded")
    }
    if (backfillQueue.isNotEmpty()) {
        val page = backfillQueue.removeAt(0)
        return ReadRecordsResponse(page, if (backfillQueue.isNotEmpty()) "page-token-${tokenCounter}" else null)
    }
    val records = pageStore[pageToken].orEmpty()
    val next = when {
        pageToken == null && pageStore.containsKey("pt-1") -> "pt-1"
        pageToken == "pt-1" && pageStore.containsKey("pt-2") -> "pt-2"
        else -> null
    }
    return ReadRecordsResponse(records, next)
}
```

(imports: `android.os.RemoteException`, `com.jhomc.healthsync.data.RecordMappers` no hace falta; verificar `RecordTypes.byClass` existe — sí, usado en `HealthRepository.toEntity`.)

`HealthRepositorySchedulingTest.kt`:

```kotlin
package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositorySchedulingTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private lateinit var repo: HealthRepository
    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        gateway = FakeHealthConnectGateway()
        gateway.granted = RecordTypes.all.map { it.permission }.toSet() // todos autorizados
        repo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = {},
        )
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun `a run with 38 authorized types calls only the budgeted ones`() = runBlocking {
        repo.syncAuthorizedTypes()
        assertTrue("criterio 1: 1 tipo por ejecución", gateway.tokenLog.size == 1)
        assertTrue(gateway.readLog.size <= 1) // solo el backfill del tipo elegido
    }

    @Test
    fun `five runs rotate across distinct types with persisted cursor`() = runBlocking {
        val chosen = mutableSetOf<String>()
        repeat(5) {
            gateway.tokenLog.clear()
            repo.syncAuthorizedTypes()
            chosen += gateway.tokenLog
        }
        assertEquals(5, chosen.size) // criterio 2: tipos distintos en 5 ejecuciones
    }

    @Test
    fun `nothing due means zero health connect calls`() = runBlocking {
        gateway.granted = setOf(RecordTypes.byTypeName("STEPS")!!.permission)
        repo.syncAuthorizedTypes() // primer run: STEPS sincronizado, next_due_at futuro
        gateway.tokenLog.clear(); gateway.readLog.clear(); gateway.changesLog.clear()
        repo.syncAuthorizedTypes()
        // criterio 4: sin vencidos → cero llamadas (ni backfill ni token)
        assertEquals(0, gateway.tokenLog.size)
        assertEquals(0, gateway.readLog.size)
        assertEquals(0, gateway.changesLog.size)
    }
}
```

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthRepositorySchedulingTest"`
Expected: FAIL — hoy `syncAuthorizedTypes` llama a todos los tipos (tokenLog > 1) y no persiste cursor.

**Step 3: Implementar la selección y la rotación**

En `HealthRepository.kt`:

1. Constructor con pacer inyectable (el diseño final de la antigua Task 6 se incorpora aquí para no tocar dos veces el constructor):

```kotlin
class HealthRepository(
    private val db: HealthDatabase,
    private val gateway: HealthConnectGateway,
    private val tokenStore: ChangesTokenStore,
    private val now: () -> Instant = Instant::now,
    private val pacer: suspend () -> Unit = { delay(PACING_DEFAULT_MS) },
) {
    companion object {
        const val PACING_DEFAULT_MS = 2_000L
    }

    /** Slows the page loop so bursts never blow the provider's per-window quota. */
    private suspend fun pace() = pacer()
```

(import `kotlinx.coroutines.delay`)

2. Nueva constante:

```kotlin
private const val ROTATION_META_KEY = "round_robin_index"
```

2. Reemplazar `syncAuthorizedTypes()`:

```kotlin
/**
 * Source phase: sync ONLY the authorized types whose next_due_at has passed
 * and that are not cooling down, budgeted to MAX_TYPES_PER_RUN. Candidates are
 * ordered by due time and the selection rotates from the persisted cursor so
 * no type starves. If nothing is due, no Health Connect call happens at all.
 */
suspend fun syncAuthorizedTypes(): List<TypeSyncResult> {
    val granted = gateway.grantedPermissions()
    val nowMs = now().toEpochMilli()
    val candidates = RecordTypes.all
        .filter { it.permission in granted }
        .map { entry -> entry to dao.getState(entry.typeName) }
        .filter { (_, st) ->
            val cooldown = st?.cooldownUntilEpochMs
            cooldown == null || cooldown <= nowMs
        }
        .filter { (_, st) ->
            val due = st?.nextDueAtEpochMs
            due == null || due <= nowMs
        }
        .sortedWith(
            compareBy<Pair<RecordTypeEntry, HealthSyncStateEntity?>> { it.second?.nextDueAtEpochMs ?: 0L }
                .thenBy { it.first.typeName },
        )
    if (candidates.isEmpty()) return emptyList()

    val cursor = rotationCursor()
    val start = cursor % candidates.size
    val rotated = candidates.drop(start) + candidates.take(start)
    val selected = rotated.take(MAX_TYPES_PER_RUN)
    saveRotationCursor((cursor + selected.size) % candidates.size)

    val results = mutableListOf<TypeSyncResult>()
    for ((entry, _) in selected) {
        try {
            val result = syncType(entry)
            tokenStore.markSynced(entry.typeName, result.hadChanges(), now().toEpochMilli())
            results += result
        } catch (e: RateLimitedException) {
            tokenStore.markCooldown(entry.typeName, now().toEpochMilli())
            throw e
        } catch (e: SecurityException) {
            tokenStore.markPermissionLost(entry.typeName)
        }
    }
    return results
}

private suspend fun rotationCursor(): Int =
    dao.getMeta(ROTATION_META_KEY)?.value?.toIntOrNull() ?: 0

private suspend fun saveRotationCursor(value: Int) {
    runCatching { dao.putMeta(SyncMetaEntity(ROTATION_META_KEY, value.toString())) }
}

private fun TypeSyncResult.hadChanges(): Boolean = upserts + deletes + backfilled > 0
```

Imports nuevos en `HealthRepository.kt`: `com.jhomc.healthsync.data.SyncMetaEntity`.

3. En `ChangesTokenStore.kt` — nuevos métodos (preservan campos con `copy`):

```kotlin
suspend fun markSynced(recordType: String, hadChanges: Boolean, nowMs: Long) {
    val current = dao.getState(recordType)
    val basePriority = current?.priority ?: HealthSyncPlanner.PRIORITY_MEDIUM
    val (newPriority, newEmptyRuns) = HealthSyncPlanner.adjustAfterRun(basePriority, current?.emptyRuns ?: 0, hadChanges)
    dao.upsertState(
        current?.copy(
            permissionGranted = true,
            lastSuccessfulReadAtEpochMs = nowMs,
            nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(newPriority, nowMs),
            cooldownUntilEpochMs = null,
            priority = newPriority,
            bootstrapPageToken = null,
            bootstrapStartEpochMs = null,
            emptyRuns = newEmptyRuns,
        )
            ?: HealthSyncStateEntity(
                recordType = recordType,
                changesToken = null,
                permissionGranted = true,
                lastSuccessfulReadAtEpochMs = nowMs,
                nextDueAtEpochMs = HealthSyncPlanner.nextDueMs(newPriority, nowMs),
                priority = newPriority,
            ),
    )
}

suspend fun markCooldown(recordType: String, nowMs: Long) {
    val current = dao.getState(recordType)
    dao.upsertState(
        current?.copy(cooldownUntilEpochMs = nowMs + HealthSyncPlanner.COOLDOWN_AFTER_RATE_LIMIT_MS)
            ?: HealthSyncStateEntity(recordType, cooldownUntilEpochMs = nowMs + HealthSyncPlanner.COOLDOWN_AFTER_RATE_LIMIT_MS),
    )
}
```

4. `markPermissionLost` debe preservar los campos nuevos:

```kotlin
suspend fun markPermissionLost(recordType: String) {
    val current = dao.getState(recordType)
    dao.upsertState(current?.copy(permissionGranted = false) ?: HealthSyncStateEntity(recordType))
}
```

5. Añadir `COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000L` al `HealthSyncPlanner` (constante nueva en la Task 2 se agrega aquí; moverla a Task 2 si se prefiere — una sola definición, en `HealthSyncPlanner`).

**Nota sobre `markSynced` y el flujo de tipo nuevo:** cuando `syncType` termina, `markSynced` fija `nextDueAtEpochMs`; el token queda guardado por el flujo de `drainChanges` (que llama a `save`), y `markSynced` lo conserva vía `copy`. Si un tipo aún no tiene token (`changesToken == null` en el state tras `markSynced`), la próxima selección lo volverá a tratar como nunca sincronizado (debido a `due == null`), lo cual es correcto.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS (nuevos + previos; si `HealthRepositoryTest` o `HealthDatabaseTest` rompen por la firma/entidad, ajustar: el constructor de `HealthRepository` gana el parámetro `pacingMs: Long = PACING_DEFAULT_MS` con default, así que no debería).

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt android/app/src/main/java/com/jhomc/healthsync/data/ChangesTokenStore.kt android/app/src/main/java/com/jhomc/healthsync/HealthSyncPlanner.kt android/app/src/test/java/com/jhomc/healthsync/FakeHealthConnectGateway.kt android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt
git commit -m "feat: select due types by budget with persisted round-robin cursor"
```

---

## Task 4: Enfriamiento ante rate limit (persistido)

**Files:**
- Modify: `android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt`
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt` (ya cubierto en Task 3, verificar)

**Step 1: Escribir el test que falla**

En `HealthRepositorySchedulingTest.kt`:

```kotlin
@Test
fun `rate limit sets cooldown and the type is skipped while cooling`() = runBlocking {
    // OJO: READ_STEPS cubre STEPS + STEPS_CADENCE (permisos compartidos en el
    // SDK 1.1.0, verificado en la Task 3). Se usa SLEEP_SESSION: permiso único,
    // un solo tipo candidato → determinista.
    gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
    gateway.failNextTokenWithRateLimit = true
    runCatching { repo.syncAuthorizedTypes() } // run 1: SLEEP_SESSION → rate limit → cooldown (re-lanza por diseño)
    // El tipo quedó en enfriamiento: una ejecución inmediata no lo toca (cero llamadas).
    gateway.tokenLog.clear(); gateway.readLog.clear(); gateway.changesLog.clear()
    repo.syncAuthorizedTypes()
    assertEquals(0, gateway.tokenLog.size) // criterio 5: una ventana de enfriamiento → cero llamadas fallidas
    assertEquals(0, gateway.readLog.size)
}
```

Nota: `syncAuthorizedTypes` re-lanza `RateLimitedException` tras persistir el cooldown (así el executor sabe que la ejecución se cortó); los tests deben envolver la ejecución en `runCatching`.

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthRepositorySchedulingTest.rate limit sets cooldown and the type is skipped while cooling"`
Expected: FAIL — sin cooldown persistido, la segunda ejecución reintenta y `failNextTokenWithRateLimit` es one-shot, así que la segunda pasaría (o fallaría la aserción por tamaño).

**Step 3: Implementar**

La implementación ya está en la Task 3 (`markCooldown` en el catch de `RateLimitedException` + filtro de cooldown en la selección). Si el test pasa sin cambios adicionales, documentarlo aquí: **la lógica de cooldown queda implementada por la Task 3; esta task es su verificación dedicada.** Si `RateLimitedException` se lanza desde `firstSync`/`drainChanges` (vía `asRateLimitedOrSelf`), el catch central de `syncAuthorizedTypes` lo captura — no hace falta más.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS.

**Step 5: Commit**

```bash
git add android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt
git commit -m "test: cooldown persists after rate limit and skips the type"
```

---

## Task 5: Bootstrap reanudable (token reservado + checkpoint por página)

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt`
- Modify: `android/app/src/main/java/com/jhomc/healthsync/data/ChangesTokenStore.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/FakeHealthConnectGateway.kt` (pageStore ya añadido en Task 3)

**Step 1: Escribir el test que falla**

En `HealthRepositorySchedulingTest.kt`:

```kotlin
@Test
fun `interrupted bootstrap resumes from the last confirmed page`() = runBlocking {
    // SLEEP_SESSION: permiso único (READ_STEPS es compartido, ver Task 3).
    gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
    gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
    gateway.pageStore["pt-1"] = listOf(Fixtures.sleepSession("hc-2", t, t.plusSeconds(3600)))
    gateway.pageStore["pt-2"] = listOf(Fixtures.sleepSession("hc-3", t, t.plusSeconds(3600)))

    // Primera ejecución: se corta (rate limit) tras confirmar la página 1.
    gateway.failReadsWithRateLimit = true
    runCatching { repo.syncAuthorizedTypes() }
    assertTrue(gateway.readLog.map { it.second }.contains("pt-1"))

    // Segunda ejecución: el cooldown (1 h) expira justo en t+1h → reanuda.
    val repoAfterHour = HealthRepository(
        db = db,
        gateway = gateway,
        tokenStore = ChangesTokenStore(db.healthDao()),
        now = { t.plusSeconds(3600) },
        pacer = {},
    )
    repoAfterHour.syncAuthorizedTypes()

    // criterio 3: continúa en la página pendiente (pt-1), no relee desde null.
    val pageTokensSeen = gateway.readLog.map { it.second }
    assertTrue("debe reanudar con el checkpoint guardado", "pt-1" in pageTokensSeen)
    assertTrue("no vuelve a empezar desde null sin necesidad", pageTokensSeen.count { it == null } == 1)
}
```

Ajuste necesario en el fake: `failReadsWithRateLimit` es one-shot (falla la siguiente llamada a `readRecords`). Con `pageStore` (null → pt-1 → pt-2), la primera ejecución hace: `null` (página 1 confirmada, checkpoint "pt-1") → `pt-1` (falla → cooldown). La segunda ejecución reanuda en `pt-1` y completa hasta `null`. El `count { it == null } == 1` confirma que la página inicial no se relee. **No se añade un segundo `failReadsWithRateLimit`.**

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthRepositorySchedulingTest"`
Expected: FAIL — hoy el backfill parte siempre de `pageToken = null` (el checkpoint no se persiste).

**Step 3: Implementar**

En `HealthRepository.kt`:

1. Nueva constante:

```kotlin
private const val BACKFILL_WINDOW_MS = 30L * 24 * 3_600_000
```

2. `syncType` debe reconocer el bootstrap en curso (el token ya está reservado):

```kotlin
suspend fun syncType(entry: RecordTypeEntry): TypeSyncResult {
    val state = dao.getState(entry.typeName)
    val token = state?.changesToken
    val bootstrapInProgress = state?.bootstrapStartEpochMs != null
    return if (token == null || bootstrapInProgress) {
        firstSync(entry)
    } else {
        drainChanges(entry, token)
    }
}
```

3. `firstSync` v2 — reservar y persistir el token + ancla, reanudar backfill:

```kotlin
private suspend fun firstSync(entry: RecordTypeEntry): TypeSyncResult {
    val nowMs = now().toEpochMilli()
    val state = dao.getState(entry.typeName)
    if (state?.bootstrapStartEpochMs == null && state?.changesToken == null) {
        val reserved = try {
            gateway.getChangesToken(setOf(entry.recordClass))
        } catch (e: RemoteException) {
            if (e.isRateLimited()) throw e.asRateLimitedOrSelf()
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        } catch (e: IOException) {
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        } catch (e: SecurityException) {
            return TypeSyncResult(entry.typeName, backfilled = backfill(entry))
        }
        db.withTransaction {
            dao.upsertState(
                state?.copy(
                    changesToken = reserved,
                    permissionGranted = true,
                    lastSuccessfulReadAtEpochMs = nowMs,
                    bootstrapStartEpochMs = nowMs - BACKFILL_WINDOW_MS,
                )
                    ?: HealthSyncStateEntity(
                        recordType = entry.typeName,
                        changesToken = reserved,
                        permissionGranted = true,
                        lastSuccessfulReadAtEpochMs = nowMs,
                        priority = HealthSyncPlanner.initialPriority(entry),
                        bootstrapStartEpochMs = nowMs - BACKFILL_WINDOW_MS,
                    ),
            )
        }
    }
    val anchorMs = dao.getState(entry.typeName)?.bootstrapStartEpochMs ?: (nowMs - BACKFILL_WINDOW_MS)
    val backfilled = resumeBackfill(entry, anchorMs)
    val reservedToken = dao.getState(entry.typeName)?.changesToken
        ?: throw IllegalStateException("bootstrap sin token reservado: ${entry.typeName}")
    val drained = drainChanges(entry, reservedToken, tokenReserved = true)
    return TypeSyncResult(
        recordType = entry.typeName,
        backfilled = backfilled,
        upserts = drained.upserts,
        deletes = drained.deletes,
        tokenAdvanced = drained.tokenAdvanced,
    )
}
```

4. `resumeBackfill` — pagina con checkpoint transaccional:

```kotlin
/** Paginated 30-day backfill that resumes from the persisted page token. */
private suspend fun resumeBackfill(entry: RecordTypeEntry, anchorMs: Long): Int {
    val end = now()
    val start = Instant.ofEpochMilli(anchorMs)
    var pageToken = dao.getState(entry.typeName)?.bootstrapPageToken
    var total = 0
    do {
        val page: ReadRecordsResponse<Record> = try {
            gateway.readRecords(entry.recordClass, start, end, pageToken)
        } catch (e: RemoteException) {
            throw e.asRateLimitedOrSelf()
        }
        val entities = page.records.map { toEntity(it) }
        db.withTransaction {
            dao.applyBackfillPage(entities, now().toEpochMilli())
            dao.upsertState(
                dao.getState(entry.typeName)!!.copy(
                    bootstrapPageToken = page.pageToken,
                    lastSuccessfulReadAtEpochMs = now().toEpochMilli(),
                ),
            )
        }
        total += entities.size
        pageToken = page.pageToken
        if (pageToken != null) pace()
    } while (pageToken != null)
    return total
}
```

5. `pace()`:

```kotlin
private suspend fun pace() {
    if (pacingMs > 0) delay(pacingMs)
}
```

6. Constructor: añadir el parámetro y el companion:

```kotlin
class HealthRepository(
    private val db: HealthDatabase,
    private val gateway: HealthConnectGateway,
    private val tokenStore: ChangesTokenStore,
    private val now: () -> Instant = Instant::now,
    private val pacingMs: Long = PACING_DEFAULT_MS,
) {
    companion object {
        const val PACING_DEFAULT_MS = 2_000L
    }
    ...
```

Import: `kotlinx.coroutines.delay`.

7. `drainChanges` mantiene su flujo; al terminar no cambia (el `markSynced` lo aplica `syncAuthorizedTypes`; los flujos directos de `syncType` desde tests quedan igual, `save` conserva el token).

8. `recoverFromExpiry` y el fallback de `drainChanges` siguen usando `backfill(entry)` (ventana fresca de 30 días, sin checkpoint) — correcto para recuperación tras expiración.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS. (`HealthRepositoryTest` usa `syncType` directo: `firstSync` reserva token y guarda ancla; sin crash, backfill completo y drain — comportamiento igual al previo.)

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt android/app/src/test/java/com/jhomc/healthsync/FakeHealthConnectGateway.kt
git commit -m "feat: resumable 30-day bootstrap with per-page checkpoint"
```

---

## Task 6: Ritmo entre llamadas de páginas (verificación)

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthRepository.kt` (ya implementado en la Task 3: `pace()` + pacer inyectable)
- Create: `android/app/src/test/java/com/jhomc/healthsync/HealthRepositoryPacingTest.kt`

**Step 1: Escribir el test**

`HealthRepositoryPacingTest.kt`:

```kotlin
package com.jhomc.healthsync

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.jhomc.healthsync.data.ChangesTokenStore
import com.jhomc.healthsync.data.HealthDatabase
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class HealthRepositoryPacingTest {

    private lateinit var db: HealthDatabase
    private lateinit var gateway: FakeHealthConnectGateway
    private val t: Instant = Instant.parse("2026-08-08T12:00:00Z")

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            HealthDatabase::class.java,
        ).build()
        gateway = FakeHealthConnectGateway()
        gateway.granted = setOf(RecordTypes.byTypeName("STEPS")!!.permission)
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun `pacer fires between pages but not after the last one`() = runBlocking {
        gateway.pageStore[null] = listOf(Fixtures.steps("hc-1", t, t, count = 1))
        gateway.pageStore["pt-1"] = listOf(Fixtures.steps("hc-2", t, t, count = 2))
        var paces = 0
        val repo = HealthRepository(
            db = db,
            gateway = gateway,
            tokenStore = ChangesTokenStore(db.healthDao()),
            now = { t },
            pacer = { paces++ },
        )
        repo.syncType(RecordTypes.byTypeName("STEPS")!!)
        // 3 páginas (null, pt-1, pt-2) → 2 pausas entre ellas.
        assertTrue("2 pausas entre 3 páginas, hubo $paces", paces == 2)
    }
}
```

**Ajuste de diseño:** en vez de `pacingMs: Long` + `delay`, el constructor recibe `pacer: suspend () -> Unit = { delay(PACING_DEFAULT_MS) }` — testeable sin reloj real. `HealthRepository` de las Tasks anteriores pasa `pacingMs = 0`; se sustituye por `pacer = {}`. Ajustar: Tasks 3/5 usan `pacingMs = 0` en tests → cambiar a `pacer = {}` (default real = delay 2 s).

**Step 2: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS (el pacer ya existe; el test verifica el comportamiento).

**Step 3: Commit**

```bash
git add android/app/src/test/java/com/jhomc/healthsync/HealthRepositoryPacingTest.kt
git commit -m "test: pacer fires between paginated health connect calls"
```

---

## Task 7: Prioridades adaptativas (promoción/democión persistidas)

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/data/ChangesTokenStore.kt` (markSynced ya implementado)
- Modify: `android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt`
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthSyncPlanner.kt` (si falta `COOLDOWN_AFTER_RATE_LIMIT_MS`)

**Step 1: Escribir los tests que fallan**

En `HealthRepositorySchedulingTest.kt`:

```kotlin
@Test
fun `type with recent changes is promoted and overdue again sooner`() = runBlocking {
    // SLEEP_SESSION: permiso único (READ_STEPS es compartido, ver Task 3) y
    // prioridad HIGH inicial (está en HIGH_FREQUENCY_TYPES).
    gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission)
    gateway.pageStore[null] = listOf(Fixtures.sleepSession("hc-1", t, t.plusSeconds(3600)))
    repo.syncAuthorizedTypes()
    val state = db.healthDao().getState("SLEEP_SESSION")!!
    assertEquals(HealthSyncPlanner.PRIORITY_HIGH, state.priority)
    assertEquals(t.toEpochMilli() + 6L * 3_600_000, state.nextDueAtEpochMs!!)
    assertEquals(0, state.emptyRuns)
}

@Test
fun `six empty rounds demote a type from high to cold and stretch its interval`() = runBlocking {
    gateway.granted = setOf(RecordTypes.byTypeName("SLEEP_SESSION")!!.permission) // único tipo → determinista
    // SLEEP_SESSION parte de HIGH (2): 3 rondas vacías → MEDIUM, otras 3 → LOW (7 días).
    gateway.pageStore.clear() // sin datos
    repeat(6) {
        repo = HealthRepository(db, gateway, ChangesTokenStore(db.healthDao()), now = { t.plusSeconds(it * 86_400L) }, pacer = {})
        repo.syncAuthorizedTypes()
    }
    val state = db.healthDao().getState("SLEEP_SESSION")!!
    assertEquals(HealthSyncPlanner.PRIORITY_LOW, state.priority)
    assertEquals(
        7L * 24 * 3_600_000,
        state.nextDueAtEpochMs!! - t.plusSeconds(5 * 86_400L).toEpochMilli(),
    )
}
```

(requiere `now` con reloj ajustable: el test construye repos con `now` distinto; los estados persisten en la misma DB in-memory.)

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthRepositorySchedulingTest"`
Expected: FAIL si `markSynced` no ajusta prioridad (según implementación de la Task 3, `adjustAfterRun` ya aplica; si pasa, la task documenta la verificación y solo añade casos de borde si faltan).

**Step 3: Implementar**

La lógica ya existe en `markSynced` (Task 3) + `HealthSyncPlanner.adjustAfterRun` (Task 2). Verificar y completar: `COOLDOWN_AFTER_RATE_LIMIT_MS = 3_600_000L` en `HealthSyncPlanner` (usado por `markCooldown`). Si todo pasa, no hay código nuevo — solo los tests de la Task 7.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS.

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/HealthSyncPlanner.kt android/app/src/test/java/com/jhomc/healthsync/HealthRepositorySchedulingTest.kt
git commit -m "test: adaptive priorities promote on activity and demote after empty rounds"
```

---

## Task 8: Puertas completas, criterios de aceptación y documentación

**Files:**
- Modify: `docs/plans/archive/2026-08-09-health-connect-sync.md` (tabla de estado + sección §3.1)
- Modify: `docs/plans/archive/2026-08-11-health-sync-quota-scheduling.md` (este plan, marcar tareas ✅ al terminar)

**Step 1: Ejecutar todas las gates Android**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew assembleDebug test`
Expected: BUILD SUCCESSFUL; todos los tests unitarios en verde (≈50+).

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew lint` (si está configurado; si no, omitir)
Expected: sin errores nuevos.

**Step 2: Verificar los 6 criterios de aceptación de §3.1 contra los tests**

| Criterio | Test que lo cubre |
|---|---|
| 1. 38 tipos autorizados → solo el presupuesto | `a run with 38 authorized types calls only the budgeted ones` |
| 2. 5 ejecuciones → tipos distintos por cursor | `five runs rotate across distinct types with persisted cursor` |
| 3. Bootstrap interrumpido continúa en página pendiente | `interrupted bootstrap resumes from the last confirmed page` |
| 4. Incremental sin cambios → cero llamadas | `nothing due means zero health connect calls` |
| 5. Rate limit → 1 fallo por ventana de enfriamiento | `rate limit sets cooldown and the type is skipped while cooling` |
| 6. Todos los tipos revisados en sus intervalos | `three empty rounds demote...` + rotación (criterio 2) |

**Step 3: Actualizar la documentación**

En `docs/plans/archive/2026-08-09-health-connect-sync.md`:
- Fila de la tabla de estado: `| Optimización de cuota y scheduling incremental | ✅ Completa | cursor round-robin persistido, bootstrap reanudable, cooldown, pacing, prioridades adaptativas (commit X) |`
- En §3.1: marcar los 6 criterios como verificados con los nombres de test.
- En Notas §7 (Pendientes): el rate-limit queda re-verificable en dispositivo con el nuevo APK (una pulsación de "Sincronizar AHORA" debe avanzar de tipo en tipo sin ráfagas).

**Step 4: Commit**

```bash
git add docs/plans/archive/2026-08-09-health-connect-sync.md
git commit -m "docs: mark quota scheduling implemented with acceptance criteria"
```

---

## Riesgos y notas

- **Backend intacto:** este plan no toca Python; no se requieren gates de pytest/ruff/mypy. Si algún test backend se ejecuta y falla, no es de este plan (registrar por separado).
- **La verificación real en dispositivo** (reinstalar APK, una pulsación, comprobar avance por tipos y `data/gym.db`) queda fuera del alcance de este plan (requiere el teléfono y reposición de cuota); es el paso siguiente natural tras la Task 8.
- **`markSynced` y tipos sin token:** si un tipo nunca llega a tener token (fallback de rango), el estado queda con `changesToken == null`; la selección lo trata como vencido siempre (`due == null`), pero el filtro de cooldown impide ráfagas de reintentos. Correcto y conservador.
- **Rotación + `MAX_TYPES_PER_RUN = 1`:** con 38 tipos y prioridades, el primer ciclo completo tarda varias horas (lo deseado: progresivo). El cursor persistido garantiza que ningún tipo se quede atrás.
- **Room sin exportSchema:** la migración se prueba con SQL directo (Task 1) y no con `MigrationTestHelper`, evitando la dependencia `room-testing` y los archivos de esquema.
