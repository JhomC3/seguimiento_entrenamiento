# HealthSync Simplified UI Implementation Plan

> **Estado (2026-08-12):** 5/5 tasks **implementadas** y **verificadas en dispositivo**
> (commits `88adf19`…`51dce6b`; suite Android en verde, `assembleDebug` OK).
> - Catálogo recortado a los 17 tipos esenciales; los 4 nuevos llegaron a `gym.db`
>   con datos reales: `DISTANCE` 108, `BASAL_METABOLIC_RATE` 36, `OXYGEN_SATURATION` 46, `VO2_MAX` 3.
> - Ampliación posterior al plan: el formulario URL/token/Guardar se **eliminó por completo**
>   y el destino se embebe en los builds debug vía `BuildConfig.DEFAULT_SYNC_URL` /
>   `DEFAULT_SYNC_TOKEN` (token leído de `data/hc_sync_token` en build-time; release sin secreto) — `51dce6b`.
> - El protocolo en el teléfono quedó reducido a: abrir la app → "Permisos esenciales" → "Sincronizar AHORA".

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reducir HealthSync a una app minimalista con exactamente los 17 tipos esenciales (los 13 actuales + DISTANCE, VO2_MAX, OXYGEN_SATURATION, BASAL_METABOLIC_RATE), sin botones de diagnóstico, sin desgloses de texto y sin la prueba de pasos 24h.

**Architecture:** `RecordTypes.all` pasa a ser la única fuente de verdad con 17 entradas: el sync, la petición de permisos y el inventario la consumen automáticamente. El manifest declara los 4 permisos nuevos (sin declaración, Health Connect no los ofrece en el diálogo). La UI queda con: panel de estado, URL/token/Guardar, "Permisos esenciales" y "Sincronizar AHORA". Backend sin cambios (allow-list amplia, inofensiva).

**Tech Stack:** Kotlin, Robolectric, Room, WorkManager, Gradle desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle` y `JAVA_HOME=/opt/homebrew/opt/openjdk@21`. Sin cambios en Python.

**Referencias:** este plan se apoya en `docs/plans/2026-08-09-health-connect-sync.md` (arquitectura del pipeline, fases 0–5 completas y verificadas) y en `docs/plans/2026-08-11-health-sync-quota-scheduling.md` (scheduling, 8/8 tasks implementadas; la agenda adaptativa se reemplazó por ventanas fijas).

---

## Task 1: Manifest — declarar los 4 permisos nuevos

**Files:**
- Modify: `android/app/src/main/AndroidManifest.xml`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/ManifestContractTest.kt`

**Step 1: Escribir el test que falla**

En `ManifestContractTest.kt`, añadir:

```kotlin
@Test
fun manifest_declares_the_four_new_essential_permissions() {
    val content = manifest.readText()
    for (permission in listOf(
        "android.permission.health.READ_DISTANCE",
        "android.permission.health.READ_VO2_MAX",
        "android.permission.health.READ_OXYGEN_SATURATION",
        "android.permission.health.READ_BASAL_METABOLIC_RATE",
    )) {
        assertTrue("falta $permission en el manifest", content.contains(permission))
    }
}
```

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.ManifestContractTest"`
Expected: FAIL — ninguno de los 4 permisos está declarado.

**Step 3: Implementar**

En `AndroidManifest.xml`, junto a las declaraciones existentes (después de `READ_LEAN_BODY_MASS`):

```xml
    <uses-permission android:name="android.permission.health.READ_DISTANCE" />
    <uses-permission android:name="android.permission.health.READ_VO2_MAX" />
    <uses-permission android:name="android.permission.health.READ_OXYGEN_SATURATION" />
    <uses-permission android:name="android.permission.health.READ_BASAL_METABOLIC_RATE" />
```

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS (todo el suite).

**Step 5: Commit**

```bash
git add android/app/src/main/AndroidManifest.xml android/app/src/test/java/com/jhomc/healthsync/ManifestContractTest.kt
git commit -m "feat: declare the four new essential health permissions"
```

---

## Task 2: Catálogo esencial — 17 tipos

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/RecordTypes.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/RecordTypesTest.kt`

**Step 1: Escribir los tests que fallan**

En `RecordTypesTest.kt`, añadir y ajustar:

```kotlin
@Test
fun `catalog is the essential seventeen types`() {
    assertEquals(17, RecordTypes.all.size)
    val names = RecordTypes.all.map { it.typeName }.toSet()
    for (essential in listOf(
        "STEPS", "HEART_RATE", "SLEEP_SESSION", "EXERCISE_SESSION",
        "ACTIVE_CALORIES_BURNED", "TOTAL_CALORIES_BURNED", "RESTING_HEART_RATE",
        "WEIGHT", "HEIGHT", "BODY_FAT", "BONE_MASS", "BODY_WATER_MASS", "LEAN_BODY_MASS",
        "DISTANCE", "VO2_MAX", "OXYGEN_SATURATION", "BASAL_METABOLIC_RATE",
    )) assertTrue("falta $essential", names.contains(essential))
}

@Test
fun `catalog excludes irrelevant and sensitive types`() {
    val names = RecordTypes.all.map { it.typeName }.toSet()
    for (excluded in listOf(
        "ELEVATION_GAINED", "SPEED", "STEPS_CADENCE", "CYCLING_PEDALING_CADENCE",
        "POWER", "FLOORS_CLIMBED", "WHEELCHAIR_PUSHES", "HEART_RATE_VARIABILITY_RMSSD",
        "RESPIRATORY_RATE", "SKIN_TEMPERATURE", "BODY_TEMPERATURE",
        "BASAL_BODY_TEMPERATURE", "HYDRATION", "NUTRITION",
        "BLOOD_PRESSURE", "BLOOD_GLUCOSE", "CERVICAL_MUCUS", "MENSTRUATION_FLOW",
        "MENSTRUATION_PERIOD", "INTERMENSTRUAL_BLEEDING", "OVULATION_TEST", "SEXUAL_ACTIVITY",
    )) assertFalse("no debe existir $excluded", names.contains(excluded))
    assertTrue(
        "ningún tipo sensible en el catálogo",
        RecordTypes.all.none { it.sensitivity == Sensitivity.SENSITIVE },
    )
}
```

Eliminar el test `medical family is fully sensitive` (la familia MEDICAL ya no existe en el catálogo).

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.RecordTypesTest"`
Expected: FAIL — el catálogo tiene 39 entradas, no 17.

**Step 3: Implementar**

En `RecordTypes.kt`:

1. **Imports:** eliminar las 22 clases excluidas: `ElevationGainedRecord`, `SpeedRecord`, `StepsCadenceRecord`, `CyclingPedalingCadenceRecord`, `PowerRecord`, `FloorsClimbedRecord`, `WheelchairPushesRecord`, `HeartRateVariabilityRmssdRecord`, `RespiratoryRateRecord`, `SkinTemperatureRecord`, `BodyTemperatureRecord`, `BasalBodyTemperatureRecord`, `HydrationRecord`, `NutritionRecord`, `BloodPressureRecord`, `BloodGlucoseRecord`, `CervicalMucusRecord`, `MenstruationFlowRecord`, `MenstruationPeriodRecord`, `IntermenstrualBleedingRecord`, `OvulationTestRecord`, `SexualActivityRecord`.

2. **La lista `all`** queda:

```kotlin
object RecordTypes {

    /**
     * Catálogo ESENCIAL: solo los tipos que el dashboard realmente consume.
     * Los 13 del núcleo (Samsung Health los escribe) + 4 añadidos a petición
     * (distancia, VO2 máx, saturación de oxígeno y tasa metabólica basal).
     * Excluidos a propósito (superficie del SDK 1.1.0 que no aporta al
     * dashboard): elevación, velocidad, cadencias, potencia, pisos, empujes
     * de silla, HRV, frecuencia respiratoria, temperaturas, hidratación,
     * nutrición y todos los tipos sensibles/médicos (presión, glucosa, ciclo
     * menstrual, ovulación, actividad sexual).
     */
    val all: List<RecordTypeEntry> = listOf(
        // --- Núcleo (Samsung Health los escribe) ---
        entry("STEPS", StepsRecord::class, MappingFamily.INTERVAL, core = true),
        entry("HEART_RATE", HeartRateRecord::class, MappingFamily.SERIES, core = true, aggregated = true),
        entry("SLEEP_SESSION", SleepSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("EXERCISE_SESSION", ExerciseSessionRecord::class, MappingFamily.SESSION, core = true),
        entry("ACTIVE_CALORIES_BURNED", ActiveCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true),
        entry("TOTAL_CALORIES_BURNED", TotalCaloriesBurnedRecord::class, MappingFamily.INTERVAL, core = true),
        entry("RESTING_HEART_RATE", RestingHeartRateRecord::class, MappingFamily.INSTANT, core = true),
        entry("WEIGHT", WeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("HEIGHT", HeightRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_FAT", BodyFatRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BONE_MASS", BoneMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("BODY_WATER_MASS", BodyWaterMassRecord::class, MappingFamily.COMPOSITION, core = true),
        entry("LEAN_BODY_MASS", LeanBodyMassRecord::class, MappingFamily.COMPOSITION, core = true),

        // --- Añadidos a petición del usuario ---
        entry("DISTANCE", DistanceRecord::class, MappingFamily.INTERVAL),
        entry("VO2_MAX", Vo2MaxRecord::class, MappingFamily.INSTANT),
        entry("OXYGEN_SATURATION", OxygenSaturationRecord::class, MappingFamily.SERIES),
        entry("BASAL_METABOLIC_RATE", BasalMetabolicRateRecord::class, MappingFamily.INSTANT),
    )
```

El resto de `RecordTypes` (`byTypeName`, `byClass`, `core`, `optionalByFamily`, `entry`) NO cambia.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS (si algún otro test referencia un tipo eliminado — p. ej. comentarios — ajustar solo lo imprescindible).

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/RecordTypes.kt android/app/src/test/java/com/jhomc/healthsync/RecordTypesTest.kt
git commit -m "feat: trim catalog to the 17 essential health types"
```

---

## Task 3: Gestor simplificado

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/HealthConnectManager.kt`
- Modify: `android/app/src/test/java/com/jhomc/healthsync/HealthConnectManagerTest.kt`

**Step 1: Escribir los tests que fallan**

En `HealthConnectManagerTest.kt`, sustituir los tests de familias/estados/smoke por:

```kotlin
@Test
fun `core permissions include every catalog type plus background and history`() = runBlocking {
    val expected = RecordTypes.all.map { it.permission }.toSet() +
        androidx.health.connect.client.permission.HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND +
        androidx.health.connect.client.permission.HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY
    assertEquals(expected, manager.corePermissions())
}

@Test
fun `core batch is exactly the essential catalog`() {
    assertEquals(RecordTypes.all.map { it.typeName }.toSet(), manager.corePermissions().let { perms ->
        RecordTypes.all.filter { it.permission in perms }.map { it.typeName }.toSet()
    })
}
```

Eliminar: el test de `type states reflect granted permissions`, `unavailable sdk marks every type...`, `steps smoke read...` y cualquier referencia a `familyPermissions`.

**Step 2: Ejecutar para ver que falla**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew testDebugUnitTest --tests "com.jhomc.healthsync.HealthConnectManagerTest"`
Expected: FAIL — `corePermissions` no incluye background/history.

**Step 3: Implementar**

En `HealthConnectManager.kt`:

```kotlin
    /**
     * Permisos ESENCIALES: el catálogo completo (17 tipos) + lectura en
     * segundo plano + historial. Un solo botón pide todo.
     */
    fun corePermissions(): Set<String> =
        RecordTypes.all.map { it.permission }.toSet() +
            HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND +
            HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY
```

Eliminar: `familyPermissions`, `typeStates`, el enum `TypeStatus`, `stepsLast24h`. Conservar: `sdkStatus`, `isCompatible`, `backgroundReadAvailable`, `catalog`, `providerDetail`, `gateway()`.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS.

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/HealthConnectManager.kt android/app/src/test/java/com/jhomc/healthsync/HealthConnectManagerTest.kt
git commit -m "refactor: simplify manager to essential permissions only"
```

---

## Task 4: MainActivity minimalista

**Files:**
- Modify: `android/app/src/main/java/com/jhomc/healthsync/MainActivity.kt`

**Step 1: Implementar la nueva UI**

Reemplazar `onCreate` (líneas 36-186) por:

```kotlin
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (intent?.action == RATIONALE_ACTION) {
            showPrivacyPolicy()
            return
        }
        // Worker periódico: 1 h, sincroniza solo tipos vencidos (agenda por
        // ventanas). El botón "Sincronizar AHORA" fuerza todo al instante.
        SyncScheduler.schedulePeriodic(this)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            setContentView(
                TextView(this).apply {
                    text = "HealthSync\nNo compatible: Health Connect requiere Android 9+ (API 28)"
                    textSize = 18f
                    setPadding(32, 32, 32, 32)
                },
            )
            return
        }

        statusView = TextView(this).apply { textSize = 14f; setPadding(8, 8, 8, 8) }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(statusView)
        }

        // --- Destino (URL + token cifrado en Keystore) ---
        root.addView(TextView(this).apply { text = "Destino (URL del servidor)" })
        urlInput = EditText(this).apply {
            hint = "https://mac.local:8443/sync/health-connect"
            inputType = InputType.TYPE_TEXT_VARIATION_URI
        }
        root.addView(urlInput)
        tokenInput = EditText(this).apply {
            hint = "Token de sincronización (X-Sync-Token)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        root.addView(tokenInput)

        root.addView(Button(this).apply {
            text = "Guardar"
            setOnClickListener { saveTarget() }
        })

        // --- Permisos esenciales (un solo diálogo con los 17) ---
        root.addView(Button(this).apply {
            text = "Permisos esenciales"
            setOnClickListener { requestPermissions(manager.corePermissions()) }
        })

        // --- Sincronizar todo ahora (fuerza, pantalla apagada OK) ---
        root.addView(Button(this).apply {
            text = "Sincronizar AHORA"
            setOnClickListener { runDirectSync() }
        })

        setContentView(ScrollView(this).apply { addView(root) })

        permissionLauncher = registerForActivityResult(
            permissionContract(),
            ActivityResultCallbackAdapter { granted ->
                (manager.gateway() as? RealHealthConnectGateway)?.invalidatePermissionCache()
                statusView.text = "Permisos concedidos: ${granted.size}."
            },
        )
        notificationPermissionLauncher = registerForActivityResult(
            androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
        ) { /* sin notificación visible el servicio sigue funcionando */ }
        observeSyncProgress()
        loadTarget()
    }
```

**Step 2: Eliminar las funciones huérfanas**

Borrar (y sus botones ya no existen): `onResume` (el dump), `openHealthConnect`, `refreshStates`, `readStepsSmoke`, `runDiagnostics`, `showSyncState`, `runBinderDiagnostics`, `runTodayInventory`, `statusText`, `fullErrorChain` (si el compilador confirma que no hay más usos).

**Step 3: Conservar obligatoriamente**

`showPrivacyPolicy` (contrato del proveedor), `permissionContract`, `requestPermissions`, `saveTarget`, `showMessage`, `loadTarget`, `runDirectSync`, `observeSyncProgress`, `showSyncResult`, `requestNotificationPermissionIfNeeded`, `onActivityResult`.

**Step 4: Ejecutar para ver que pasa**

Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test`
Expected: PASS. Si el compilador reporta imports/identificadores sin uso (p. ej. `Sensitivity`, `RecordTypes.byTypeName` en botones eliminados), limpiarlos.

**Step 5: Commit**

```bash
git add android/app/src/main/java/com/jhomc/healthsync/MainActivity.kt
git commit -m "feat: minimal healthsync ui with essential permissions and sync only"
```

---

## Task 5: Gates, APK y verificación en el teléfono

1. **Gates Android:**
   Run: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew test assembleDebug`
   Expected: BUILD SUCCESSFUL; suite completa en verde (debug + release).

2. **Instalar** `android/app/build/outputs/apk/debug/app-debug.apk`.

3. **Protocolo en el teléfono:**
   - La pantalla muestra solo: panel de estado, URL + token + Guardar, "Permisos esenciales", "Sincronizar AHORA".
   - Pulsar "Permisos esenciales" → el diálogo de Health Connect ofrece los 17 → conceder.
   - Pulsar "Sincronizar AHORA" una vez → notificación con progreso → termina con resumen.
   - Verificar en el Mac: `sqlite3 data/gym.db "SELECT record_type, COUNT(*) FROM health_records WHERE deleted_at IS NULL GROUP BY record_type;"` → deben aparecer `DISTANCE`, `VO2_MAX`, `OXYGEN_SATURATION`, `BASAL_METABOLIC_RATE` (con datos reales o 0 si Samsung no los escribe — el SpO2 sin sensor en el Redmi es esperado).

4. **Backend:** sin cambios; opcionalmente correr `uv run pytest -q` para confirmar que nada se rompió (no debería).

---

## Notas y riesgos

- Los estados Room de tipos eliminados (STEPS_CADENCE, etc.) quedan huérfanos pero inofensivos: el sync solo itera el catálogo nuevo.
- Los datos ya sincronizados en `gym.db` de tipos eliminados se conservan (no se borran).
- `HealthInventory` (clase + tests) se conserva aunque su botón desaparezca: es diagnóstico reutilizable y su eliminación añadiría churn sin valor.
- Si un test referencia un tipo eliminado tras la Task 2, ajustar solo lo imprescindible (p. ej. `HealthRepositoryPacingTest` solo tiene un comentario sobre STEPS_CADENCE — no requiere cambio).
