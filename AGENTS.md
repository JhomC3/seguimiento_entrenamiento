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
  - `requests` (Importación única de Google Sheets)
  - `pytest` (Testing)
- **Frontend:** HTML + **htmx** (AJAX incremental y actualización OOB) + CSS (Tailwind, vía CDN).
- El proyecto también incluye un `run-agent.sh` + `litellm_config.yaml` para levantar un proxy LiteLLM y ejecutar este agente con modelos Gemini. No es parte del dashboard en sí.

## 3. Arquitectura de Datos: SQLite como Única Fuente de Verdad
- **SQLite (`data/gym.db`) es la única fuente de verdad.** El dashboard lee y escribe exclusivamente en SQLite.
- Google Sheets **no** forma parte del runtime. Solo se usa para una **importación única** opcional:
  ```bash
  uv run python scripts/import_google_sheets.py
  ```
  El script reemplaza en una sola transacción las filas `origen='google'` y nunca toca las `origen='manual'`.
- El sync manual (`POST /sync`) fue eliminado del dashboard. No reintroducir sincronización automática con Google Sheets.

## 4. Estructura de Directorios Clave
- `app.py`: Entrada de la aplicación FastAPI (rutas del dashboard).
- `config.py`: Constantes globales (`DB_PATH`, `CICLO_START`, categorías musculares).
- `scripts/import_google_sheets.py`: Importación única desde Google Sheets.
- `src/`: Lógica central del sistema.
  - `fetcher.py` + `parser.py`: Solo usados por el script de importación.
  - `database.py`: Operaciones SQLite (init no destructivo, migraciones, queries).
  - `training_service.py`: Lógica de negocio (semana por calendario, validación, inserción/edición de sesiones).
  - `metrics_engine.py`: Motor de métricas (RM ajustado, PFR, rendimiento relativo).
  - `charts.py`: Gráficos Plotly y agregaciones de datos por ejercicio/grupo.
- `templates/`: Plantillas Jinja2 del frontend.
  - `base.html`: Layout base (estilos, htmx, Plotly).
  - `index.html`: Pantalla principal (sidebar con categorías/ejercicios, navegador de fechas, editor de sesión, gráfica).
  - `date_navigator.html`: Navegador horizontal de fechas (con marcador de días con datos).
  - `session_editor.html`: Editor de la sesión del día seleccionado (lectura/edición según fecha).
  - `exercise_create_form.html`: Alta de ejercicios nuevos en el sidebar (parcial).
  - `exercise_list.html` / `exercise_detail.html`: Navegación por ejercicio (parciales).
- `data/`: Contiene `gym.db` y `data/backups/` (copias automáticas antes de operaciones destructivas).
- `tests/`: Pruebas unitarias e integración.
- `assets/body_map.svg`: Mapa corporal (recurso visual).

## 5. Modelo de Datos (SQLite)
La base `data/gym.db` tiene dos tablas:

**`ejercicios`**
- `id` INTEGER PK
- `grupo_muscular` TEXT NOT NULL
- `ejercicio` TEXT NOT NULL UNIQUE
- `categoria` TEXT (EMPUJE / TIRON / PIERNA / CORE)
- `origen` TEXT NOT NULL DEFAULT 'google' ('google' | 'manual')

**`training_sets`**
- `id` INTEGER PK
- `semana` INTEGER NOT NULL
- `dia` TEXT NOT NULL
- `fecha` TEXT (formato `d/m/yy`)
- `set_orden` INTEGER NOT NULL
- `ejercicio` TEXT NOT NULL
- `reps` REAL
- `kg` REAL
- `rir` REAL
- `origen` TEXT NOT NULL DEFAULT 'google' ('google' | 'manual')

**Migración:** `init_db()` es no destructivo: crea tablas/índices si faltan, hace `ALTER TABLE ADD COLUMN` para columnas nuevas y hace backfill de `categoria` desde `MUSCLE_CATEGORIES`. Nunca borra datos.

## 6. Semana por Calendario
- La semana de un entrenamiento manual se calcula contra el inicio del ciclo (`CICLO_START` en `config.py`, por defecto `10/02/2026`):
  ```python
  semana = max(1, (fecha - ciclo_inicio).days // 7 + 1)
  ```
- `10/02/2026` → semana 1. `18/02/2026` → semana 2. Fechas previas al ciclo → semana 1.
- El formulario muestra la fecha actual por defecto, con `<input type="date">` (calendario y escritura manual).

## 7. Arquitectura del Dashboard (FastAPI + htmx)
La app `app.py` sirve HTML renderizado con Jinja2 y usa htmx para actualizaciones parciales:

- **`GET /`** → index con sidebar (categorías/ejercicios/nuevo ejercicio), navegador de fechas, editor de sesión del día y gráfica global (PFR sistémico).
- **`GET /fecha`** → navegador de fechas + editor de sesión para la fecha indicada (respuesta OOB). Fechas pasadas = solo lectura con botón ✏️; hoy/futuro = editable.
- **`POST /entrenamiento/session/save`** → reemplaza en una transacción todas las series de la fecha (vacío = borra la sesión). Hace backup previo en `data/backups/`.
- **`POST /ejercicio/nuevo`** → alta de ejercicio con grupo muscular y categoría (rechaza duplicados).
- **`GET /exportar/csv`** → exporta `training_sets` a CSV.
- **`GET /select`** → lista de ejercicios del grupo (`grupo=""` para global) con gráfica OOB.
- **`GET /grupo/reset`** → actualiza la gráfica con el rendimiento del grupo (PFR del grupo muscular).
- **`GET /ejercicio`** → tablas de detalle (raw + resumen por sesión) con gráfica OOB del ejercicio.

**Flujo frontend (en `index.html`):**
1. El sidebar contiene: formulario de nuevo ejercicio, categorías musculares con sus músculos, y la lista de ejercicios del grupo seleccionado (cargada vía `/select`).
2. El navegador `#date-navigator` muestra la fecha seleccionada, ~13 días hacia atrás y máximo 2 hacia adelante; scroll horizontal, flechas y un `<input type="date">` permiten ir a cualquier fecha. Los días con entrenamiento muestran un punto de marcador.
3. `#session-editor` muestra la tabla compacta `# | Ejercicio | Peso | Reps | RIR | RMₐ` de la fecha seleccionada. Hoy/futuro: filas editables por defecto (lápiz encendido). Pasado: solo lectura con lápiz apagado que activa edición. Al desplegar el selector de ejercicio, el seleccionado aparece primero.
4. Seleccionar un ejercicio carga `exercise_detail.html` en `#history-section` y actualiza la gráfica unificada.

## 8. Reglas de Codificación (Coding Standards)
- **Tipado Estricto:** Usa anotaciones de tipo (Type Hints) en todas las firmas de funciones en `src/`.
- **Manejo de Errores:** Nunca uses excepciones genéricas (`except:`). Captura errores específicos y regístralos o elévalos adecuadamente. En `app.py`, las funciones auxiliares de lectura DB (`get_db_status`, `get_filters`, etc.) usan `try/except Exception` y devuelven valores seguros.
- **Validación de datos manuales:** centralizada en `src/training_service.py` (`validate_sets`). Kg/reps positivos, RIR opcional no negativo, ejercicio debe existir en catálogo. Inserción siempre transaccional.
- **Estructura del Parser (solo importación):**
  - La hoja `ciclo_16` tiene columnas repetitivas por semana (Ejercicio, Reps, Kg, RIR). El parser debe procesarlas de forma iterativa y limpia.
  - Los datos faltantes (campos vacíos) deben ser mapeados a `None` o `float('nan')` en Pandas, y guardarse como `NULL` en SQLite.
- **Motor de Métricas:**
  - `RM ajustado = kg * (1 + 0.0333 * (reps + 1 + rir))`.
  - El rendimiento relativo (%) se calcula contra el baseline (promedio RM de la primera semana del ejercicio).
  - Puedes extender `metrics_engine.py` para nuevas métricas, manteniendo los mismos patrones (DataFrame + filtros `systemic`/`muscle_group`/`exercise`).
- **SQL Seguro:** Usa consultas parametrizadas (`?`) en SQLite para evitar cualquier vulnerabilidad, incluso si los datos provienen de tu propia hoja.

## 9. Estética del Frontend
- Mantén la identidad visual actual: fondo oscuro (`bg-matte-950`/`bg-neutral-900`), acento borgoña **`burgundy-700` / `burgundy-400`** (`#9b1b30`/`#e56d88`), toques "neón" (`neon-border`, `neon-title`).
- Las gráficas Plotly usan `plot_bgcolor`/`paper_bgcolor` transparentes para integrarse con el tema oscuro.
- Respeta el patrón de fracciones de template y la actualización vía `hx-swap-oob`.

## 10. Control de Calidad y Pruebas
Antes de dar por completada una tarea, debes:
1. Validar que las pruebas pasen ejecutando:
   ```bash
   uv run pytest
   ```
2. Ejecutar la app localmente para verificar la interfaz en caso de cambios visuales:
   ```bash
   uv run uvicorn app:app --reload
   ```
3. Si agregas dependencias, actualiza siempre el archivo `requirements.txt`.