# Health Connect Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Construir el extractor de Health Connect que integra los datos del Galaxy Watch (Samsung Health) al dashboard: una app Android mínima en Kotlin dentro de `android/` que lee **todos los tipos de datos disponibles** de Health Connect (núcleo primero: steps, heart_rate, sleep, weight, exercise; catálogo completo después), los persiste en Room local como buffer idempotente y los reenvía por HTTPS a un endpoint nuevo de este backend (FastAPI + SQLite), donde quedan disponibles para análisis. Nada de servidor remoto, autenticación compleja, Compose avanzado ni arquitectura empresarial.

**Architecture:** 4 piezas Android sin capas extra: `HealthConnectManager` (solo el SDK), `HealthRepository` (Changes API con token único + mapeo + persistencia), `SyncWorker` (orquesta, sin lógica de negocio), `SyncScheduler` (WorkManager periódico 1h + botón manual). Sincronización diferencial con **un único changes token** para el conjunto de tipos, paginación con `hasMore`, deduplicación por `metadata.id` (UNIQUE), propagación de `DeletionChange`, fallback a rango de 30 días ante expiración del token, y token guardado **solo tras persistencia exitosa**. Room genérico (`health_records` local) como buffer para no perder datos si el Mac está apagado (el token expira a los 30 días). Backend: migración SQLite `v010` con tabla genérica `health_records` (mismo patrón de snapshot desnormalizado y `origen='health_connect'` que `import_nutrition.py`), endpoint único `POST /sync/health-connect` con token secreto `X-Sync-Token` (env `HC_SYNC_TOKEN`), persistencia idempotente con `INSERT OR IGNORE`.

**Tech Stack:** Android: Kotlin, `androidx.health.connect:connect-client:1.1.0` (estable; verificar patch en el momento de implementar), `work-runtime-ktx:2.10.x`, `room:2.6.1` + KSP, `datastore-preferences:1.1.x`, OkHttp, org.json (sin librerías de serialización). Backend: Python 3.11+, FastAPI, SQLite (migraciones versionadas), pytest, ruff, mypy, uv.

---

## 1. Decisiones confirmadas con el usuario

| Decisión | Elección |
|---|---|
| Ubicación del código Android | **`android/` dentro de este repo** (monorepo, máxima del sandbox) |
| Buffer local | **Room en el teléfono + reenvío** a la API (el Mac no está encendido 24/7; token HC expira a los 30 días) |
| Alcance de datos | **Todos los tipos que Health Connect ofrezca** — catálogo canónico expansible; núcleo primero (steps, heart_rate, sleep, weight, exercise), resto por lotes en Fase 6 (misma mecánica: permiso + mapeador) |
| Frecuencia | 1 hora + flex 15 min (ejemplo oficial de Google); ajustable tras medir consumo |
| ExerciseSessionRecord | Se extrae como tipo de dato crudo (resumen de sesión); **sin** mapeo a `training_sets` (granularidad incompatible: series kg/reps vs. sesión) |

## 2. Contexto verificado

| Hecho | Valor |
|---|---|
| SDK Health Connect | `connect-client:1.1.0` estable; serie alpha 1.2.x no recomendada para producción. **Verificar patch actual al implementar** (sin acceso web en la sesión de planificación) |
| Permiso background | `READ_HEALTH_DATA_IN_BACKGROUND` — obligatorio para WorkManager; verificar disponibilidad con `getFeatureStatus(FEATURE_READ_HEALTH_DATA_IN_BACKGROUND)` antes de programar |
| Historial inicial | 30 días antes de otorgar permiso por defecto; permiso `PERMISSION_READ_HEALTH_DATA_HISTORY` para más (no se solicita de entrada) |
| Token de cambios | Expira a los 30 días → el Worker debe correr con suficiente frecuencia; token **único** para el conjunto (se sincronizan juntos) |
| Cambio del ecosistema (jun 2026) | Pasos on-device se atribuyen a un nombre de paquete sintético del dispositivo, no `"android"` — no asumir `dataOrigin.packageName` fijo |
| Plataforma | HC integrado en Android 14+; app descargable en Android 9-13 (el Watch puede ser Android <14) |
| Proyecto existente | Patrón de ingesta idempotente (`INSERT OR IGNORE` + `origen`), migraciones versionadas (v001-v009), CSRF en mutaciones htmx — el endpoint nuevo es API, no htmx, y debe excluirse del CSRF con su propio token |

## 3. Scope / Non-goals / Definition of done

**In scope:**
- Esqueleto Gradle en `android/` (Kotlin, una activity, sin Compose complejo).
- Health Connect: SDK, permisos en lote (núcleo 5 tipos + background), lectura manual bajo demanda.
- Room genérico local + deduplicación por `hc_id` + propagación de borrados.
- Changes API incremental con token único, paginación y fallback por expiración.
- WorkManager: periódico 1h (+ flex 15 min), constraints, `enqueueUniquePeriodicWork(UPDATE)`, botón "Sincronizar ahora".
- Reenvío a la API con cola de pendientes (marca `synced`) y URL/token configurables en la app.
- Backend: migración `v010`, `src/health_sync_service.py`, `POST /sync/health-connect` con `X-Sync-Token`, tests de idempotencia/seguridad.
- Fase 6: catálogo completo de tipos con mapeadores por familia.
- Export CSV, docs y gates.

**Non-goals (v1):** mapeo de sesiones de HC a `training_sets`; análisis/gráficas de los datos HC en el dashboard; Hilt/Dagger, Clean Architecture, UseCases; worker por tipo de dato; Foreground Service; exención de batería; Firebase/Supabase; backend remoto fuera de la red local; sincronización bidireccional; tipos con requisitos especiales de privacidad (presión arterial, glucosa, ciclo menstrual) hasta Fase 6 y con confirmación explícita.

**Definition of done:**
- `android/` compila e instala; HC detectado (`SDK_AVAILABLE`).
- Lectura manual de steps → "steps: N" en pantalla (watch → Samsung Health → HC → Kotlin verificado en dispositivo físico).
- 2 sincronizaciones consecutivas → 0 duplicados; borrado en HC se propaga a Room.
- App cerrada → WorkManager ejecuta → datos nuevos aparecen en Room.
- `POST /sync/health-connect` idempotente (reenvío → `ignored`, no duplica); token inválido → 401; payload inválido → 400.
- Mac apagado varios días → datos acumulados en el teléfono → al volver, todo llega a SQLite.
- Todos los tipos del catálogo elegido: permiso + mapeador + verificación.
- Gates backend en verde (`uv run pytest -q`, `ruff format --check .`, `ruff check .`, `mypy app.py src tests`) y `./gradlew assembleDebug test` sin errores.

## 4. Guardrails

1. TDD: test estrecho rojo → implementación mínima → verde → commit por tarea (backend; en Android, test unitario del repository/worker con fake del cliente).
2. Rama `feature/health-sync`; verificar `git branch --show-current` antes de cada commit. Sin commits de `data/*.db`, `backups/`, `.tmp/` ni `android/.gradle/` (`.gitignore` desde Fase 0).
3. Máxima del sandbox: todo dentro del proyecto; `./gradlew` escribe caches en `android/.gradle` (local del repo) y `~/.gradle` solo si el wrapper lo requiere (documentado en Fase 0; sin artefactos fuera del repo).
4. Backend: SQL parametrizado (`?`); migraciones versionadas sin editar las aplicadas; `v010` se registra tras `v009`; `origen='health_connect'` como marcador (no tocar `'google'|'manual'`).
5. El endpoint nuevo **no** usa el CSRF de formularios htmx: se valida con `X-Sync-Token` (env `HC_SYNC_TOKEN`; si no está definido, 503). Revisar `src/security.py` para excluirlo sin debilitar las rutas htmx.
6. La app Android funciona parcialmente sin permisos completos: sincroniza solo lo autorizado; nunca falla por un permiso faltante de un tipo no esencial (el Worker devuelve `Result.success()` con los tipos concedidos o `failure()` limpio si faltan todos + background).
7. Verificar `git branch --show-current` y los gates de cada fase antes de avanzar.

---

## Phase 0 — Esqueleto del proyecto Android

### Task 0.1: Materializar el plan y baseline
Guardar este documento en `docs/plans/2026-08-09-health-connect-sync.md`. Baseline backend: `uv run pytest -q` (verde, ~345), ruff, mypy. Commit `docs: add health connect sync plan`.

### Task 0.2: Esqueleto Gradle en `android/`
**Files:** Create `android/` (settings.gradle.kts, build.gradle.kts raíz y app, gradle wrapper, `app/src/main/AndroidManifest.xml`, `MainActivity.kt` con TextView mínimo, `.gitignore` con `.gradle/`, `build/`, `local.properties`).
- Kotlin 2.x, `minSdk 26`, `targetSdk` = API instalada (35+), `applicationId com.jhomc.healthsync` (ajustable).
- Dependencias declaradas (versiones a verificar al implementar): `connect-client:1.1.0`, `work-runtime-ktx:2.10.x`, `room:2.6.1` + KSP, `datastore-preferences:1.1.x`, OkHttp.
- Manifest: permisos `READ_STEPS`, `READ_HEART_RATE`, `READ_SLEEP`, `READ_WEIGHT`, `READ_EXERCISE`, `READ_HEALTH_DATA_IN_BACKGROUND`, `INTERNET`; `<queries><package android:name="com.google.android.apps.healthdata"/></queries>`.
- Criterio: `./gradlew assembleDebug` compila; la app abre sin crash. Commit `feat: android project skeleton`.

## Phase 1 — Health Connect + permisos + lectura manual (prueba de humo)

### Task 1.1: `HealthConnectManager` — cliente, disponibilidad, feature background
**Files:** Create `android/app/src/main/java/com/jhomc/healthsync/HealthConnectManager.kt`; Modify `MainActivity.kt`.
- `HealthConnectClient.getOrCreate(context)`; `getSdkStatus` → estado en pantalla (`SDK_AVAILABLE` / `SDK_UNAVAILABLE_*`); `getFeatureStatus(FEATURE_READ_HEALTH_DATA_IN_BACKGROUND)`.
- Criterio: la app muestra "Health Connect: disponible" (o guía de instalación). Commit `feat: health connect client and availability`.

### Task 1.2: Permisos en lote (núcleo) + estado por tipo
**Files:** Modify `MainActivity.kt`; Create `android/.../RecordTypes.kt`.
- `RecordTypes.kt`: catálogo canónico núcleo `(class, HealthPermission.getReadPermission, mapeador)`: `StepsRecord`, `HeartRateRecord`, `SleepSessionRecord`, `WeightRecord`, `ExerciseSessionRecord` + background.
- `registerForActivityResult(PermissionController.createRequestPermissionResultContract())` → solicita el lote; la UI muestra ✓ por tipo y "Permisos: N/5 + background".
- Criterio: concesión en pantalla; permiso revocado se refleja al reabrir. Commit `feat: batch permission request with per-type state`.

### Task 1.3: Lectura manual de `StepsRecord` (sin automatizar nada)
**Files:** Modify `HealthConnectManager.kt` (read manual), `MainActivity.kt` (botón).
- Botón "Leer pasos (24h)": `ReadRecordsRequest(StepsRecord::class, timeRangeFilter = between(now−24h, now))` → muestra "Steps: N".
- Criterio: **dispositivo físico** (watch+teléfono): el contador coincide con Samsung Health. Sin Room, sin WorkManager todavía. Commit `feat: manual steps read`.

## Phase 2 — Persistencia, deduplicación y sincronización diferencial

### Task 2.1: Room genérico local
**Files:** Create `android/.../data/HealthDatabase.kt` (`health_records`: `hc_id` TEXT PK, `tipo`, `start_epoch_ms`, `end_epoch_ms`, `value_json`, `synced` INT, `created_at`); DAO con `upsertAll` (`INSERT OR REPLACE`), `deleteByHcIds`, `getPending` (`synced=0`), `markSynced`.
- Criterio: test unitario del DAO: insertar 2 veces el mismo `hc_id` → 1 fila. Commit `feat: room local buffer with dedup`.

### Task 2.2: Mapeadores de los 5 tipos núcleo
**Files:** Create `android/.../data/RecordMappers.kt`.
- `Record → Map<String, Any?>` por familia: base (start/end, `dataOrigin`, `metadata.id`), series (pasos count), muestras (HR `samples` → array {bpm, time}), sesiones (exercise/sleep: title, duración, tipos de ejercicio).
- Criterio: mapeo determinista y serializable con org.json. Commit `feat: mappers for core record types`.

### Task 2.3: `HealthRepository` — Changes API incremental
**Files:** Create `android/.../HealthRepository.kt`, `ChangesTokenStore.kt` (DataStore).
- Flujo: token nulo → lectura histórica 30 días por rango (paginación `pageToken`) → persistir → `getChangesToken(ChangesTokenRequest(recordTypes))` guardado **solo tras persistir**; token existente → loop `getChanges(token)` paginando `hasMore`: `UpsertionChange` → upsert, `DeletionChange` → delete, filtrar `dataOrigin` propio; `ChangesTokenExpiredException` → fallback rango 30 días + token nuevo; `SecurityException` → propagar como fallo permanente.
- Criterio: test con cliente fake: upserts/borrados aplicados, token avanzado solo en éxito, 2 syncs → 0 duplicados. Commit `feat: incremental changes sync with token`.

### Task 2.4: Botón "Sincronizar ahora" (one-time)
**Files:** Modify `MainActivity.kt`, `SyncScheduler.kt` (nuevo).
- `OneTimeWorkRequestBuilder<SyncWorker>` con constraints de red + `setExpedited`; resultado visible en pantalla (contadores por tipo).
- Criterio: ejecutar sync manual dos veces seguidas → "nuevos: 0" la segunda; borrar un registro en Samsung Health → aparece en la segunda sync como borrado. Commit `feat: manual one-time sync`.

## Phase 3 — WorkManager periódico en segundo plano

### Task 3.1: `SyncWorker` + scheduler periódico
**Files:** Create `android/.../SyncWorker.kt`; Modify `SyncScheduler.kt`.
- `doWork()`: `getSdkStatus` ≠ SDK_AVAILABLE → `failure()`; permisos+background (feature status) → si faltan todos, `failure()` limpio; si faltan tipos no esenciales, sincroniza los concedidos; `repository.sync()` → `Result.success()`; excepción de red/temporal → `Result.retry()` (backoff exponencial 30 min); `SecurityException` → `failure()`.
- `PeriodicWorkRequestBuilder(1h, flex 15 min)` + `Constraints(red conectada, batería no baja)` + `enqueueUniquePeriodicWork("health_connect_sync", UPDATE)`.
- **Files:** Modify `MainActivity.kt` — tras concesión de permisos → `scheduleHealthSync()`. Sin receiver BOOT (WorkManager lo cubre) ni Foreground Service.
- Criterio: **MVP-8**: cerrar la app → esperar → datos nuevos de Samsung Health aparecen en Room. Commit `feat: periodic background sync worker`.

## Phase 4 — Backend: ingesta idempotente

### Task 4.1: Migración `v010_health_connect`
**Files:** Create `src/migrations/v010_health_connect.py`; Modify `src/migrations/runner.py`, `tests/test_database.py`.
- Tabla genérica (patrón snapshot de `v007`):
  ```sql
  CREATE TABLE IF NOT EXISTS health_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      hc_id TEXT NOT NULL UNIQUE,
      tipo TEXT NOT NULL,
      start_epoch_ms INTEGER NOT NULL,
      end_epoch_ms INTEGER,
      value_json TEXT NOT NULL,
      dispositivo TEXT NOT NULL DEFAULT 'android',
      origen TEXT NOT NULL DEFAULT 'health_connect',
      recibido_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_health_records_tipo_start ON health_records(tipo, start_epoch_ms);
  ```
- Registrar tras v009; añadir a `_DOMAIN_TABLES`. Tests: `MAX(version)==10`, UNIQUE(hc_id) duplicado → rechazo. Commit `feat: v010 health records table`.

### Task 4.2: Modelo y servicio de ingesta
**Files:** Modify `src/models.py`; Create `src/health_sync_service.py`; Modify `src/database.py`; `tests/test_health_sync_service.py`.
- `HealthRecordInput(hc_id, tipo, start_epoch_ms, end_epoch_ms|None, value: dict)` + `HealthSyncPayload(device, records)` tipados; `ValidationError` para hc_id vacío, timestamp no int, `value` no dict, tipo fuera del catálogo.
- `ingest_health_records(db, payload) -> IngestResult(inserted, ignored)` con `INSERT OR IGNORE` (patrón `import_nutrition.py`); `recibido_at` ISO server-side.
- Tests: payload válido → inserted; reenvío idéntico → ignored (0 duplicados); tipo desconocido → `ValidationError`. Commit `feat: health ingest service with idempotent insert`.

### Task 4.3: Ruta API con token secreto
**Files:** Modify `app.py`, `config.py`, `src/security.py` (excluir endpoint del CSRF htmx sin debilitar el resto), `tests/test_app.py`.
- `config.py`: `HC_SYNC_TOKEN = os.environ.get("HC_SYNC_TOKEN", "")`; si vacío → la ruta devuelve 503 "no configurado".
- `POST /sync/health-connect`: header `X-Sync-Token` requerido (comparación de strings segura) → 401 si no coincide; body validado por servicio → 400 con aviso seguro en caso de `ValidationError`; 200 `{inserted, ignored, received}`.
- Tests: sin env → 503; token incorrecto → 401; correcto + payload → 200 e inserts; doble POST → `ignored>0`. Commit `feat: sync endpoint with token auth`.

### Task 4.4: Verificación end-to-end del pipeline
Criterio: con la app en Fase 3 lista, URL del Mac (LAN) configurada → los datos del teléfono llegan a SQLite; export temporal por SQL (`SELECT tipo, COUNT(*)`) coincide con la pantalla de la app. Sin commit de BD. Commit `test: e2e sync from device to sqlite`.

## Phase 5 — Reenvío de pendientes y configuración en la app

### Task 5.1: Cola de reenvío en `HealthRepository`
- Tras `sync()` exitoso: subir `getPending()` a la API (`POST /sync/health-connect` con URL+token de config); `markSynced` solo con 2xx; fallo de red → queda pendiente y el Worker reintenta en la siguiente corrida (backoff ya cubierto).
- Criterio: **MVP-9**: Mac apagado 2 días → el teléfono acumula; al encender el Mac, la siguiente corrida sube todo (0 pérdidas). Commit `feat: pending upload queue`.

### Task 5.2: URL y token configurables en pantalla
**Files:** Modify `MainActivity.kt` (dos campos + persistencia en DataStore).
- Campos: `http://192.168.x.x:8000` y token; la sync manual usa la config guardada.
- Criterio: cambiar la URL y sincronizar sin rebuild. Commit `feat: configurable api url and token`.

## Phase 6 — Catálogo completo de tipos

### Task 6.1: Ampliar `RecordTypes.kt` y permisos
- Incorporar por lotes los tipos restantes que Samsung Health escribe: calorías (activas/totales), distancia, velocidad, cadencia, potencia, FC reposo, HRV (RMSSD), SpO₂, temperatura, frecuencia respiratoria, pisos, composición corporal (masa grasa/magra/IMC/agua/hueso), altura.
- Cada entrada: `(class, permiso, mapeador)`; mapeadores por familia (muestras, series, sesiones, métricas instantáneas).
- Los tipos con requisitos especiales (presión arterial, glucosa, ciclo) quedan marcados como `REVIEW` y se piden con confirmación explícita del usuario antes de activarlos (no se incluyen en el lote por defecto).
- Criterio: por cada lote: permiso concedido, mapeo verificado en BD real, `value_json` coherente. Commits por lote (`feat: extended record catalog batch N`).

## Phase 7 — Export, documentación y cierre

### Task 7.1: Export CSV de `health_records`
- `GET /exportar/health-connect.csv` (patrón del export existente) con columnas `tipo, hc_id, start_epoch_ms, end_epoch_ms, value_json, dispositivo, recibido_at`.
- Test: CSV generado con filas ordenadas por `(tipo, start_epoch_ms)`. Commit `feat: health records csv export`.

### Task 7.2: Docs
- `AGENTS.md`: sección HealthSync (estructura `android/`, catálogo de tipos, ruta `/sync/health-connect`, `HC_SYNC_TOKEN`, tabla `health_records`).
- `docs/architecture/security-model.md`: endpoint de API con token propio fuera del CSRF htmx.
- `docs/operations/local-development.md`: cómo correr la app, URL/token, ADB para forzar el worker (`adb shell cmd jobscheduler run`).
- Commit `docs: health sync contract and operations`.

### Task 7.3: Gates finales y smoke
- Backend: `uv run pytest -q`, ruff, mypy. Android: `./gradlew assembleDebug test`.
- Smoke real: watch → Samsung Health → HC → Room → API → SQLite; export CSV; análisis pandas básico sobre `health_records` (una consulta de ejemplo).
- Commit `chore: final gates`.

### Task 7.4: Integración (solo con aprobación explícita del usuario)
`git merge main` si pasó tiempo → gates → merge a `main` → `git branch -d feature/health-sync`. Commit final + reporte.

---

**Riesgos:** Health Connect no es testeable en emulador estándar (dispositivo físico obligatorio para validar fases 1-3); Samsung Health puede retrasar la aparición de datos (la ventana de solapamiento y la idempotencia lo absorben); versiones de dependencias a confirmar al implementar (sin acceso web en planificación); el Watch puede correr Android <14 (requiere la app Health Connect descargada); el cambio de `dataOrigin` sintético (jun 2026) invalida cualquier filtro por paquete; `HC_SYNC_TOKEN` sin configurar degrada la ruta a 503 (documentado, no silencioso).
