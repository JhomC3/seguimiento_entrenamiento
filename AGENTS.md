# Instrucciones del Agente - Gym Tracker Dashboard

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
- `config.py`: Constantes globales, URLs de descarga y `DB_PATH` (configurable vía `GYM_DB_PATH`).
- `src/`: Lógica central del sistema.
  - `db_connection.py`: Fábrica `connect_db` (foreign_keys ON, row_factory, busy_timeout) + context managers `read_connection` / `transaction`.
  - `migrations/`: Migraciones versionadas (`v001`..`v003`) y `runner.py` (transaccionales, con backup automático antes de aplicar migraciones pendientes).
  - `models.py`: Modelos tipados (`TrainingSetInput`, `TrainingSet`, `Session`, `TemplateInput`, `Template`) y excepciones de dominio (`ValidationError`, `NotFoundError`, `ConflictError`).
  - `dashboard_service.py`: Orquestación de vistas (view models, charts, filtros) y traducción de errores a respuestas seguras.
  - `view_models.py`: `DateNavigatorViewModel`, `SessionEditorViewModel` — solo valores que necesitan las plantillas.
  - `security.py`: Middleware de headers de seguridad + CSP y protección CSRF (token firmado + validación de Origin).
  - `fetcher.py`: Extracción HTTP de Google Sheets.
  - `parser.py`: Limpieza y transformación de CSV.
  - `database.py`: Operaciones SQLite (lecturas/escrituras) usando `src/db_connection`.
  - `training_service.py` / `template_service.py`: Servicios de dominio tipados (validación, sesiones, plantillas).
  - `metrics_engine.py`: Motor de métricas (RM ajustado, PFR, rendimiento relativo).
  - `charts.py`: Gráficos Plotly y agregaciones de datos por ejercicio/grupo.
- `static/`: Assets por responsabilidad.
  - `css/`: `app.css` (manifest de @import) + `theme`, `components`, `date-navigator`, `session-editor`, `templates`.
  - `js/`: Módulos ES (`state`, `notices`, `editor`, `row-sortable`, `templates`, `date-navigation`, `htmx-lifecycle`) + bootstrap `app.js` (lee `#app-config` JSON, expone el bridge de handlers inline, inicializa el DOM).
- `templates/`: Plantillas Jinja2 del frontend.
  - `base.html`: Shell de layout (~70 líneas: metadata, CDNs, Tailwind config, partials, `{% block content %}`).
  - `partials/`: `notices.html`, `confirm_modal.html`, `app_config.html`.
  - `index.html`: Pantalla principal con categorías musculares y gráfica unificada.
  - Fragmentos por feature: `session_editor.html`, `date_navigator.html`, `plantillas_list.html`, `exercise_list.html`, `exercise_detail.html`, `exercise_create_form.html`.
- `data/`: Contiene la base de datos local SQLite `gym.db` (regenerable) y `backups/`.
- `tests/`: Pruebas unitarias, integración y `e2e/` (Playwright, servidor aislado + DB temporal).
- `docs/`: Arquitectura (`current-ui-contract.md`, `security-model.md`), operaciones (`local-development.md`, `release-checklist.md`), planes.
- `scripts/`: `import_google_sheets.py` (carga del CSV), `verify_editor.py` (chequeo del editor).
- `assets/body_map.svg`: Mapa corporal (recurso visual).

## 4. Modelo de Datos (SQLite)

La base `data/gym.db` tiene las tablas `ejercicios`, `training_sets`, `plantillas`,
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

## 5. Arquitectura del Dashboard (FastAPI + htmx)

La app `app.py` sirve HTML renderizado con Jinja2 y usa htmx para actualizaciones parciales:

- **`GET /`** → index con categorías musculares y gráfica global (PFR sistémico). Incluye `#app-config` (JSON con `categoria_map` y `csrf_token`).
- **`GET /fecha/editor?fecha=`** → fragmento del editor de sesión.
- **`POST /entrenamiento/session/save`** y **`POST /entrenamiento/session/eliminar`** → mutaciones OOB (`#editor-notice`, `#save-outcome`, `#session-editor-wrap`, `#editor-state`).
- **`POST /ejercicio/nuevo`** → crea ejercicio desde el UI (OOB `#notice-container`, `#exercise-create`).
- **`GET /plantillas` / `POST /plantilla/guardar|editar|eliminar|reordenar` / `GET /plantilla/aplicar/{id}`** → CRUD y drag&drop de plantillas (OOB `#plantillas-section`, `#session-editor-wrap`).
- **`POST /undo`** → deshace la última acción (pila en memoria, máx. 10).
- **`GET /exportar/csv`** → descarga CSV de `training_sets`.
- **`GET /select`** → lista de ejercicios del grupo (`grupo=""` para global) con gráfica OOB.
- **`GET /grupo/reset`** → actualiza la gráfica con el rendimiento del grupo (PFR del grupo muscular).
- **`GET /ejercicio`** → tablas de detalle (raw + resumen por sesión) con gráfica OOB del ejercicio.
- La importación de Google Sheets **no es una ruta HTTP**: se ejecuta con `python scripts/import_google_sheets.py`.
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
