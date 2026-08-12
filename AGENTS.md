# Instrucciones del Agente - Gym Tracker Dashboard

## 0. Máxima del Sandbox (obligatoria, permanente)

1. **Todo dentro del directorio del proyecto.** Ningún archivo temporal, log, backup o artefacto puede crearse fuera del directorio de trabajo. Prohibido escribir en `/tmp`, `/var/folders`, `~/Library` u otras rutas del sistema.
2. **Siempre el entorno virtual** `.venv` del proyecto (`uv run ...`). Nada se ejecuta con el Python/uv global del sistema.
3. **Nada sale del sandbox**: no instalar paquetes globales, no lanzar procesos que escriban fuera del proyecto, no usar rutas absolutas externas.
4. Si un comando/script necesita un directorio temporal, crear `.tmp/` dentro del proyecto y limpiarlo al terminar.
5. Esta máxima aplica a cualquier tarea y herramienta, sin excepciones.

## 1. Identidad y Rol

Eres un ingeniero de software senior experto en Python, especializado en análisis de datos, visualización interactiva y bases de datos SQLite. Tu rol en este proyecto es mantener, optimizar y extender el dashboard de progresión de gimnasio.

## 2. Tech Stack y Entorno

- **Lenguaje:** Python 3.11+
- **Entorno Virtual:** Siempre debes usar el entorno virtual ubicado en `.venv`.
- **Gestor de Dependencias:** **`uv`** es obligatorio.
  - Para instalar dependencias: `uv pip install -r requirements.txt` (o `uv pip install <package>`).
  - Para ejecutar comandos del entorno: usa `uv run <comando>` o asegúrate de que el entorno `.venv` esté activo.
- **Librerías principales:**
  - `fastapi` + `uvicorn` (Servidor web / API)
  - `jinja2` (Templates HTML servidor-side)
  - `pandas` (Manipulación de datos)
  - `plotly` (Visualizaciones y gráficos interactivos)
  - `requests` (Extracción de Google Sheets)
  - `pytest` (Testing)
- **Frontend:** HTML + **htmx** (AJAX incremental y actualización OOB de la gráfica unificada) + CSS (Tailwind, vía CDN).
- El proyecto también incluye un `run-agent.sh` + `litellm_config.yaml` para levantar un proxy LiteLLM y ejecutar este agente con modelos Gemini. No es parte del dashboard en sí.

## 3. Estructura de Directorios Clave

- `app.py`: Entrada de la aplicación FastAPI — handlers delgados (parseo de request, servicios, selección de respuesta). Sin SQL ni lógica de dominio multi-paso.
- `config.py`: Constantes globales, URLs de descarga y `DB_PATH` (configurable vía `LIFESTYLE_DB_PATH`; `GYM_DB_PATH` queda como alias de compatibilidad).
- `src/`: Lógica central del sistema.
  - `db_connection.py`: Fábrica `connect_db` (foreign_keys ON, row_factory, busy_timeout) + context managers `read_connection` / `transaction`.
  - `migrations/`: Migraciones versionadas (`v001`..`v003`) y `runner.py` (transaccionales, con backup automático antes de aplicar migraciones pendientes).
  - `models.py`: Modelos tipados (`TrainingSetInput`, `TrainingSet`, `Session`, `TemplateInput`, `Template`) y excepciones de dominio (`ValidationError`, `NotFoundError`, `ConflictError`).
  - `dashboard_service.py`: Orquestación de vistas (view models, charts, filtros) y traducción de errores a respuestas seguras.
  - `view_models.py`: `DateNavigatorViewModel`, `SessionEditorViewModel` — solo valores que necesitan las plantillas.
  - `security.py`: Middleware de headers de seguridad + CSP (nonce por respuesta, sin `'unsafe-inline'` en script-src) y protección CSRF (token firmado + validación de Origin).
  - `mutation_service.py`: Casos de uso de mutación (backup/snapshot/escritura/undo como una operación; pila de undo en memoria, máx. 10).
  - `response_fragments.py`: Render de fragmentos OOB vía partials Jinja (autoescape como única frontera HTML; targets allow-listed).
  - `fetcher.py`: Extracción HTTP de Google Sheets.
  - `parser.py`: Limpieza y transformación de CSV.
  - `database.py`: Operaciones SQLite (lecturas/escrituras) usando `src/db_connection`.
  - `training_service.py` / `template_service.py`: Servicios de dominio tipados (validación, sesiones, plantillas).
  - `metrics_engine.py`: Motor de métricas (RM ajustado, PFR, rendimiento relativo).
  - `charts.py`: Gráficos Plotly y agregaciones de datos por ejercicio/grupo.
- `static/`: Assets por responsabilidad.
  - `css/`: `app.css` (manifest de @import) + `theme`, `components`, `date-navigator`, `session-editor`, `templates`.
  - `js/`: Módulos ES (`state`, `notices`, `editor`, `row-sortable`, `templates`, `date-navigation`, `dashboard-filters`, `htmx-lifecycle`) + bootstrap `app.js` (lee `#app-config` JSON, inyecta el token CSRF vía `htmx:configRequest`, inicializa el DOM; sin bridge `window.*`). Los handlers inline fueron eliminados: toda interacción usa `data-action` + listeners delegados (ver `docs/architecture/current-ui-contract.md` §3).
- `templates/`: Plantillas Jinja2 del frontend.
  - `base.html`: Shell de layout (~70 líneas: metadata, CDNs, Tailwind config, partials, `{% block content %}`).
  - `partials/`: `notices.html`, `confirm_modal.html`, `app_config.html`.
  - `index.html`: Pantalla principal con categorías musculares y gráfica unificada.
  - Fragmentos por feature: `session_editor.html`, `date_navigator.html`, `plantillas_list.html`, `exercise_list.html`, `exercise_detail.html`, `exercise_create_form.html`.
- `data/`: Contiene la base de datos local SQLite `lifestyle.db` (regenerable) y `backups/`.
- `tests/`: Pruebas unitarias, integración y `e2e/` (Playwright, servidor aislado + DB temporal).
- `docs/`: Arquitectura (`current-ui-contract.md`, `security-model.md`, `health-sync-contract.md`), operaciones (`local-development.md`, `release-checklist.md`, `health-sync-migration.md`), planes.
- `scripts/`: `import_google_sheets.py` (carga del CSV), `verify_editor.py` (chequeo del editor).
- `assets/body_map.svg`: Mapa corporal (recurso visual).
- `android/`: App HealthSync (Kotlin) — extractor de Health Connect → backend. Gradle SIEMPRE desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle` y `ANDROID_HOME=$PWD/android/sdk` (sandbox). Estructura: `HealthConnectManager` (SDK, permisos = catálogo + background + history), `RecordTypes.kt` (catálogo canónico ESENCIAL de 17 tipos, con permisos vía `getReadPermission`), `data/` (Room: `health_records`, `health_sync_state`, `sync_targets`, `health_outbox`), `HealthRepository` (Changes API por tipo + outbox por destino), `HealthSyncClient` (HTTPS, lotes ≤500 ops), `SyncWorker`/`SyncScheduler` (WorkManager 1h + manual), `SecureTargetStore` (URL en DataStore, token cifrado en Keystore). **UI minimalista sin formulario**: el destino se embebe en builds debug vía `BuildConfig.DEFAULT_SYNC_URL`/`DEFAULT_SYNC_TOKEN` (token leído de `data/hc_sync_token` en build-time; release sin secreto); la UI es solo estado + "Permisos esenciales" + "Sincronizar AHORA".

## 4. Modelo de Datos (SQLite)

La base `data/lifestyle.db` tiene las tablas `ejercicios`, `training_sets`, `plantillas`,
`plantilla_sets` y `schema_migrations` (versiones aplicadas). El esquema se gestiona
exclusivamente con las migraciones versionadas en `src/migrations/`; no se hacen
`ALTER TABLE` a mano.

**`ejercicios`**

- `id` INTEGER PK
- `grupo_muscular` TEXT NOT NULL
- `ejercicio` TEXT NOT NULL UNIQUE
- `categoria` TEXT (backfilled desde grupo muscular)
- `origen` TEXT NOT NULL DEFAULT 'google' ('manual' para creados desde el UI)

**`training_sets`**

- `id` INTEGER PK
- `semana` INTEGER NOT NULL
- `dia` TEXT NOT NULL
- `fecha` TEXT (formato `d/m/yy`, contrato de datos vigente)
- `set_orden` INTEGER NOT NULL
- `ejercicio` TEXT NOT NULL
- `reps` REAL
- `kg` REAL
- `rir` REAL
- `origen` TEXT NOT NULL DEFAULT 'google' ('manual' para sesiones guardadas)

**`plantillas`**: `id`, `nombre` UNIQUE, `clasificacion`, `created_at`, `updated_at`, `orden`.
**`plantilla_sets`**: `id`, `plantilla_id` FK CASCADE, `set_orden`, `ejercicio`.

**`alimentos`**: `id`, `nombre` UNIQUE, `categoria`, nueve nutrientes por 100 g (`kcal`, `carbohidratos`, `fibra`, `proteina`, `grasa`, `hierro`, `calcio`, `vitamina_c`, `vitamina_a`), `origen` ('google'|'manual').

**`diario_alimentacion`**: `id`, `fecha` ISO `YYYY-MM-DD`, `orden`, `alimento`, `cantidad_g` (NULL para placeholders "—"), nueve nutrientes (snapshot recalculado desde el catálogo, sin FK a `alimentos`), `origen`. Índice `(fecha, orden)`.

**`parametros_diarios`**: `fecha` PK, `peso_kg`, `factor_proteina` (1.5), `factor_grasa` (1.1), `kcal_objetivo` — editables día a día — y `fibra/hierro/calcio/vitamina_c/vitamina_a` objetivo (importados de la hoja).

**`health_records`** (migración v010): espejo genérico de Health Connect. `hc_id` TEXT PK (id de HC, deduplicación), `record_type` (allow-list en `src/health_sync_service.py`, espejo de `RecordTypes.kt`), `start/end_epoch_ms`, `last_modified_epoch_ms` (revisión), `data_origin_package`, `payload_schema_version`, `value_json` (snapshot crudo versionado), `device_id`, `received_at`, `updated_at`, `deleted_at` (baja lógica). Índice `(record_type, start_epoch_ms)`. Las consultas y el export excluyen borradas por defecto.

## 5. Arquitectura del Dashboard (FastAPI + htmx)

La app `app.py` sirve HTML renderizado con Jinja2 y usa htmx para actualizaciones parciales:

- **`GET /`** → index con categorías musculares y gráfica global (PFR sistémico). Incluye `#app-config` (JSON con `categoria_map` y `csrf_token`).
- **`GET /fecha/editor?fecha=`** → fragmento del editor de sesión.
- **`POST /entrenamiento/session/save`** y **`POST /entrenamiento/session/eliminar`** → mutaciones OOB (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`, `#editor-state`).
- **`POST /ejercicio/nuevo`** → crea ejercicio desde el UI (OOB `#notice-container`, `#exercise-create`).
- **`GET /plantillas` / `POST /plantilla/guardar|editar|eliminar|reordenar` / `GET /plantilla/aplicar/{id}`** → CRUD y drag&drop de plantillas (OOB `#plantillas-section`, `#session-editor-wrap`).
- **`POST /undo`** → deshace la última acción (pila en memoria, máx. 10).
- **`GET /exportar/csv`** → descarga CSV de `training_sets`.
- **`POST /sync/health-connect`** → API JSON (no htmx) de ingesta de Health Connect: autenticada con `X-Sync-Token` (`HC_SYNC_TOKEN` env; sin env → 503), exenta del CSRF de formularios **solo por igualdad exacta de ruta** (`CSRF_EXEMPT_PATHS` en `src/security.py`), lotes ≤500 ops / 1 MiB, upsert condicionado por revisión + baja lógica, acuse individual por `hc_id`+revisión (contrato en `docs/architecture/health-sync-contract.md`).
- **`GET /exportar/health-connect.csv`** → CSV de `health_records` activos (orden `record_type, start_epoch_ms`); `?incluir_borrados=1` para auditoría de bajas.
- **`GET /select`** → lista de ejercicios del grupo (`grupo=""` para global) con gráfica OOB.
- **`GET /grupo/reset`** → actualiza la gráfica con el rendimiento del grupo (PFR del grupo muscular).
- **`GET /ejercicio`** → tablas de detalle (raw + resumen por sesión) con gráfica OOB del ejercicio.
- **Panel de alimentación integrado en `/`** (arriba del editor de sesión; no hay página standalone). **`GET /alimentacion/editor?fecha=`** → fragmento del editor. **`POST /alimentacion/save`** (solo `fecha`, `alimento[]`, `cantidad[]` + `peso_kg`, `factor_proteina`, `factor_grasa`, `kcal_objetivo`; el servidor recalcula contra el catálogo con `ROUND_HALF_UP(catálogo_100g × g / 100)`, nunca confía en macros del cliente) y **`POST /alimentacion/eliminar`** → mutaciones OOB (`#nutrition-editor-wrap`, `#nutrition-date-navigator`). **`POST /alimento/nuevo`** → alta de alimento (OOB `#alimento-create` + `#app-config` con `alimento_map` actualizado). **`GET /alimentacion/exportar/csv`** → CSV de `diario_alimentacion`. El `#app-config` del index incluye `alimento_map` (9 nutrientes) para la previsualización client-side. Fórmulas de objetivo: `prot = peso × factor_proteina`, `grasa = peso × factor_grasa`, `kcal` editable, `carb = (kcal − 4prot − 9grasa)/4`; la fila Consumido es la suma del día.
- La importación de Google Sheets **no es una ruta HTTP**: se ejecuta con `python scripts/import_google_sheets.py` (entrenamiento) y `python scripts/import_nutrition.py` (alimentación; idempotente, backup previo, reemplaza solo `origen='google'`).
- Todos los handlers son `def` síncronos (FastAPI los ejecuta en threadpool); las mutaciones exigen token CSRF (`X-CSRF-Token` desde `#app-config`) y Origin del mismo sitio. Errores de dominio → 400 con aviso seguro; excepciones inesperadas → 500 genérico (log servidor).

**Flujo frontend (en `index.html`):**

1. El usuario selecciona un grupo muscular (Empuje / Tirón / Pierna / Core).
2. `#exercise-section` se actualiza con `exercise_list.html` vía htmx.
3. La gráfica única `#unified-chart` se refresca mediante `hx-swap-oob="innerHTML"` en la misma respuesta.
4. Seleccionar un ejercicio carga `exercise_detail.html` en `#history-section` y actualiza la gráfica unificada.

## 6. Reglas de Codificación (Coding Standards)

- **Tipado Estricto:** Usa anotaciones de tipo (Type Hints) en todas las firmas de funciones en `src/`.
- **Manejo de Errores:** Nunca uses excepciones genéricas (`except:`). Captura errores específicos y regístralos o elévalos adecuadamente. En `app.py`, las funciones auxiliares de lectura DB (`get_db_status`, `get_filters`, etc.) usan `try/except Exception` y devuelven valores seguros.
- **Estructura del Parser:**
  - La hoja `ciclo_16` tiene columnas repetitivas por semana (Ejercicio, Reps, Kg, RIR). El parser debe procesarlas de forma iterativa y limpia.
  - Los datos faltantes (campos vacíos) deben ser mapeados a `None` o `float('nan')` en Pandas, y guardarse como `NULL` en SQLite.
- **Motor de Métricas:**
  - `RM ajustado = kg * (1 + 0.0333 * (reps + 1 + rir))`.
  - El rendimiento relativo (%) se calcula contra el baseline (promedio RM de la primera semana del ejercicio).
  - Puedes extender `metrics_engine.py` para nuevas métricas, manteniendo los mismos patrones (DataFrame + filtros `systemic`/`muscle_group`/`exercise`).
- **SQL Seguro:** Usa consultas parametrizadas (`?`) en SQLite para evitar cualquier vulnerabilidad, incluso si los datos provienen de tu propia hoja.

## 7. Estética del Frontend

- Mantén la identidad visual actual: fondo oscuro (`bg-matte-950`/`bg-neutral-900`), acento borgoña **`burgundy-700` / `burgundy-400`** (`#9b1b30`/`#e56d88`), toques "neón" (`neon-border`, `neon-title`).
- Las gráficas Plotly usan `plot_bgcolor`/`paper_bgcolor` transparentes para integrarse con el tema oscuro.
- Respeta el patrón de fracciones de template (`exercise_list.html`, `exercise_detail.html`) y la gráfica única con `hx-swap-oob`.

## 8. Control de Calidad y Pruebas

Antes de dar por completada una tarea, debes:

1. Validar que las pruebas pasen (unidad + integración + browser):
   ```bash
   uv run pytest
   ```
2. Ejecutar las puertas de calidad estáticas:
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy app.py src tests
   ```
3. Ejecutar la app localmente para verificar la interfaz en caso de cambios visuales:
   ```bash
   uv run uvicorn app:app --host 127.0.0.1 --reload
   ```
4. Si agregas dependencias, actualiza `pyproject.toml` y regenera el lock:
   ```bash
   uv lock && uv sync --locked
   ```
   (`requirements.txt` se conserva solo como export de compatibilidad.)
