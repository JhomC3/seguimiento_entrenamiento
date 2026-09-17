# Instrucciones del Agente - Gym Tracker Dashboard

## 0. Máxima del Sandbox (obligatoria, permanente)

1. **Todo dentro del directorio del proyecto.** Ningún archivo temporal, log, backup o artefacto puede crearse fuera del directorio de trabajo. Prohibido escribir en `/tmp`, `/var/folders`, `~/Library` u otras rutas del sistema.
2. **Siempre el entorno virtual** `.venv` del proyecto (`uv run ...`). Nada se ejecuta con el Python/uv global del sistema.
3. **Nada sale del sandbox**: no instalar paquetes globales, no lanzar procesos que escriban fuera del proyecto, no usar rutas absolutas externas.
4. Si un comando/script necesita un directorio temporal, crear `.tmp/` dentro del proyecto y limpiarlo al terminar.
5. Esta máxima aplica a cualquier tarea y herramienta, sin excepciones.

## 0.5. Máxima de Git y Worktrees (obligatoria, permanente)

1. **Una tarea = una rama = un worktree.** Cada agente o tarea trabaja en su propio
   directorio (`git worktree`) con su propia rama. **Prohibido** que dos agentes o
   dos tareas compartan el mismo directorio de trabajo.
2. **Prohibido empezar sobre un árbol sucio.** Antes de crear un worktree o cambiar
   de tarea: haz commit en su rama o `git stash -u`. Un worktree nuevo nace del HEAD,
   nunca arrastra cambios sin commitear.
3. **Aislamiento por worktree:** cada worktree tiene su propio `.venv`
   (`uv sync --locked`), su propia DB (`data/*.db` está gitignored: copiar o
   regenerar con los scripts de importación), sus propios secretos
   (`scripts/start_server.sh` los genera) y su propio puerto (8001, 8002…; el 8000
   es del trabajo principal). El SDK de Android también es por worktree
   (`ANDROID_HOME=$PWD/android/sdk`, ver §2).
4. **Mantenimiento constante de git:** commits pequeños por hito con mensaje conciso
   (estilo del repo); antes de cada commit inspecciona `git status`, `git diff` y
   `git log --oneline -10`; stage solo los ficheros intencionados, nunca secretos;
   sincroniza con la base (rebase/merge) antes de integrar; revisa rama y diff antes
   de confirmar cambios (sin commits ni pushes automáticos); tras el merge elimina
   el worktree (`git worktree remove`) y poda (`git worktree prune`), y borra las
   ramas ya integradas.
5. Esta máxima aplica a cualquier tarea, agente y herramienta, sin excepciones.
   Procedimiento operativo: `docs/operations/local-development.md` § "Parallel work".

## 1. Identidad y Rol

Eres un ingeniero de software senior experto en Python, especializado en análisis de datos, visualización interactiva y bases de datos SQLite. Tu rol en este proyecto es mantener, optimizar y extender el dashboard de progresión de gimnasio.

## 2. Tech Stack y Entorno

- **Lenguaje:** Python 3.11+
- **Entorno Virtual:** Siempre debes usar el entorno virtual ubicado en `.venv`.
- **Gestor de Dependencias:** **`uv`** es obligatorio.
  - Para instalar dependencias: edita `pyproject.toml` y ejecuta `uv lock && uv sync --locked` (el `requirements.txt` es un export de compatibilidad, no se edita a mano).
  - Para ejecutar comandos del entorno: usa `uv run <comando>` o asegúrate de que el entorno `.venv` esté activo.
- **Librerías principales:**
  - `fastapi` + `uvicorn` (Servidor web / API)
  - `jinja2` (Templates HTML servidor-side)
  - `pandas` (Manipulación de datos)
  - `plotly` (Visualizaciones y gráficos interactivos)
  - `requests` (Extracción de Google Sheets)
  - `pytest` (Testing)
- **Frontend:** HTML + **htmx** (AJAX incremental y actualización OOB) + **Tailwind compilado estáticamente** (sin CDN runtime): `scripts/build_css.sh` (npx tailwindcss 3.4.17) compila `static/css/input.css` → `static/css/tailwind.css` (minificado, commiteado). Los colores/tokens canónicos viven en `static/design-tokens.json` (generado por `scripts/build_design_tokens.py`) y se consumen desde `tailwind.config.js`. Tras tocar clases en templates/JS hay que recompilar el CSS (`./scripts/build_css.sh`) o los cambios no se verán.
- El proyecto incluye `android/` (app HealthSync) y scripts de soporte; no hay otros agentes embebidos.

## 3. Estructura de Directorios Clave

- `app.py`: Entrada de la aplicación FastAPI — handlers delgados (parseo de request, servicios, selección de respuesta). Sin SQL ni lógica de dominio multi-paso.
- `config.py`: Constantes globales, URLs de descarga de Google Sheets (entrenamiento + nutrición) y `DB_PATH` (configurable vía `LIFESTYLE_DB_PATH`; `GYM_DB_PATH` queda como alias de compatibilidad). `HC_SYNC_TOKEN` se lee del env o, si falta, del archivo `data/hc_sync_token`.
- `src/`: Lógica central del sistema.
  - `db_connection.py`: Fábrica `connect_db` (foreign_keys ON, row_factory, busy_timeout) + context managers `read_connection` / `transaction`.
  - `migrations/`: Migraciones versionadas `v001`..`v020` (no existe `v004`) — v005 recomputa `semana`, v006 normaliza fechas a ISO, v007–v009 alimentación, v010 Health Connect, v011 `descanso_seg`, v012 `cardio_annotations`, v013 `undo_entries` (journal de undo persistente), v014 índice `training_sets(fecha, set_orden)`, v015 `training_splits`/`training_split_items` (gestor de splits), v016 `training_splits.activo` (split actual único), v017 `velocidad_kmh`/`dificultad` (series HIIT), v018 objetivos DRI + curaduría Arepa/Huevo/huérfanos, v019 12 micros nuevos (Mg, Zn, K, Na, D, E, K, folato, B12, B6, yodo, selenio), v020 relleno DRI en `*_objetivo` en 0 dejados por guardados sin micros — y `runner.py` (transaccionales, con backup automático antes de aplicar migraciones pendientes). La app aplica las migraciones pendientes en el arranque.
  - `models.py`: Modelos tipados (`TrainingSetInput`, `TrainingSet`, `Session`, `TemplateInput`, `Template`) y excepciones de dominio (`ValidationError`, `NotFoundError`, `ConflictError`).
  - `dashboard_service.py`: Orquestación de vistas (view models, charts, filtros) y traducción de errores a respuestas seguras.
  - `view_models.py`: `DateNavigatorViewModel`, `SessionEditorViewModel` — solo valores que necesitan las plantillas.
  - `security.py`: Middleware de headers de seguridad + CSP estática (sin nonce ni `'unsafe-inline'` en script-src; `'unsafe-inline'` solo en style-src, requerido por Plotly) y protección CSRF (token firmado + validación de Origin).
  - `mutation_service.py`: Casos de uso de mutación (backup/snapshot/escritura/undo como una operación; journal de undo persistente en SQLite (`undo_entries`, v013; máx. 10 entradas, snapshots solo del lado `before`)).
  - `response_fragments.py`: Render de fragmentos OOB vía partials Jinja (autoescape como única frontera HTML; targets allow-listed).
  - `fetcher.py`: Extracción HTTP de Google Sheets.
  - `parser.py`: Limpieza y transformación de CSV.
  - `database.py`: Operaciones SQLite (lecturas/escrituras) usando `src/db_connection`.
  - `training_service.py` / `template_service.py`: Servicios de dominio tipados (validación, sesiones, plantillas).
  - `metrics_engine.py`: Motor de métricas (RM ajustado, PFR, rendimiento relativo).
  - `charts.py`: Gráficos Plotly y agregaciones de datos por ejercicio/grupo.
  - `nutrition_service.py`: Servicio de dominio de alimentación (cálculo contra el catálogo `alimentos`; nunca confía en macros del cliente).
  - `health_sync_service.py`: Ingesta de Health Connect (validación, upsert por revisión, acuses).
  - `cardio_service.py`: Anotaciones de cardio (velocidad/inclinación) sobre sesiones `EXERCISE_SESSION`.
  - `exercise_service.py`: Caso de uso de alta de ejercicio.
  - `analysis_data.py`: Capas de análisis diario (series agregadas por día, JSON1).
  - `network_access.py`: Middleware del gate LAN sync-only (remoto solo `POST /sync/health-connect` + API v1 del diario; rate-limit por peer).
  - `backup_utils.py`: Backups pre-mutación.
  - `design_tokens.py`: Token visual canónico (fuente de `static/design-tokens.json`).
- `static/`: Assets por responsabilidad.
  - `css/`: `app.css` (manifest de @import) + `tokens.css` (CSS custom properties de los design tokens), `theme`, `components`, `date-navigator`, `session-editor`, `templates`, `cascade`.
  - `js/`: Módulos ES (`state`, `notices`, `editor`, `editor-popup`, `row-sortable`, `templates`, `date-navigation`, `chart-interaction`, `level-cascade`, `nutrition-editor`, `nutrition-templates`, `panel-collapse`, `htmx-lifecycle`) + bootstrap `app.js` (lee `#app-config` JSON, inyecta el token CSRF vía `htmx:configRequest`, inicializa el DOM; sin bridge `window.*`). Los handlers inline fueron eliminados: toda interacción usa `data-action` + listeners delegados (ver `docs/architecture/current-ui-contract.md` §3).
- `templates/`: Plantillas Jinja2 del frontend.
  - `base.html`: Shell de layout (~70 líneas: metadata, CDNs, Tailwind config, partials, `{% block content %}`).
  - `partials/`: `notices.html`, `confirm_modal.html`, `app_config.html`.
  - `index.html`: Pantalla principal con categorías musculares y gráfica unificada.
  - Fragmentos por feature: `editor_popup.html` (popup de registro), `session_editor.html`, `date_navigator.html`, `cardio_day.html`, `nutrition_editor.html`, `cascade_row.html`/`ejercicios_row.html` (cascada de niveles), `session_history.html`, `exercise_detail.html`, `exercise_create_form.html`, `plantillas_list.html`, `plantillas_alimentacion_list.html`, `alimento_create_form.html`, `splits.html` (página del gestor de splits) + `partials/split_accordion.html` (sección de splits: estado vacío o lista), `partials/split_accordion_item.html` (item acordeón con board semanal), `partials/split_board.html` (7 tarjetas de día con resumen jerárquico + lista editable).
- `data/`: Contiene la base de datos local SQLite `lifestyle.db` (regenerable), `backups/` y los secretos gitignored `hc_sync_token` / `csrf_secret` (generados por `scripts/start_server.sh`).
- `tests/`: Pruebas unitarias, integración y `e2e/` (Playwright, servidor aislado + DB temporal).
- `docs/`: Arquitectura (`current-ui-contract.md`, `security-model.md`, `health-sync-contract.md`), operaciones (`local-development.md`, `release-checklist.md`, `health-sync-migration.md`), planes.
- `scripts/`: `import_google_sheets.py` (carga del CSV de entrenamiento), `import_nutrition.py` (alimentación; idempotente, backup previo, reemplaza solo `origen='google'`), `start_server.sh` (arranque LAN sync-only: genera/persiste `hc_sync_token` + `csrf_secret`), `build_css.sh` (compila Tailwind), `build_design_tokens.py` (genera `static/design-tokens.json`), `check_module_coverage.py` (pisos de cobertura por módulo), `audit_ui.py` (barrido de auditoría funcional de UI con Playwright sobre copia de la DB real), `audit_consistency.py` (gate de vocabulario canónico de componentes en CI).
- `assets/body_map.svg`: Mapa corporal (recurso visual).
- `android/`: App HealthSync (Kotlin) — extractor de Health Connect → backend. Gradle SIEMPRE desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle` y `ANDROID_HOME=$PWD/android/sdk` (sandbox): `JAVA_HOME=/opt/homebrew/opt/openjdk@21 GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk ./gradlew assembleDebug test`. Estructura: `HealthConnectManager` (SDK, permisos = catálogo + background + history), `RecordTypes.kt` (catálogo Android de 17 tipos núcleo, con permisos vía `getReadPermission`; la allow-list de ingesta del servidor en `health_sync_service.py` es un superset de 40 — son ámbitos compatibles, no un espejo), `data/` (Room: `health_records`, `health_sync_state`, `sync_targets`, `health_outbox`), `HealthRepository` (Changes API por tipo + outbox por destino), `HealthSyncClient` (HTTPS, lotes ≤500 ops), `SyncWorker`/`SyncScheduler`/`SyncService` (WorkManager 1h + manual), `SyncPlanner`/`SyncExecutor`/`HealthInventory`, `SecureTargetStore` (URL en DataStore, token cifrado en Keystore). **UI minimalista sin formulario**: el destino se embebe en builds debug vía `BuildConfig.DEFAULT_SYNC_URL`/`DEFAULT_SYNC_TOKEN` (token leído de `data/hc_sync_token` en build-time; release sin secreto); la UI es solo estado + "Permisos esenciales" + "Sincronizar AHORA". **Tema = port de `static/design-tokens.json`**: `android/app/src/main/res/values/` (`colors.xml` 1:1 de los tokens, `themes.xml` con `AppTheme` oscuro, `styles.xml` con el vocabulario espejo de `components.css` aplicado vía `DiaryTheme.kt`; test `ThemeContractTest`).

## 4. Modelo de Datos (SQLite)

La base `data/lifestyle.db` tiene las tablas `ejercicios`, `training_sets`, `plantillas`,
`plantilla_sets`, `alimentos`, `diario_alimentacion`, `parametros_diarios`,
`health_records`, `cardio_annotations`, `training_splits`, `training_split_items`
y `schema_migrations` (versiones aplicadas).
El esquema se gestiona exclusivamente con las migraciones versionadas en
`src/migrations/`; no se hacen `ALTER TABLE` a mano.

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
- `fecha` TEXT (ISO `YYYY-MM-DD` desde v006; el formato legado `d/m/yy` quedó normalizado por migración)
- `set_orden` INTEGER NOT NULL
- `ejercicio` TEXT NOT NULL
- `reps` REAL
- `kg` REAL
- `rir` REAL
- `descanso_seg` REAL (v011, segundos de descanso opcionales por serie)
- `velocidad_kmh` REAL (v017, solo series `HIIT`, 1 decimal)
- `dificultad` REAL (v017, solo series `HIIT`, decimal ≥ 0)
- `origen` TEXT NOT NULL DEFAULT 'google' ('manual' para sesiones guardadas)

**`plantillas`**: `id`, `nombre` UNIQUE, `clasificacion`, `created_at`, `updated_at`, `orden`.
**`plantilla_sets`**: `id`, `plantilla_id` FK CASCADE, `set_orden`, `ejercicio`.

**`alimentos`**: `id`, `nombre` UNIQUE, `categoria`, 21 nutrientes por 100 g (`kcal`, `carbohidratos`, `fibra`, `proteina`, `grasa`, `hierro`, `calcio`, `vitamina_c`, `vitamina_a` + v019: `magnesio`, `zinc`, `potasio`, `sodio`, `vitamina_d`, `vitamina_e`, `vitamina_k`, `folato`, `vitamina_b12`, `vitamina_b6`, `yodo`, `selenio`), `origen` ('google'|'manual').

**`diario_alimentacion`**: `id`, `fecha` ISO `YYYY-MM-DD`, `orden`, `alimento`, `cantidad_g` (NULL para placeholders "—"), 21 nutrientes (snapshot recalculado desde el catálogo, sin FK a `alimentos`), `origen`. Índice `(fecha, orden)`.

**`parametros_diarios`**: `fecha` PK, `peso_kg`, `factor_proteina` (1.5), `factor_grasa` (1.1), `kcal_objetivo` — editables día a día — y 17 objetivos de micros con defaults DRI (5 clásicos + 12 v019).

**`health_records`** (migración v010): espejo genérico de Health Connect. `hc_id` TEXT PK (id de HC, deduplicación), `record_type` (allow-list de 40 en `src/health_sync_service.py`, superset del catálogo Android de 17), `start/end_epoch_ms`, `last_modified_epoch_ms` (revisión), `data_origin_package`, `payload_schema_version`, `value_json` (snapshot crudo versionado), `device_id`, `received_at`, `updated_at`, `deleted_at` (baja lógica). Índice `(record_type, start_epoch_ms)`. Las consultas y el export excluyen borradas por defecto.

**`cardio_annotations`** (migración v012): anotaciones manuales sobre sesiones `EXERCISE_SESSION` espejadas. `id` PK, `hc_id` TEXT UNIQUE FK → `health_records(hc_id)` ON DELETE CASCADE, `velocidad_kmh`, `inclinacion_pct`, `notas`, `created_at`, `updated_at`. Una anotación con todos los campos vacíos se elimina.

**`training_splits`** (migraciones v015–v016): splits semanales de entrenamiento. `id` PK, `nombre` (UNIQUE case-insensitive vía índice en `LOWER(nombre)`), `created_at`, `updated_at`, `activo` (v016, INTEGER 0/1, único vía índice parcial `WHERE activo = 1`: un solo split actual).
**`training_split_items`** (migración v015): `id` PK, `split_id` FK → `training_splits(id)` ON DELETE CASCADE, `dia` (canónico `LUNES..DOMINGO`), `orden` (renumerado por día en el servidor), `item_type` (`'ejercicio'` | `'hiit'`), `ejercicio`, `grupo_muscular` (derivado del catálogo en servidor; `'HIIT'` para cardio). UNIQUE `(split_id, dia, orden)`; los duplicados del mismo ejercicio en un día son válidos (cada instancia = 1 serie).

## 5. Arquitectura del Dashboard (FastAPI + htmx)

La app `app.py` sirve HTML renderizado con Jinja2 y usa htmx para actualizaciones parciales:

- **`GET /`** → index con categorías musculares y gráfica global (PFR sistémico). Incluye `#app-config` (JSON con `categoria_map`, `alimento_map`, `ciclo_start` y `csrf_token`).
- **`GET /fecha/editor?fecha=`** → fragmento del editor de sesión.
- **`GET /editor/popup?fecha=`** → cuerpo del popup de registro (navegador + editor de sesión + alimentación + cardio).
- **`POST /entrenamiento/session/save`** y **`POST /entrenamiento/session/eliminar`** → mutaciones OOB (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`, `#editor-state`).
- **`POST /ejercicio/nuevo`** → crea ejercicio desde el UI (OOB `#notice-container`, `#exercise-create`).
- **`GET /plantillas` / `POST /plantilla/guardar|editar|eliminar|reordenar` / `GET /plantilla/aplicar/{id}`** → CRUD y drag&drop de plantillas (OOB `#plantillas-section`, `#session-editor-wrap`).
- **`GET /splits` (página completa a ancho completo; `?abrir={id}` precarga) / `GET /split/nuevo` (item nuevo sin persistir) / `POST /split/guardar` / `POST /split/eliminar/{split_id}` / `POST /split/activar/{split_id}`** → gestor de splits semanales: acordeón de items (split actual primero y abierto, check discreto en el toolbar para marcar el actual), tarjetas de día de dimensiones invariantes con resumen jerárquico colapsable + lista editable (scrolls internos), catálogo izquierda sticky (duplicados = series, HIIT como item especial, métricas server-authoritative); OOB `#splits-section`; undo kind `'splits'` (incluye el activo). La ruta `GET /split/{split_id}` fue retirada (los boards viven en la sección).
- **`POST /undo`** → deshace la última acción (journal `undo_entries` en SQLite, máx. 10).
- **`GET /healthz`** → liveness JSON (`{"status": "ok", "db": "ok"}`; 503 si la DB no responde). `/docs`, `/redoc` y `/openapi.json` están **deshabilitados** (sin inventario público).
- **`POST /sync/health-connect`** → API JSON (no htmx) de ingesta de Health Connect: autenticada con `X-Sync-Token` (`HC_SYNC_TOKEN` env; sin env → 503), exenta del CSRF de formularios **solo por igualdad exacta de ruta** (`CSRF_EXEMPT_PATHS` en `src/security.py`), lotes ≤500 ops / 1 MiB, upsert condicionado por revisión + baja lógica, acuse individual por `hc_id`+revisión (contrato en `docs/architecture/health-sync-contract.md`).
- **API v1 del diario (JSON móvil, no htmx; contrato en `docs/architecture/training-api-contract.md`):** **`GET /api/v1/sesion?fecha=`** (sesión del día con RM recalculado), **`POST /api/v1/sesion`** (`{fecha, sets[]}`, reemplazo total idempotente, 1–100 series, misma `validate_sets` que la web, backup + journal `sesion`), **`DELETE /api/v1/sesion?fecha=`** (idempotente), **`GET /api/v1/ejercicios`** (catálogo `ejercicio/grupo_muscular/categoria` + `meta.categorias` para el alta). **B1 entreno full:** **`GET /api/v1/plantillas`**, **`POST /api/v1/plantilla/aplicar`** (`{plantilla_id, fecha}`, preview sin escribir), **`POST /api/v1/plantilla/guardar`** (`{nombre, ejercicios[]}`, upsert por nombre, journal `entrenos`), **`POST /api/v1/ejercicio`** (alta, 409 duplicado), **`GET /api/v1/undo/peek`** + **`POST /api/v1/undo`** (`{fecha?}`, consume 1 entrada). Mismo `X-Sync-Token` (503 sin token, 401 inválido, 404 inexistente, 409 conflicto); `POST`/`DELETE` exentos de CSRF por igualdad exacta de ruta.
- **API v1 nutrición (JSON móvil, B2; mismo contrato):** **`GET /api/v1/diario?fecha=`** (entradas + consumido + objetivo Atwater + parámetros, con prefill heredado `prefill_source`), **`POST /api/v1/diario`** (`{fecha, entradas[], peso_kg?, factor_proteina?, factor_grasa?, kcal_objetivo?}`; nutrientes recalculados en servidor, reemplazo idempotente, journal `alimentacion`), **`DELETE /api/v1/diario?fecha=`** (idempotente, conserva parámetros), **`GET /api/v1/alimentos`** (21 nutrientes/100 g + `meta.nutrientes`), **`POST /api/v1/alimento`** (alta, 409 duplicado), **`GET /api/v1/plantillas-comida`** + **`POST /api/v1/plantilla-comida/aplicar`** (preview recalculado sin escribir) + **`POST /api/v1/plantilla-comida/guardar`** (upsert por nombre, sin undo como la web). **Cardio (B3):** `GET /api/v1/cardio?fecha=`, `POST /api/v1/cardio/anotacion` (vacío = borrar). **Sugerencia (rueda):** `GET /api/v1/sugerencia?fecha=`. **B4:** `GET /api/v1/fechas?vista=` + offline móvil (caché nutrición + `pending_writes` con drenado oportunista).
- **`GET /exportar/health-connect.csv`** → CSV de `health_records` activos (orden `record_type, start_epoch_ms`); `?incluir_borrados=1` para auditoría de bajas.
- **`GET /nivel?tipo=global|musculo|ejercicio&foco=`** → cascada de niveles: fila de músculos → ejercicios del músculo → detalle en `#history-section`; OOB de `#unified-chart` con el compilado de la selección.
- **`GET /grafica`** → fragmento de la gráfica de la selección actual (1 músculo: compilado + ejercicios; 2+: global + músculos).
- **`GET /semana/primer-entreno?semana=`** → primera fecha de entrenamiento de la semana (JSON).
- **`POST /cardio/annotation`** → guarda o elimina anotación de cardio (OOB).
- **Panel de alimentación integrado en `/`** (arriba del editor de sesión; no hay página standalone). **`GET /alimentacion/editor?fecha=`** → fragmento del editor. **`POST /alimentacion/save`** (solo `fecha`, `alimento[]`, `cantidad[]` + `peso_kg`, `factor_proteina`, `factor_grasa`, `kcal_objetivo`; el servidor recalcula contra el catálogo con `ROUND_HALF_UP(catálogo_100g × g / 100)`, nunca confía en macros del cliente)   y **`POST /alimentacion/eliminar`** → mutaciones OOB (`#nutrition-editor-wrap`). **`POST /alimento/nuevo`** → alta de alimento (OOB `#alimento-create` + `#app-config` con `alimento_map` actualizado). **`POST /alimentacion/plantilla/guardar|eliminar|reordenar`** y **`GET /alimentacion/plantilla/aplicar/{id}`** → plantillas de comidas (OOB `#nutrition-editor-wrap`). El `#app-config` del index incluye `alimento_map` (21 nutrientes) para la previsualización client-side. Fórmulas de objetivo: `prot = peso × factor_proteina`, `grasa = peso × factor_grasa`, `kcal` editable, `carb = (kcal − 4prot − 9grasa)/4`; la fila Consumido es la suma del día.
- La importación de Google Sheets **no es una ruta HTTP**: se ejecuta con `python scripts/import_google_sheets.py` (entrenamiento) y `python scripts/import_nutrition.py` (alimentación; idempotente, backup previo, reemplaza solo `origen='google'`).
- Todos los handlers son `def` síncronos (FastAPI los ejecuta en threadpool); las mutaciones exigen token CSRF (`X-CSRF-Token` desde `#app-config`) y Origin del mismo sitio. Errores de dominio → 400 con aviso seguro; excepciones inesperadas → 500 genérico (log servidor).
- **Gate LAN sync-only** (`GYM_LAN_SYNC_ONLY=1`, activado por `scripts/start_server.sh`): en LAN el servidor sirve **solo** `POST /sync/health-connect` + la API v1 del diario (`GET`/`POST`/`DELETE /api/v1/sesion`, `GET /api/v1/ejercicios`, `GET /api/v1/plantillas`, `POST /api/v1/plantilla/guardar|aplicar`, `POST /api/v1/ejercicio`, `GET /api/v1/undo/peek`, `POST /api/v1/undo`, `GET /api/v1/sugerencia`, `GET`/`POST /api/v1/cardio(/anotacion)`, `GET /api/v1/fechas`, `GET`/`POST`/`DELETE /api/v1/diario`, `GET /api/v1/alimentos`, `POST /api/v1/alimento`, `GET /api/v1/plantillas-comida`, `POST /api/v1/plantilla-comida/guardar|aplicar`, allow-list exacta `ALLOWED_REMOTE_ROUTES` en `src/network_access.py`); cualquier otra petición remota recibe 403 antes de parsear el body. Rate-limit por peer `GYM_SYNC_RATE_LIMIT_PER_MINUTE` (default 30, 429 + `Retry-After`). Exige `GYM_CSRF_SECRET` (persistido en `data/csrf_secret`); el arranque falla si el par env/secreto es inconsistente.

**Flujo frontend (contrato vigente v3: `docs/architecture/current-ui-contract.md`):**

1. La pantalla principal es una cascada de niveles (`GET /nivel`): fila de músculos (multi-selección con shift+click, `tipo=global` restaura estado base) → ejercicios del músculo → detalle tabular en `#history-section`.
2. La gráfica única `#unified-chart` se refresca vía `hx-swap-oob` en la misma respuesta; los datos Plotly viajan en `#unified-chart-data` (JSON inline) y se renderizan con `chart-interaction.js`.
3. Clic en un día de la gráfica abre el popup de registro (`/editor/popup`); las mutaciones devuelven OOB (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`, `#editor-state`).

## 5.5 Backend Standards (innegociables)

Referencia completa: `docs/architecture/backend-standards.md` (forense: `docs/analysis/2026-08-14-forensic-backend-standards.md`). Principios vinculantes:

- **Monolito modular con dominio puro:** handlers delgados → servicios de dominio tipados
  → `src/database.py` (única capa con SQL). Prohibido lógica de negocio en `app.py`,
  SQL fuera de `database.py` o capas de abstracción sin necesidad real.
- **Datos:** toda escritura multi-fila en `transaction(...)`; constraints (UNIQUE/FK) en
  la DB, no solo en código; migraciones versionadas con backup; backups pre-mutación con
  retención; índices con intención; WAL activado en `connect_db`.
- **Validación en el borde:** nunca confiar en el cliente; valores calculados siempre en
  servidor (nutrientes, RM); errores de dominio → 400 con mensaje seguro, inesperados →
  500 genérico + `logger.exception` (stack solo server-side).
- **Seguridad OWASP aplicada:** `GYM_CSRF_SECRET` obligatorio en arranques no-loopback
  (`start_server.sh` debe generarlo/persistirlo); token de sync con `compare_digest`;
  límites de cuerpo/lote; sin rutas muertas ni endpoints sin inventario conocido;
  URLs externas solo constantes (sin SSRF).
- **Observabilidad:** logs con contexto correlacionable (`request_id` cuando exista);
  health endpoint; nunca fallos silenciosos.
- **Idempotencia y resiliencia:** upsert por revisión en sync, importaciones que
  reemplazan solo `origen='google'` (con backup previo), mutaciones con backup + undo.
- **Testing:** pirámide con gates `pytest` + `ruff` + `mypy` + cobertura ≥90 %; todo
  cambio de contrato lleva su test.

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

- Mantén la identidad visual actual: fondo oscuro (`bg-matte-950`/`bg-neutral-900`), acento borgoña **`burgundy-600` / `burgundy-400`** (`#9b1b30`/`#e56d88`), toques "neón" (`neon-border`, `neon-title`). **Fuente única de verdad: `static/design-tokens.json`** (generado por `scripts/build_design_tokens.py`); si un valor visual no está ahí, no se usa.
- **Vocabulario canónico de componentes en `static/css/components.css`** (única fuente): `.btn` (`.btn-primary`, `.btn-ghost`, `.btn-outline`, `.btn-text`), `.cell-input`/`.cell-select` (celdas de tabla), `.field-input` (formularios de alta), `.panel`/`.panel-title`/`.card`. Queda **prohibido** repetir utilidades de color inline (`bg-white/[0.04]`, `bg-burgundy-700 hover:…`, `bg-matte-950 border…`), micro-tipografía (`text-[9-11px]`) y hex literales en templates/CSS. El gate `scripts/audit_consistency.py` (en CI) lo verifica; las clases que el JS/tests usan como hook se conservan como alias.
- Las gráficas Plotly usan `plot_bgcolor`/`paper_bgcolor` transparentes para integrarse con el tema oscuro.
- Respeta el patrón de fracciones de template (`exercise_detail.html`) y la gráfica única con `hx-swap-oob`.

## 7.5 Web Standards (innegociables)

Referencia completa: `docs/architecture/web-standards.md`. Principios vinculantes:

- **Server-First:** HTML servidor + htmx; JS solo como mejora progresiva. Prohibido SPAs,
  frameworks client-side o hidratación. Validación y cálculo de datos siempre en servidor.
- **Tokens como única fuente de verdad:** si un valor visual no está en `tailwind.config.js`
  o en las CSS custom properties, no se usa.
- **WCAG 2.2 AA:** contraste ≥4.5:1, navegación por teclado, focus visible, errores nunca
  solo con color, `prefers-reduced-motion`, ARIA solo sin elemento nativo.
- **Core Web Vitals:** LCP ≤2.5s, INP ≤200ms, CLS ≤0.1; swaps htmx sin layout shift.
- **Seguridad:** CSP estática sin nonce ni `'unsafe-inline'` en script-src (style-src sí lo
  requiere Plotly), CSRF + Origin en mutaciones, SQL parametrizado, secretos nunca en cliente.
- **Estados de UI siempre diseñados** (vacío/carga/error/éxito) y toda mutación con backup +
  push a la pila de undo.

## 8. Control de Calidad y Pruebas

### Flujo recomendado con OpenCode

- Usa `/refine` solo cuando la solicitud sea ambigua o tenga varias decisiones abiertas.
- Para tareas no triviales, empieza con `/plan` y revisa el plan antes de usar `/implement`.
- Usa `/review` después de implementar; el agente reviewer no tiene permiso para editar.
- Usa `/security-review` cuando el cambio toque autenticación, datos sensibles, red o Health Connect.
- Los agentes de `.opencode/agents/` son roles especializados de análisis y no sustituyen estas instrucciones.
- No se hacen commits ni pushes automáticamente; la rama y el diff deben revisarse antes de confirmar cambios.
- Las skills del proyecto complementan estas instrucciones; las reglas permanentes siguen viviendo aquí.

Antes de dar por completada una tarea, debes:

1. Sincronizar el entorno (falla si `uv.lock` está obsoleto; CI lo exige igual):
   ```bash
   uv sync --locked
   ```
2. Validar que las pruebas pasen (el piso de cobertura 90 % branch es automático vía `addopts` de `pyproject.toml`):
   ```bash
   uv run pytest                            # unidad + integración + browser (Playwright)
   uv run pytest --ignore=tests/e2e         # solo unidad/integración (aquí vive el gate de cobertura)
   uv run pytest tests/e2e -q --no-cov      # solo browser (el subproceso uvicorn no se instrumenta)
   uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py --min 90
   ```
   (Una vez por máquina: `uv run playwright install chromium` para los tests e2e.)
3. Ejecutar las puertas de calidad estáticas:
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy app.py src tests
   ```
 4. En caso de cambios visuales, recompilar Tailwind (sin CDN runtime, el CSS commiteado es el que se sirve):
    ```bash
    ./scripts/build_css.sh
    ```
    Y ejecutar la app localmente. Arranque único y estándar (genera/persiste el token
    de HealthSync en `data/hc_sync_token` y el secreto CSRF en `data/csrf_secret`;
    activa el gate LAN sync-only y expone `0.0.0.0:8000` para la app Android y el
    dashboard en el Mac — no hay otro modo de arranque para uso diario):
    ```bash
    ./scripts/start_server.sh
    ```
 5. Si agregas dependencias, actualiza `pyproject.toml` y regenera el lock:
   ```bash
   uv lock && uv sync --locked
   ```
   (`requirements.txt` se conserva solo como export de compatibilidad.)
