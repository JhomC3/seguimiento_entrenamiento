# Informe Forense — Cumplimiento de Backend Standards (2026-08-14)

> **Propósito:** auditoría estática del backend del proyecto Gym Tracker contra la guía
> `docs/architecture/backend-standards.md` (v1, 2026-08-14). Cada hallazgo incluye
> severidad, ubicación `archivo:línea`, evidencia y remediación. El análisis cubre
> `app.py`, `src/` completo, migraciones, scripts CLI, CI y configuración.
> **Base auditada:** commit `085659b` (working tree limpio).
>
> **Resumen del estado:** el núcleo del backend es sólido — capas limpias con dominio
> puro, transacciones ACID en todas las escrituras, constraints en la base de datos,
> migraciones versionadas con backup, importaciones idempotentes, validación de borde
> tipada y una suite de 433 tests con cobertura ≥90 %. Las brechas se concentran en
> **observabilidad** (request_id, health, config de logging), **inventario de API**
> (documentación expuesta por defecto y código muerto) y **operativa SQLite** (WAL,
> índices), más un **hallazgo de seguridad de severidad alta heredado del informe
> frontend** (secret CSRF de desarrollo + arranque oficial en `0.0.0.0`).

---

## 1. Metodología y alcance

**Superficie auditada** (lectura íntegra de ~4.900 líneas de backend):

| Capa | Archivos |
|---|---|
| HTTP | `app.py` (1.238 ln) — todos los handlers y middleware |
| Servicios de dominio | `training_service.py`, `nutrition_service.py`, `template_service.py`, `exercise_service.py`, `cardio_service.py`, `metrics_engine.py`, `analysis_data.py`, `mutation_service.py`, `health_sync_service.py`, `dashboard_service.py` |
| Persistencia | `database.py` (611 ln), `db_connection.py`, `migrations/runner.py`, `migrations/v001_v012` |
| Scripts | `import_google_sheets.py`, `import_nutrition.py`, `start_server.sh`, `build_css.sh`, `check_module_coverage.py` |
| Config/CI | `config.py`, `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`, `docs/operations/release-checklist.md` |

**Verificaciones instrumentadas:** `rg` para callers de funciones sospechosas de código
muerto, `rg` para `basicConfig`/WAL/`docs_url`, lectura directa de scripts de importación
para confirmar idempotencia y backups.

**Corrección sobre el borrador preliminar:** la importación de entrenamiento
(`import_google_sheets.py:39`) **sí es idempotente** — borra `origen='google'` antes de
insertar en una sola transacción. Ese hallazgo preliminar queda descartado; el gap real
es la **ausencia de backup previo** en esa importación (la de nutrición sí lo hace).

---

## 2. Conformidades (lo que ya se cumple bien)

| Pilar | Conformidad | Evidencia |
|---|---|---|
| Arquitectura | Handlers delgados; servicios de dominio tipados; SQL solo en `database.py`; capa de persistencia única | `app.py:467-495` (save), `training_service.py:118-148`, `database.py` |
| Datos | Todas las escrituras multi-fila en `transaction(...)` (delete+insert atómico) | `database.py:42,75,109,233,451,500...` |
| Datos | Constraints en DB: `UNIQUE` en `ejercicios.ejercicio`, `plantillas.nombre`, `alimentos.nombre`; FK `plantilla_sets.plantilla_id ON DELETE CASCADE`; PKs naturales (`hc_id`, `parametros_diarios.fecha`) | `v001_initial_schema.py:10-45`; `v010_health_connect.py` |
| Datos | Migraciones versionadas, transaccionales, con backup automático previo y registro en `schema_migrations`; runner con guarda (backup solo si existen tablas de dominio) | `migrations/runner.py:59-112` |
| Datos | Backups pre-mutación con retención 30 (`prune_backups`); backup fallido bloquea la escritura | `mutation_service.py:74-83`; `backup_utils.py` |
| Validación | Validación de dominio completa: NaN/Inf, rangos (RIR ≥ −5), catálogo, arrays paralelos, fechas ISO; valores calculados **siempre** en servidor | `training_service.py:62-78,118-148`; `nutrition_service.py:43-72,143-155` |
| Idempotencia | Sync por `hc_id` + revisión (upsert condicionado, baja lógica, acuse individual); sesión y diario son replace-by-fecha; importaciones reemplazan solo `origen='google'` | `health_sync_service.py:154-213`; `import_google_sheets.py:38-51`; `import_nutrition.py:108-125` |
| Errores | Dominio → 400 con mensaje seguro en español; inesperado → 500 genérico con `logger.exception` (stack solo server-side) | `dashboard_service.py:296-305`; `mutation_service.py:81-83` |
| Seguridad | Token de sync con `hmac.compare_digest`; límites 1 MiB / 500 ops; validación estructural atómica del lote; SSRF ausente (URLs constantes de `config.py`); `timeout=30` en el fetcher | `app.py:1182-1214`; `health_sync_service.py:22-23,74-133`; `fetcher.py:20` |
| Testing | 433 tests; cobertura ≥90 % (gate global + por módulo charts/metrics); e2e Playwright aislado; CI con 3 jobs | `pyproject.toml:63-66`; `.github/workflows/ci.yml` |
| Config | Secretos fuera de git (`data/hc_sync_token` gitignored); config por env (`LIFESTYLE_DB_PATH`, `HC_SYNC_TOKEN`, `GYM_CSRF_*`) | `.gitignore`; `config.py:5-24`; `security.py:44-51` |

---

## 3. Hallazgos por pilar del estándar

### 3.1 Seguridad (backend-standards §6) — 1 alto

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **Secret CSRF de desarrollo por defecto + arranque oficial en `0.0.0.0`:** `start_server.sh` expone el dashboard en toda la LAN (para la app Android) y no genera ni valida `GYM_CSRF_SECRET`; sin la variable, el CSRF se firma con `_DEV_SECRET` público (`dev-only-secret-do-not-use-in-production`) → cualquier host de la red puede forjar tokens y mutar datos. Mismo hallazgo del informe frontend (P0); aquí se reafirma como invariante del estándar §2/§6 | `scripts/start_server.sh:21-22`; `src/security.py:53-54`; `app.py:90-94` |
| Medio | **Sin rate limiting** (OWASP API4, unrestricted resource consumption): `/sync/health-connect` solo limita tamaño (1 MiB) y lote (500 ops), sin throttle por IP/token. Mitigación actual: token estático secreto + límites de tamaño; no documentada como riesgo aceptado | `app.py:1182-1214`; `health_sync_service.py:22-23` |
| Medio | **Form parsing sin límites:** arrays `Form(...)` (`ejercicio[]`, `alimento[]`, `id[]`) sin `max_length`/conteo; sin límite global de tamaño de request en uvicorn (el sync sí tiene 1 MiB) → un formulario hostil puede consumir CPU/memoria de parseo | `app.py:471-476,542-549,687,811` |

### 3.2 Observabilidad (backend-standards §7) — 1 alto, 1 medio

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **Sin correlación de peticiones ni telemetría de requests:** no existe middleware de logging de peticiones propio (solo el access log de uvicorn), ni `request_id`, ni contexto por petición en los logs. Un 500 no se puede correlacionar con la petición que lo causó | `app.py:104-110` (único middleware de logging: cache de estáticos) |
| **Alto** | **Sin configuración de logging:** `logging.getLogger(...)` en los módulos, pero **cero** `basicConfig`/`dictConfig` en toda la app → el handler por defecto de Python (`lastResort`, WARNING+) hace invisibles los `logger.info` y emite solo warning/error a stderr; no hay formato estructurado ni destino definido | `rg 'basicConfig\|dictConfig'` → 0 resultados; `app.py`, `src/*` |
| Medio | **Sin health endpoint:** no existe `/healthz` ni equivalente (liveness/readiness de 12-Factor §9); un despliegue no puede verificar que la app responde y la DB abre | `app.py` (todas las rutas listadas en §1 de current-ui-contract) |
| Medio | **Sin métricas:** nada más allá del access log; no hay contadores de errores por ruta ni percentiles (p95/p99) — aceptable al tamaño actual, pero el estándar §7 exige al menos conocer la tasa de errores | `app.py` |

### 3.3 API e inventario de rutas (backend-standards §3) — 1 alto, 1 medio

| Sev | Hallazgo | Evidencia |
|---|---|---|
| **Alto** | **Documentación expuesta por defecto sin decisión:** FastAPI habilita `/docs`, `/redoc` y `/openapi.json` automáticamente (sin `docs_url=None`/`openapi_url=None` ni revisión del contrato). OWASP API9 (improper inventory): el contrato expone el inventario completo de endpoints, incluidos los internos de htmx | `app.py:97` (`FastAPI(title="Gym Tracker")` sin parámetros de docs) |
| Medio | **Código muerto de backend:** `get_sessions_page` (`training_service.py:209-213`) y `get_training_sessions` (`database.py:114-140`) sin callers; `load_ejercicios` (`database.py:30-36`) y `load_training_data` (`database.py:39-43`) sin callers (el import usa sqlite3 directo); `delete_session(semana, dia, fecha)` (`database.py:168-174`) sin callers (el servicio usa `delete_session_by_fecha`). Más las rutas legacy `/select`, `/grupo/reset`, `/ejercicio` ya reportadas en el informe frontend | `rg` de callers (verificado) |

### 3.4 Datos y persistencia (backend-standards §4) — 3 medios, 4 bajos

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | **SQLite sin WAL:** `connect_db` solo activa `foreign_keys` y `busy_timeout` (5 s); `journal_mode` queda en el default (rollback) → una escritura bloquea lecturas de otras pestañas/procesos. WAL da lecturas concurrentes sin bloquear y `synchronous=NORMAL` opcional | `db_connection.py:10-15`; `rg 'journal_mode'` → 0 |
| Medio | **Índices incompletos:** `training_sets(fecha)` sin índice — `save_session` hace `DELETE`+`INSERT` por fecha, `get_sets_by_fecha` filtra por fecha, `get_training_sessions` agrupa por fecha. Los JOINs con `LOWER(col)` (`calculate_pfr_timeline`, `get_ejercicios_por_grupo`, `find_*`) no usan los índices existentes (función sobre columna) | `v001_initial_schema.py:29-30` (solo semana/ejercicio); `training_service.py:163-170`; `metrics_engine.py:80-86` |
| Medio | **Importación de entrenamiento sin backup previo:** `import_google_sheets.py` borra todas las filas `origen='google'` de `training_sets` y las reemplaza sin `backup_db()` (la de nutrición sí: `import_nutrition.py:105`). Una hoja mal parseada destruye el histórico de entrenamiento sin copia de seguridad | `import_google_sheets.py:35-51`; `import_nutrition.py:104-105` |
| Bajo | `INSERT OR REPLACE` en `save_parametros_diarios` (borra+reinserta, cambia rowid; frágil si aparecen FKs) y en `import_nutrition.py:127` — preferir `INSERT ... ON CONFLICT(fecha) DO UPDATE` | `database.py:496-510`; `import_nutrition.py:126-143` |
| Bajo | `restore_entrenos` manipula `sqlite_sequence` a mano tras restaurar (frágil ante futuros cambios de esquema) | `database.py:292-309` |
| Bajo | Backup de migración con `shutil.copy2` del archivo (no snapshot del motor): no atómico ante escritores concurrentes; SQLite ofrece `conn.backup()` | `migrations/runner.py:59-70` |
| Bajo | N+1 leve: `get_plantillas` (1 + N consultas) y `get_plantillas_alimentacion` (1 + N) | `database.py:187-203,523-541` |
| Bajo | `pandas.read_sql_query` carga tablas completas a memoria en gráficas/métricas (`calculate_pfr_timeline`, `get_exercises_baselines`) — límite operativo no documentado | `metrics_engine.py:44-51,78-86`; `charts.py:27-36` |

### 3.5 Configuración y 12-Factor (backend-standards §2) — 1 medio

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | **Estado en proceso:** la pila de undo (`deque(maxlen=10)`) es memoria de proceso único — se pierde al reiniciar uvicorn y no se comparte entre workers; la UI no informa del límite (solo Ctrl/Cmd+Z). Límite conocido y aceptable, pero debe documentarse en la UI y en el estándar (ya lo hace §1/§8) | `mutation_service.py:33` |
| Bajo | Constantes de dominio hardcodeadas (`CICLO_START`, `SHEET_ID`, `GIDS`, `MUSCLE_CATEGORIES`) en `config.py` — 12-Factor III: config en entorno. Aceptable para app personal con ciclo anual; mover a env si se hacen multi-entorno | `config.py:26-55` |
| Bajo | `import_google_sheets.py` usa `sqlite3.connect(DB_PATH)` directo, saltándose la fábrica `connect_db` (sin `foreign_keys` ni `busy_timeout` en el script) | `import_google_sheets.py:36`; `import_nutrition.py:106` |

### 3.6 API y contratos de error (backend-standards §3) — conformidad con matices

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Info | Dos contratos de error coexisten y son coherentes: htmx (HTML + notice OOB con status 400) y JSON sync (`{"detail": ...}`). Documentados en `current-ui-contract.md` y `health-sync-contract.md`; no unificar sin cambiar ambos contratos | `app.py:324-334`; `health_sync_service.py` |
| Info | `GET` nunca muta (aplicar plantilla solo devuelve filas para el editor, no persiste) — semántica HTTP correcta | `app.py:819-830` |

### 3.7 Higiene y drift documental

| Sev | Hallazgo | Evidencia |
|---|---|---|
| Medio | `AGENTS.md` §5 documenta las rutas muertas `/select`, `/grupo/reset`, `/ejercicio` como vigentes y no menciona `/nivel`, `/grafica`, `/editor/popup`, `/cardio/annotation`; §4 declara migraciones `v001..v003` (existen hasta `v012`); drift en el conteo de record types (17 vs 41) | `AGENTS.md:38,103,118-120`; `health_sync_service.py:26-69` |
| Bajo | CSV exports sin BOM UTF-8 (Excel corrompe acentos) | `app.py:710-724,900-909` |

---

## 4. Ranking de remediación priorizado

| Prio | Hallazgo | Esfuerzo | Archivos |
|---|---|---|---|
| **P0** | Generar/persistir `GYM_CSRF_SECRET` en `start_server.sh` (mismo patrón que `hc_sync_token`); abortar si no existe al exponer `0.0.0.0` | S | `scripts/start_server.sh` |
| **P1** | Decidir y gestionar `/docs`-`/redoc`-`/openapi.json` (deshabilitarlos o documentar su exposición) + eliminar rutas muertas y código muerto backend | S-M | `app.py:97`, `app.py:912-1179`, `database.py`, `training_service.py` |
| **P1** | `request_id` por petición (middleware) + config de logging (formato, handler a stderr, nivel INFO en dev) | S | `app.py`, nuevo `src/logging_setup.py` o similar |
| **P1** | `GET /healthz` (liveness: app + DB abren) | S | `app.py` |
| **P1** | WAL en `connect_db` (`PRAGMA journal_mode=WAL`, `synchronous=NORMAL`) | S | `src/db_connection.py:10-15` |
| **P1** | `backup_db()` antes del reemplazo en `import_google_sheets.py` | S | `scripts/import_google_sheets.py:35` |
| **P2** | Índice en `training_sets(fecha)` (+ evaluación de índices de expresión para `LOWER`) | S | nueva migración `v013` |
| **P2** | Rate limiting en `/sync/health-connect` (token bucket simple en memoria o por IP) o documentar riesgo aceptado | M | `app.py:1182-1214` |
| **P2** | Límites en arrays de formularios (`max_length`/conteo de filas) | S | `app.py` handlers |
| **P2** | `ON CONFLICT` en `save_parametros_diarios` e import nutrición; revisar `sqlite_sequence`; `conn.backup()` en runner | S-M | `database.py:496-510`, `migrations/runner.py`, `import_nutrition.py:127` |
| **P2** | Actualizar `AGENTS.md` y `current-ui-contract.md` (rutas, migraciones, record types) | S | `AGENTS.md`, `current-ui-contract.md` |

---

## 5. Anexos

### A. Verificaciones instrumentadas

- `rg 'basicConfig|dictConfig|addHandler|FileHandler'` → **0 resultados** (sin config de logging).
- `rg 'journal_mode|WAL|synchronous'` en `src/`, `config.py` → **0 resultados**.
- `rg 'docs_url|redoc_url|openapi_url' app.py` → **0 resultados** (docs FastAPI por defecto).
- Callers verificados (código muerto): `get_sessions_page`, `get_training_sessions`,
  `load_ejercicios`, `load_training_data`, `delete_session(semana, dia, fecha)` → sin
  usos en `app.py`, `src/`, `scripts/`.
- Idempotencia confirmada de importaciones: `DELETE ... WHERE origen='google'` +
  `INSERT` en una sola transacción (`import_google_sheets.py:38-51`,
  `import_nutrition.py:108-125`).

### B. Índices existentes vs. consultas frecuentes

| Tabla | Índices (migración) | Consulta frecuente sin índice |
|---|---|---|
| `training_sets` | `(semana)`, `(ejercicio)` (v001) | `WHERE fecha = ?` (save/read por día) |
| `diario_alimentacion` | `(fecha, orden)` (v007/v008) | — (cubierta) |
| `health_records` | `(record_type, start_epoch_ms)` (v010) | — (cubierta) |
| `plantilla_sets` / `plantilla_alimentos` | FK indexados (v001/v009) | — (cubierta) |
| JOINs `LOWER(ejercicio)` | sin índices de expresión | `calculate_pfr_timeline`, `get_ejercicios_por_grupo`, `find_*` |

### C. Referencias cruzadas

- Guía auditada: `docs/architecture/backend-standards.md` (11 secciones + checklist §11).
- Guía frontend: `docs/architecture/web-standards.md`; forense frontend:
  `docs/analysis/2026-08-14-forensic-web-standards.md` (P0 CSRF duplicado en §3.1).
- Modelo de amenazas: `docs/architecture/security-model.md`.
- Contratos: `docs/architecture/current-ui-contract.md`, `docs/architecture/health-sync-contract.md`.

---

## Estado tras remediación (web-standards)

Los hallazgos de web-standards (misma auditoría, `docs/analysis/2026-08-14-forensic-web-standards.md`)
se remediaron según `docs/plans/2026-08-14-web-standards-remediation.md` (2026-08-15):
P0 LAN sync-only + CSRF, pipeline de tokens, contraste WCAG AA, Plotly lazy, navigator
acotado + assets versionados, dialogs nativos + regiones live, teclado/reordenamiento,
undo persistente (v013), rutas legacy retiradas, gates axe/Lighthouse. El estado
detallado del backend (este informe) se añade al completar su propio plan.
