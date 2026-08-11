# Health Connect Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

> **Estado (2026-08-10):** Phases 0–5 **implementadas** (35 commits en `feature/health-sync`).
> Backend verificado end-to-end (tests, gates y smoke local). App Android funcional en
> dispositivo (permisos concedidos, agregación de pasos OK). **Pendiente:** smoke real
> completo (datos del teléfono → Mac), bloqueado por el **rate limiting de Health Connect**
> (ver Notas de ejecución §3), e integración a `main` (Task 5.3, con aprobación explícita).

| Fase | Estado | Evidencia |
|---|---|---|
| 0 — Baseline, seguridad y esqueleto | ✅ Completa | `317c50a`, `aa6b97a`; APK compila; contrato v1 + CSRF exacto |
| 1 — Catálogo, permisos, humo | ✅ Completa | `1929f06`, `bc076ef`; 38 tipos verificados contra el AAR; permisos concedidos en dispositivo |
| 2 — Room, mapeadores, Changes | ✅ Completa | `16ad760`, `863904d`, `f5a75fc`; 31 tests Android |
| 3 — Backend v010 + ingesta + endpoint | ✅ Completa | `494d370`, `872aedc`, `d61bd5b`; 379 tests; smoke curl OK |
| 4 — Entrega HTTP, destinos, worker | ✅ Completa | `6cac5f7`; outbox por destino + seed; `HealthSyncClient` testado |
| 5 — Resiliencia, export, docs | ✅ Completa | `bb713a9`, `0e76ce2`; fixtures cruzados; CSV; docs operativas |
| Optimización de cuota y scheduling incremental | ✅ Completa | `b12ad70`, `6d04d5d`, `478ba07`, `cf5fc2c`; cursor round-robin persistido, bootstrap reanudable, cooldown, pacing y prioridades adaptativas; 6 criterios verificados |
| Smoke real en dispositivo | 🔄 En curso | Permisos OK, agregación OK; **bloqueado por rate limit** (notas §3) |
| Integración a `main` (Task 5.3) | ⏳ Pendiente | Requiere aprobación explícita del usuario |

**Goal:** Construir una app Android Kotlin dentro de `android/` que extrae y conserva **todos los tipos de `Record` disponibles para el dispositivo en la versión fijada de Health Connect**, procedentes de Samsung Health/Galaxy Watch y otras fuentes autorizadas; los replica de forma fiable al dashboard mediante FastAPI + SQLite, primero en el Mac y posteriormente en cualquier host HTTPS persistente sin reescribir la app Android.

**Architecture:** La app separa la sincronización de origen (Health Connect → Room) de la entrega (Room → destino HTTP). `HealthConnectManager` encapsula el SDK, `HealthRepository` mantiene un token por tipo, aplica cambios y publica operaciones en un outbox, `SyncWorker` orquesta y `SyncScheduler` programa los trabajos. Room es la fuente local de continuidad y conoce los destinos de entrega; FastAPI recibe lotes versionados e idempotentes, aplica upserts y bajas lógicas en SQLite y confirma cada operación. No se añade Clean Architecture, Hilt, Firebase, Compose complejo ni infraestructura remota obligatoria.

**Tech Stack:** Android: Kotlin, `androidx.health.connect:connect-client:1.1.0` (confirmar parche estable antes de fijarlo), WorkManager, Room + KSP, DataStore, Android Keystore, OkHttp y `org.json`. Backend: Python 3.11+, FastAPI, SQLite, migraciones versionadas, pytest, ruff, mypy y uv. Transporte: HTTPS con certificado confiable; nunca HTTP en builds release.

---

## 1. Decisiones confirmadas y límites reales

| Decisión | Elección |
|---|---|
| Ubicación Android | `android/` dentro de este repositorio. |
| Alcance | Todos los `Record` soportados por la versión fijada del SDK y disponibles en el teléfono. El catálogo es explícito y versionado; no se usa reflexión ni se promete un tipo que el dispositivo/SDK no exponga. |
| Datos sensibles | Se incluyen también los tipos con sensibilidad especial cuando el usuario los autorice en la pantalla oficial de Health Connect. La app informa qué se activó, no envía rutas/biometría/medicina sin el permiso correspondiente. |
| Historial inicial | 30 días por defecto. El permiso de historial amplía el rango solo si el usuario lo concede. "Todos los tipos" no equivale a historial ilimitado. |
| Modelo de datos | Registros crudos con procedencia y revisión; `ExerciseSessionRecord` no se convierte en `training_sets`. |
| Destino inicial | FastAPI + SQLite en el Mac por HTTPS en la red privada. |
| Destino futuro | Cualquier host HTTPS persistente. La URL no contiene ninguna suposición de Mac, IP LAN o proveedor. |
| Frecuencia | WorkManager despierta de forma eventual (objetivo 1 h), pero un planificador por tipo decide qué toca leer; sync manual disponible. |

### Principios no negociables

1. La app obtiene el estado desde Health Connect aunque el destino esté caído; la entrega nunca impide avanzar los tokens de origen una vez Room confirmó el cambio.
2. Un registro puede insertarse, actualizarse o borrarse. Las tres operaciones se replican hasta recibir confirmación individual del servidor.
3. `metadata.id` identifica un registro de Health Connect; además se conserva tipo, origen y `lastModifiedTime`. Un `INSERT OR IGNORE` no es suficiente para cambios posteriores.
4. Cada tipo tiene su propio token y cursor. Revocar o no autorizar un tipo no detiene los que sí están autorizados.
5. No se suma ni se interpreta automáticamente la información cruda. Por ejemplo, pasos de distintos orígenes pueden solaparse; cualquier métrica futura debe elegir una política de origen/agregación explícita.
6. Toda petición release usa HTTPS. El token no se guarda en preferencias en texto plano ni se registra en logs.

## 2. Contrato de datos y migración de destino

### 2.1 Catálogo completo, pero verificable

`RecordTypes.kt` contendrá una entrada explícita por cada `Record` del SDK fijado. Cada entrada declara: nombre estable de tipo, clase, permiso de lectura, familia de mapeo, disponibilidad de feature y nivel de sensibilidad. Las familias son: intervalo/cantidad, instantáneo, serie de muestras, sesión, composición corporal, rutas y recursos médicos si el SDK/feature los permite.

Un tipo no autorizado, no disponible o sin datos no es un error global: se refleja como estado por tipo y se omite hasta que cambie. Las rutas y recursos médicos deben tener mapeador y permiso propios, nunca caer por accidente en un JSON genérico incompleto.

El lote inicial de permisos pide el **núcleo que Samsung Health realmente escribe** (pasos, frecuencia cardiaca, sueño, ejercicio, calorías, peso y composición corporal); el resto del catálogo queda como botones opcionales por familia (con explicación previa para los sensibles) que abren el diálogo oficial de Health Connect. El estado por tipo es idéntico en ambos casos; la autorización final siempre pertenece a Health Connect.

### 2.2 Estado local: origen separado de entrega

Room tendrá estas entidades, en una sola transacción cuando aplique:

- `health_records`: `hc_id` PK, `record_type`, inicio/fin, `last_modified_epoch_ms`, `data_origin_package`, zona horaria si existe, `payload_schema_version`, `value_json`, `deleted_at`, `source_updated_at`.
- `health_sync_state`: una fila por `record_type` con `changes_token`, estado de permiso, `last_successful_read_at`, `next_due_at`, prioridad, `cooldown_until`, progreso de bootstrap/checkpoint y diagnóstico seguro. El cursor round-robin global también se persiste para no seleccionar siempre el primer tipo.
- `sync_targets`: `target_id`, URL HTTPS normalizada, nombre, activo y `created_at`. El secreto queda fuera de Room, cifrado mediante Android Keystore.
- `health_outbox`: `target_id`, `hc_id`, `operation` (`UPSERT`/`DELETE`), revisión, intentos y fecha. La clave única evita duplicar operaciones de la misma revisión para el mismo destino.

Al cambiar a un destino nuevo se crea un `target_id` nuevo y se siembra un `UPSERT` para cada registro no borrado. Por ello un futuro servidor recibe todo lo que Room conserva sin depender del flag global `synced`. Para migrar histórico más antiguo que el buffer del móvil se exporta/importa la SQLite del Mac antes de activar el nuevo destino.

### 2.3 Contrato HTTP estable

`POST /sync/health-connect` acepta lotes acotados de operaciones, no una lista ilimitada de registros. Cada operación contiene `hc_id`, `record_type`, revisión, operación, metadatos de procedencia y payload versionado. La respuesta incluye los `hc_id` y revisión aceptados; Android marca como entregadas exclusivamente esas operaciones.

El backend valida tamaño de cuerpo, máximo de operaciones, JSON, tipo permitido, timestamps y revisiones antes de abrir una transacción. Un lote válido se aplica atómicamente. `400`, `401` y `413` son errores permanentes visibles; errores de red y `5xx` son reintentables. Nunca se reintenta indefinidamente un payload inválido.

La autenticación es un **token único** `HC_SYNC_TOKEN` en env (estilo `GYM_CSRF_WINDOW_HOURS`), enviado en `X-Sync-Token` y comparado con `secrets.compare_digest`; si el env no está definido, el endpoint responde `503`. El `device_id` que declara la app en cada operación es metadato informativo (para consultas/export), nunca material de autenticación. El contrato conserva versión (`schema_version`) para poder evolucionar sin romper instalaciones viejas.

---

## 3. Scope, non-goals y definición de terminado

**In scope:**

- Esqueleto Android y catálogo completo de tipos del SDK fijado.
- Permisos, disponibilidad y estados por tipo.
- Backfill seguro, Changes API incremental por tipo, altas, actualizaciones y borrados.
- Room como fuente local y outbox por destino, con entrega por lotes acotados.
- HTTPS, secreto protegido por Keystore, configuración de destinos y resincronización a un destino nuevo.
- Migración `v010`, servicio de ingesta, endpoint versionado, CSV y pruebas de contrato, seguridad y resiliencia.
- WorkManager, medición local de registros/bytes/duración y documentación operativa para Mac y host futuro.

**Non-goals v1:** análisis o gráficas de salud dentro del dashboard; transformar sesiones HC en series de gimnasio; sincronización bidireccional; notificaciones en tiempo real; Hilt/Dagger; Firebase/Supabase; servicio foreground; exención de batería; una migración inmediata de todo el dashboard desde SQLite a PostgreSQL.

**Definition of done:**

- La app instala en Android 9+; Android 8 muestra estado no compatible sin fallar.
- Todos los tipos expuestos por el catálogo fijado se pueden verificar como autorizado, denegado, no disponible o sincronizado; cada tipo autorizado tiene mapeo y fixture de contrato.
- Dos syncs consecutivas no duplican; una actualización con igual `hc_id` y revisión mayor actualiza; un borrado llega al backend y desaparece de las consultas activas.
- Una interrupción después de persistir Room, durante paginación, después de recibir el servidor o antes de marcar la operación como entregada no pierde ni duplica el estado final.
- Mac apagado varios días: Room acumula; al volver el destino, se entrega por lotes y se vacía el outbox.
- Al configurar un destino HTTPS nuevo, el buffer local se reenvía al nuevo `target_id` sin cambio de código Android.
- HTTP, certificado no confiable, token ausente o token incorrecto no transmiten datos ni marcan operaciones como entregadas.
- Backend: `uv run pytest -q`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app.py src tests`. Android: `GRADLE_USER_HOME=$PWD/.gradle ./gradlew assembleDebug test` desde `android/`.

---

## 4. Guardrails

1. TDD: prueba roja, implementación mínima, prueba verde y commit por unidad coherente. Tests Android usan una interfaz pequeña `HealthConnectGateway` falsa; el dispositivo físico prueba la integración real.
2. Mantener la rama actual `feature/health-sync`; no incluir `data/*.db`, `backups/`, `.tmp/`, `android/.gradle/`, `android/app/build/` ni secretos en commits.
3. La máxima del sandbox es estricta: todos los comandos Gradle se ejecutan desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle`. Nunca se permite escribir en `~/.gradle`.
4. La migración `v010` se agrega tras `v009`; no se edita una migración aplicada. Todos los SQL usan parámetros.
5. El middleware CSRF actual protege todos los métodos mutantes. Su bypass debe ser exclusivamente la igualdad exacta de ruta `/sync/health-connect`; el endpoint resultante exige token propio y produce JSON, no HTML. Un prefijo o bypass genérico está prohibido.
6. Release rechaza URL no HTTPS y usa el trust store normal de Android. No se añaden clientes "trust all", desactivación de hostname verification ni permisos cleartext. La configuración de LAN debe resolver TLS mediante un certificado confiable/CA privada instalada en el teléfono o un proxy TLS local.
7. Requests y respuestas no registran `X-Sync-Token`, `value_json` ni datos médicos. La UI solo muestra contadores, estado y errores seguros.
8. WorkManager es oportunista: red no medida y batería no baja por defecto; el usuario puede habilitar red medida de forma explícita. No se interpreta la hora programada como garantía.

---

## Phase 0 — Baseline, seguridad y esqueleto Android

### Task 0.1: Baseline y entorno reproducible

**Files:** Modify `.gitignore`; create `android/` con Gradle wrapper, `settings.gradle.kts`, `build.gradle.kts`, `app/build.gradle.kts`, manifest, `MainActivity.kt` y test mínimo.

1. Ejecutar baseline backend con uv y registrar resultado sin modificar DB.
2. Crear proyecto Kotlin con `minSdk 26`, dejando claro en UI que Health Connect requiere Android 9+; fijar `compileSdk`/`targetSdk`, Java toolchain, AGP y versiones exactas, nunca "API instalada".
3. Añadir `android/.gradle/`, builds y `local.properties` a `.gitignore`.
4. Compilar desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle ./gradlew assembleDebug`.
5. Commit: `feat: add reproducible android health sync skeleton`.

### Task 0.2: Contrato versionado y seguridad de red

**Files:** Create `docs/architecture/health-sync-contract.md`, `android/app/src/main/res/xml/network_security_config.xml`; modify `AndroidManifest.xml`, `config.py`, `tests/test_security.py`.

1. Escribir fixtures JSON de `UPSERT`, `DELETE`, actualización y respuesta con acuses por operación.
2. Definir `schema_version`, tamaño/límite inicial de lote y campos obligatorios; no codificar IP de Mac.
3. Configurar release para HTTPS únicamente y debug para un host de desarrollo explícito si es imprescindible, nunca con permisos cleartext globales.
4. Añadir prueba que demuestre que el bypass CSRF no aplica a otras rutas y que `/sync/health-connect` exige su propia credencial.
5. Commit: `docs: define secure health sync contract`.

## Phase 1 — Catálogo completo, permisos y lectura de humo

### Task 1.1: Cliente y catálogo completo

**Files:** Create `android/app/src/main/java/com/jhomc/healthsync/HealthConnectManager.kt`, `RecordTypes.kt`, `HealthConnectGateway.kt`; modify `MainActivity.kt`.

1. Escribir test de catálogo: no permite tipo duplicado, todo tipo tiene permiso/familia y los tipos especiales están etiquetados.
2. Implementar cliente, `getSdkStatus`, feature status y catálogo explícito de cada `Record` soportado por la dependencia fijada.
3. Añadir estado por tipo: no disponible, no autorizado, listo, sincronizado o error seguro.
4. En dispositivo real, comprobar disponibilidad y que la pantalla muestra el catálogo, no solo cinco tipos.
5. Commit: `feat: add complete health connect record catalog`.

### Task 1.2: Permisos completos y humo de pasos

**Files:** Modify `MainActivity.kt`, `HealthConnectManager.kt`; test `RecordTypesTest.kt`.

1. Solicitar en lote el **núcleo** (tipos que Samsung Health escribe: pasos, FC, sueño, ejercicio, calorías, peso, composición); el resto del catálogo aparece como botones opcionales por familia que piden permisos por separado (con explicación previa para los sensibles); refrescar el estado al volver a foreground.
2. Implementar el botón de pasos de 24 h mediante `aggregate(StepsRecord.COUNT_TOTAL)`, no sumando `readRecords`, para evitar doble conteo de orígenes solapados.
3. Comprobar en teléfono real el resultado agregado y registrar los tipos que Samsung Health realmente llena.
4. Commit: `feat: request core health permissions with optional catalog`.

## Phase 2 — Room: fuente de origen, cambios y outbox

### Task 2.1: Esquema local y operaciones de entrega

**Files:** Create `android/.../data/HealthDatabase.kt`, DAOs y entidades; tests Room instrumentados.

1. Escribir pruebas de upsert por `hc_id` + revisión, borrado lógico, deduplicación de outbox y semilla para un `target_id` nuevo.
2. Implementar las cuatro tablas locales descritas en §2.2; `INSERT OR REPLACE` no se usa si puede borrar relaciones o perder revisiones.
3. En una transacción, actualizar registro y crear/reemplazar la operación de outbox de igual revisión para cada destino activo.
4. Probar que cambiar de destino genera replay de registros activos sin afectar el destino anterior.
5. Commit: `feat: add health source store and target-aware outbox`.

### Task 2.2: Mapeadores de todas las familias

**Files:** Create `RecordMappers.kt`, fixtures por familia y tests unitarios.

1. Escribir fixtures deterministas para intervalo, instantáneo, serie, sesión, composición, ruta y recurso médico disponible.
2. Implementar JSON determinista con `hc_id`, revisión, origen, tiempo y payload versionado. Nunca serializar una clase HC por reflexión ni descartar un campo complejo silenciosamente.
3. Rechazar localmente un tipo del catálogo sin mapeador y mostrar diagnóstico, sin bloquear los demás tipos.
4. Commit: `feat: map complete health record catalog`.

### Task 2.3: Changes API por tipo y recuperación segura

**Files:** Create `HealthRepository.kt`, `ChangesTokenStore.kt`; tests con `HealthConnectGateway` falso.

1. Escribir pruebas para token nulo, paginación, update, delete, permiso revocado, expiración y crash entre página/token.
2. Para un tipo sin token: crear token de cambios, hacer backfill de 30 días por páginas, persistir y drenar cambios desde aquel token; esto elimina la ventana entre backfill y token.
3. Para un token existente: procesar `UpsertionChange`/`DeletionChange`, persistir la página y su siguiente token de manera transaccional. Tratar la expiración por **ambas vías** del SDK fijado — la señal `changesTokenExpired` de la respuesta y la excepción `ChangesTokenExpiredException` — verificando cuáles expone la versión concreta de `connect-client`; no descartar ninguna por anticipado.
4. En expiración, releer desde la última lectura segura o los últimos 30 días, deduplicar por id/revisión y reservar token nuevo.
5. Persistir el checkpoint de cada página del bootstrap y el `next_due_at`/`cooldown_until` después de cada resultado; una interrupción no puede reiniciar el historial completo.
5. Commit: `feat: sync all health types incrementally`.

## Phase 3 — Backend idempotente, actualizado y con bajas

### Task 3.1: Migración `v010_health_connect`

**Files:** Create `src/migrations/v010_health_connect.py`; modify `src/migrations/runner.py`, `tests/test_database.py`.

1. Escribir pruebas que esperan versión 10, PK `hc_id`, índice `(record_type, start_epoch_ms)`, actualización y baja lógica.
2. Crear `health_records` con `hc_id TEXT PRIMARY KEY`, `record_type`, tiempos, `last_modified_epoch_ms`, `data_origin_package`, `payload_schema_version`, `value_json`, `device_id`, `received_at`, `updated_at` y `deleted_at` nullable.
3. Añadir la tabla a `_DOMAIN_TABLES` para backup antes de migrar.
4. Commit: `feat: add versioned health record mirror schema`.

### Task 3.2: Servicio de ingesta y contrato de acuse

**Files:** Modify `src/models.py`, `src/database.py`; create `src/health_sync_service.py`, `tests/test_health_sync_service.py`.

1. Escribir pruebas de batch válido, replay idéntico, revisión mayor, revisión vieja, delete, body excesivo, tipo inválido y rollback total ante fila inválida.
2. Implementar validación estricta y `INSERT ... ON CONFLICT(hc_id) DO UPDATE` condicionado por revisión. La baja actualiza `deleted_at`; consultas y export por defecto excluyen filas borradas.
3. Devolver el acuse exacto por `hc_id` y revisión, no solo contadores globales.
4. Commit: `feat: mirror health changes with upserts and deletes`.

### Task 3.3: Endpoint autenticado y aislado del CSRF HTML

**Files:** Modify `app.py`, `config.py`, `src/security.py`, `tests/test_app.py`, `tests/test_security.py`.

1. Escribir pruebas de 503 sin credencial configurada, 401 ante token inválido, 400/413 ante payload inválido, JSON correcto y bypass exacto de CSRF.
2. Implementar `POST /sync/health-connect` con límite de request, autenticación constante y transacción del servicio.
3. Verificar que rutas htmx siguen necesitando CSRF y que ningún token ni payload aparece en logs/respuestas de error.
4. Commit: `feat: add secure health sync endpoint`.

## Phase 4 — Entrega HTTP, destinos y scheduling

### Task 4.1: Cliente HTTPS y configuración protegida

**Files:** Create `HealthSyncClient.kt`, `SecureTargetStore.kt`; modify `MainActivity.kt`; tests unitarios.

1. Escribir pruebas para URL HTTP rechazada, URL HTTPS aceptada, certificado fallido, token ausente y rotación de destino.
2. Guardar URL, `target_id` y preferencias no secretas en DataStore; cifrar el token mediante clave Android Keystore. El campo UI de token se enmascara.
3. Usar OkHttp con validación TLS normal, timeout acotado, lotes por registros y bytes y respuesta de acuse individual.
4. Marcar entregado exclusivamente lo confirmado por el servidor; errores permanentes se muestran y no se reintentan en bucle.
5. Commit: `feat: upload health outbox to secure configurable target`.

### Task 4.2: Cambio de destino y plan de salida del Mac

**Files:** Modify `HealthRepository.kt`, `MainActivity.kt`; create `docs/operations/health-sync-migration.md`; tests unitarios.

1. Escribir prueba: cambiar destino genera el seed del buffer actual para el nuevo `target_id` y no reescribe la fuente Health Connect.
2. Implementar confirmación visible con número de registros que se reenviarán, estado de progreso y opción de cancelar antes de comenzar.
3. Documentar migración Mac → host persistente: backup consistente de SQLite, restauración en volumen persistente, configuración TLS/credencial nueva, cambio de destino, validación de conteos e histórico de rollback.
4. Aclarar que mantener FastAPI + SQLite en un único host persistente no requiere cambio Android; migrar el dashboard entero a PostgreSQL es un proyecto separado.
5. Commit: `feat: support health sync target migration`.

### Task 4.3: Worker manual y periódico eficiente

**Files:** Create `SyncWorker.kt`, `SyncScheduler.kt`; modify `MainActivity.kt`; tests con WorkManager.

1. Escribir pruebas para tipos parciales, sin permisos, red caída, 5xx, 401, outbox grande y progreso manual.
2. Orquestar: sincronizar únicamente los tipos autorizados cuyo `next_due_at` haya vencido, entregar outbox por lotes y reportar contadores por tipo/bytes/duración sin datos sensibles.
3. Programar trabajo único periódico 1 h/flex 15 min con red no medida y batería no baja; el trabajo no implica que se consulte todo el catálogo. El manual one-time puede ser expedited con `OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST`.
4. Reintentar únicamente fallos temporales. Permiso faltante o URL/token inválidos quedan en estado accionable; no producen tráfico ni backoff infinito.
5. Validar en dispositivo real ejecución eventual con app cerrada; no usar la hora exacta como criterio.
6. Aplicar un presupuesto por ejecución: como máximo 1–2 tipos o el límite de páginas/tiempo configurado. Persistir el progreso después de cada página y continuar en la siguiente ejecución.
7. Usar rotación round-robin entre tipos autorizados que estén pendientes; no seleccionar siempre el primer tipo del catálogo.
8. Commit: `feat: schedule efficient resilient health sync`.

## Phase 5 — Verificación completa, export y operación

### Task 5.1: Pruebas de resiliencia y contrato cruzado

**Files:** Create fixtures compartidos Android/Python; modify tests Android y `tests/test_health_sync_service.py`.

1. Ejecutar las mismas fixtures serializadas por Android contra el servicio Python.
2. Probar cortes: crash después de Room, timeout después de commit remoto, expiración de token, actualización y borrado antes/después de upload, Mac apagado y cambio de destino.
3. Medir registros, bytes, duración y tamaño de Room con FC y sesiones reales; ajustar únicamente límite de lote/frecuencia si hay evidencia de consumo relevante.
4. Commit: `test: verify end to end health sync recovery`.

### Task 5.2: Export y documentación

**Files:** Modify `app.py`, `tests/test_app.py`, `AGENTS.md`, `docs/architecture/security-model.md`, `docs/operations/local-development.md`.

1. Implementar `GET /exportar/health-connect.csv` para registros activos, ordenado por tipo/tiempo, con opción explícita documentada para auditoría de bajas.
2. Documentar catálogo, contrato, modelo de seguridad, HTTPS LAN, operación Gradle dentro del sandbox, respaldo y migración a host permanente.
3. Ejecutar gates backend y Android, smoke real watch → Samsung Health → Health Connect → Room → HTTPS → SQLite y cambio a segundo destino de prueba.
4. Commit: `docs: complete health sync operations and migration guide`.

### Task 5.3: Integración

Solo con aprobación explícita del usuario: actualizar desde `main` si es necesario, ejecutar gates, integrar y reportar los resultados. No eliminar ramas, backups ni datos sin autorización específica.

---

**Riesgos y mitigaciones:** Health Connect requiere dispositivo físico para validar integración real; Samsung Health puede retrasar la publicación de registros, absorbida por tokens, revisiones y replay. Los tokens expiran a los 30 días: el backfill deduplicado recupera el estado legible, pero el historial anterior al permiso requiere autorización de historial. Desde la actualización de Health Connect de junio de 2026, los pasos capturados en el propio dispositivo se atribuyen a un nombre de paquete sintético específico del dispositivo en lugar de `"android"`: `data_origin_package` se conserva como metadato, pero **no se asume ningún valor fijo** para filtrar ni deduplicar. Un host LAN HTTPS necesita un certificado confiable y el dashboard no debe exponerse públicamente sin una capa de autenticación adicional. Datos de series o rutas pueden aumentar tamaño de Room: los lotes, la red no medida, los límites y las métricas locales controlan el coste sin eliminar datos no entregados. **Rate limiting (verificado en doc oficial):** Health Connect impone un límite periódico y otro diario de llamadas por app; el límite en segundo plano es MÁS estricto que en primer plano; la doc recomienda la Changes API (changelog) para minimizar llamadas. El cliente debe detectar `RemoteException: rate limited` y **nunca reintentar en bucle** (esperar la reposición). **Manifest:** el proveedor (2025+) solo registra apps que declaran el handler `ACTION_SHOW_PERMISSIONS_RATIONALE` (ver contrato §8) — sin él la app no aparece en Health Connect ni el diálogo de permisos muestra opciones.

---

## Notas de ejecución (2026-08-09/10) — dispositivo real: Redmi Note 8, Android 13, MIUI 14, Health Connect v268669

### 1. Crash de arranque — `network_security_config` inválido

**Síntoma:** la app no abría; logcat: `XmlConfigSource$ParserException: Nested domain-config not allowed in debug-overrides`.

**Causa:** `domain-config` anidado dentro de `debug-overrides` (no permitido por el parser de Android).

**Fix (`cc429ae`):** split por build variant: `src/main/res/xml/network_security_config.xml` (HTTPS-only, también release) + `src/debug/res/xml/network_security_config.xml` (misma base + cleartext solo para hosts de desarrollo explícitos: `127.0.0.1`, `10.0.2.2`, `192.168.1.6`).

### 2. HealthSync no aparecía en Health Connect — manifest incompleto (resuelto)

**Síntomas:** botón de permisos sin efecto; HealthSync ausente de "Permisos de las apps" de Health Connect; el diálogo se abría sin opciones; "Abrir Health Connect" caía a Play Store.

**Descartes con evidencia:**
- No era la versión del SDK: el AAR **1.2.0-alpha04** (último en Maven) es idéntico al 1.1.0 en el contrato de permisos (`androidx.health.ACTION_REQUEST_PERMISSIONS` + paquete `com.google.android.apps.healthdata`), en `DEFAULT_PROVIDER_MIN_VERSION_CODE` (68623) y en las **19 clases del binder** (`androidx.health.platform.client.impl.sdkservice.*`) → migrar el SDK no cambiaría nada.
- No era Health Connect: **Nike Run Club** (instalada como control) se registró sola y aparece en la lista de apps de HC.

**Causa real:** el manifest no declaraba el handler de política de privacidad. El sample oficial de Google (`android/health-samples`, `HealthConnectSample/AndroidManifest.xml`) lo exige: intent-filter `androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE` en la Activity + `<intent>` equivalente en `<queries>` + `VIEW_PERMISSION_USAGE`/`HEALTH_PERMISSIONS` (Android 14+). El proveedor 2026 solo registra apps "completas".

**Fix (`6dfac1f`):** manifest alineado con el sample oficial + pantalla de privacidad en `MainActivity` (`showPrivacyPolicy`) + guard de regresión `ManifestContractTest` (`57754b0`) + contrato §8 (`8ada026`).

**Lección estructural:** el flujo de permisos de HC es por **intent** (UI del proveedor) y funciona aunque el binder falle; el registro de la app depende del manifest completo, no del SDK.

### 3. Rate limiting de Health Connect — PROBLEMA ACTUAL (abierto)

**Síntoma:** "Sincronizar AHORA (directo)" → `RemoteException: Request rejected. Rate limited request quota has been exceeded. Please wait until quota has replenished before making further requests.`

**Verificación oficial:** la doc de Google *"Plan to avoid rate limiting"* (`developer.android.com/health-and-fitness/health-connect/rate-limiting`, actualizada 2026-01-19) confirma: **dos límites** por app (periódico + diario) sobre el número de llamadas a la API; **el rate limiting en segundo plano es más estricto que en primer plano**; recomendación explícita: usar la **Changes API (changelog handling)** en lugar de lecturas crudas para minimizar llamadas. El SDK cliente no contiene el mensaje (verificado en su bytecode) — lo emite el proveedor. La afirmación "las apps nuevas tienen cuota baja" **NO está en la doc oficial** y queda descartada como explicación.

**Hechos del dispositivo:**
- La agregación de pasos 24h **funciona** → el binder y los permisos están vivos; el fallo es exclusivo de la cuota, no del protocolo.
- La cuota seguía agotada **tras 10 horas** → un límite periódico se repone en ~1 h; algo la consume continuamente.

**Hipótesis principal (por verificar):** el worker de WorkManager reintenta en background ante rate limit (`Result.retry()` + backoff exponencial 30 min) y, como el límite de background es más estricto, **mantiene la cuota agotada de forma permanente**. En MIUI el worker aparecía ENQUEUED, pero pudo ejecutarse intermitentemente.

**Mitigaciones YA implementadas** (`f7d5f1c`, `f50ff9d`, `75d9b39`):
- Detección de rate limit → `RateLimitedException` (no reintenta en el mismo bucle).
- Fallback estructural: Changes API como primario; ante `RemoteException` no-rate-limit → **modo rango** (backfill 30 días paginado, dedup por revisión); el fallback es red de seguridad, no el camino principal (la doc recomienda Changes).
- Throttle temporal: `MAX_TYPES_PER_RUN = 1` mientras se verifica la cuota; el diseño definitivo usa presupuesto y rotación persistidos por tipo (Notas §3.1).
- `SyncExecutor` compartido (worker + botón directo) con reporte estructurado; UI con mensaje claro de cuota y cadena de causas completa del error.

**Plan inmediato (aplicado en `580941f`, 2026-08-10; pendiente solo la verificación en dispositivo):**
1. ✅ Cancelar los workers de WorkManager en `MainActivity.onCreate` — `SyncScheduler.cancelAll()` (ambos: `health_connect_sync` periódico y `health_connect_sync_now`) → la sync queda 100% manual (botón directo) mientras dure la investigación.
2. ✅ Worker ante `rate_limited` → `Result.success()` (nunca `retry`; datos de diagnóstico `reason=rate_limited`), + catch defensivo de `RateLimitedException` que escape del executor (también → success).
3. ✅ `MAX_TYPES_PER_RUN = 1` (HealthRepository.kt) — STEPS es el primero del catálogo → la primera corrida sincroniza solo pasos.
4. ✅ Cache de `grantedPermissions` en `RealHealthConnectGateway` (TTL 15 s) + `invalidatePermissionCache()` llamado tras el flujo de permisos en MainActivity (se acabó la llamada al binder en cada `onResume`).
5. ⏳ Esperar la reposición (~1–2 h) y verificar con **una sola** pulsación del botón directo → comprobar `data/gym.db`.
6. ⏳ Si tras 24 h sin workers la cuota sigue agotada → evaluar el límite diario (declaración de datos en Play Console / uso estabilizado) — no antes.

**Verificación pendiente en el teléfono (Redmi Note 8):** instalar el nuevo APK, abrir la app una vez (cancela workers al arrancar), esperar 1–2 h a que la cuota se reponga y pulsar **una sola vez** "Sincronizar AHORA (directo)". Compilado y 43 tests unitarios Android en verde (`580941f`).

### 3.1 Diseño objetivo para reducir llamadas sin perder datos

La sincronización debe conservar todos los tipos autorizados, pero no consultar todo el catálogo en cada ejecución. El objetivo es que la primera carga sea progresiva y que el funcionamiento normal sea incremental.

**Regla inmediata:** `HealthRepository` debe filtrar los tipos autorizados y seleccionar el siguiente tipo pendiente **antes** de invocar `syncType()`. Aplicar `.take()` después de `mapNotNull` no limita las llamadas: el `map` ya se evaluó completo. El cursor de rotación debe persistirse; de lo contrario, limitar a uno dejaría `STEPS` como único tipo sincronizado para siempre.

**Primera carga (bootstrap):** para cada tipo autorizado sin token, reservar primero el token, leer el historial inicial de 30 días por páginas y persistir un checkpoint tras cada página. Después se drenan los cambios desde el token reservado. Si la app, el proceso o el destino fallan, la siguiente ejecución continúa desde Room; nunca repite automáticamente los 30 días completos por un error de red o cuota.

**Funcionamiento normal:** cada tipo conserva su token y `next_due_at`. Cuando vence, se usa exclusivamente la Changes API y se procesan sus páginas hasta agotarlas o hasta alcanzar el presupuesto de la ejecución. El token intermedio se guarda de forma transaccional. La documentación oficial recomienda tokens separados por tipo, especialmente cuando los tipos se consumen de forma independiente o un permiso puede revocarse.

**Prioridad adaptativa, sin excluir datos:**

- Tipos de alta actividad (pasos, frecuencia cardiaca, sueño, sesiones, calorías): objetivo cada 4–6 horas.
- Tipos de actividad ocasional (distancia, hidratación, nutrición y similares): objetivo diario.
- Tipos de baja frecuencia (peso, composición corporal, constantes y datos médicos): objetivo semanal.

Estos intervalos son objetivos, no garantías de WorkManager. Un tipo inicialmente desconocido empieza en prioridad media; si produce cambios recientes, sube de prioridad, y si permanece vacío varias rondas, baja a prioridad fría. Ningún tipo autorizado se elimina. Todos los intervalos deben ser inferiores a la caducidad de tokens de 30 días.

**Presupuesto y transporte:** una ejecución procesa como máximo 1–2 tipos, o el límite menor entre páginas, registros y tiempo configurado. La extracción Health Connect → Room no depende de la red. Room acumula el outbox y el cliente HTTP solo transmite cuando hay operaciones pendientes, en lotes limitados por 500 operaciones y por bytes. Así un Mac apagado no provoca relecturas ni bloquea el avance del origen.

**Rate limit y errores:** ante una respuesta limitada se guarda `retry_after`/enfriamiento y se termina con éxito diagnóstico; no se hace `retry` inmediato ni se activa un backfill de 30 días. Los fallos temporales de red se reintentan con backoff acotado, y los fallos permanentes quedan visibles sin generar tráfico repetido. La cuota de Health Connect varía por operación y por primer/segundo plano, por lo que el contador local debe medir llamadas, páginas, registros, bytes y duración.

**Criterios de aceptación adicionales:**

1. Una ejecución que empieza con 38 tipos autorizados no invoca más de los tipos seleccionados por el presupuesto.
2. Cinco ejecuciones consecutivas recorren tipos distintos mediante el cursor persistido.
3. Un bootstrap interrumpido continúa en la página pendiente y no vuelve a leer páginas confirmadas.
4. Una sincronización incremental sin cambios no ejecuta backfill ni genera HTTP.
5. Un rate limit no provoca más de una llamada fallida por ventana de enfriamiento.
6. El conjunto completo de tipos autorizados termina siendo revisado dentro de sus intervalos, sin exigir que todos se consulten en la misma ejecución.

**Estado (2026-08-11):** implementado en `feature/health-sync` (Tasks 1–8 de `docs/plans/2026-08-11-health-sync-quota-scheduling.md`); los 6 criterios tienen tests dedicados (58 unit tests en verde).

### 4. Entorno MIUI (Redmi Note 8)

- El icono de Health Connect **no aparece en el cajón de apps** (MIUI lo oculta; el launcher existe); se accede a HC desde Samsung Health.
- WorkManager: el trabajo periódico y el one-time quedan **ENQUEUED** (MIUI restringe la ejecución de fondo de apps de origen desconocido) → **el botón directo en primer plano es la vía primaria de sincronización**; el worker queda como best-effort documentado.

### 5. Hallazgos técnicos del SDK 1.1.0 (verificados contra el AAR real)

- `IntervalRecord`/`InstantaneousRecord`/`SeriesRecord` son **internal** en 1.1.0 → los mapeos extraen start/end/zone por `when` explícito por tipo.
- Las unidades son **value classes** con properties `inXxx` (`inKilograms`, `inKilocalories`, `inCelsius`…), no `.xxx`.
- El constructor de `Metadata` es **internal** → los fixtures de test usan reflexión (solo tests; documentado en `Fixtures.kt`).
- `DEFAULT_PROVIDER_PACKAGE_NAME`/`DEFAULT_PROVIDER_MIN_VERSION_CODE` son internal → constantes propias (`HealthConnectProvider`) con valores verificados del bytecode (68623).
- `ReadRecordsResponse` no tiene `hasMore()` → paginación por `pageToken != null`.
- En 1.1.0 NO existen `BodyMassIndexRecord`, `SleepStageRecord` ni `ExerciseLap` como `Record`; `ExerciseRoute` no extiende `Record` (API aparte) → excluidos del catálogo con evidencia.

### 6. Backend — verificado

- Smoke local completo: 401 sin token / 200 con acuse individual / replay idempotente / export CSV correcto (datos de prueba limpiados de `data/gym.db`).
- Gates: 379 tests pytest + ruff format/check + mypy, verdes.

### 7. Pendientes

- Smoke end-to-end real (Watch → Samsung Health → HC → Room → HTTP → SQLite del Mac) — **pendiente**: con el nuevo APK (Tasks 1–8), "Sincronizar AHORA (directo)" avanza por tipos sin ráfagas y sin quemar la cuota; verificar en dispositivo.
- Verificación de `data_origin_package` real con pasos on-device.
- Integración a `main` (Task 5.3) — solo con aprobación explícita del usuario.
