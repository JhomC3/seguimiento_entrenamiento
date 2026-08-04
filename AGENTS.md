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
- `app.py`: Entrada de la aplicación FastAPI (rutas del dashboard).
- `config.py`: Constantes globales, URLs de descarga y `DB_PATH`.
- `src/`: Lógica central del sistema.
  - `fetcher.py`: Extracción HTTP de Google Sheets.
  - `parser.py`: Limpieza y transformación de CSV.
  - `database.py`: Operaciones SQLite (creación de tablas y carga).
  - `metrics_engine.py`: Motor de métricas (RM ajustado, PFR, fatiga acumulada, recuperación).
  - `charts.py`: Gráficos Plotly y agregaciones de datos por ejercicio/grupo.
  - `diagnostics.py`: Diagnósticos lógicos de estancamiento/overreaching.
- `templates/`: Plantillas Jinja2 del frontend.
  - `base.html`: Layout base (estilos, htmx, Plotly).
  - `index.html`: Pantalla principal con categorías musculares y gráfica unificada.
  - `exercise_list.html`: Lista de ejercicios (parcial).
  - `exercise_detail.html`: Tabla de series/sesiones por ejercicio (parcial).
- `data/`: Contiene la base de datos local SQLite `gym.db`.
- `tests/`: Pruebas unitarias e integración.
- `assets/body_map.svg`: Mapa corporal (recurso visual).

## 4. Modelo de Datos (SQLite)
La base `data/gym.db` tiene dos tablas:

**`ejercicios`**
- `id` INTEGER PK
- `grupo_muscular` TEXT NOT NULL
- `ejercicio` TEXT NOT NULL UNIQUE

**`training_sets`**
- `id` INTEGER PK
- `semana` INTEGER NOT NULL
- `dia` TEXT NOT NULL
- `fecha` TEXT
- `set_orden` INTEGER NOT NULL
- `ejercicio` TEXT NOT NULL
- `reps` REAL
- `kg` REAL
- `rir` REAL

## 5. Arquitectura del Dashboard (FastAPI + htmx)
La app `app.py` sirve HTML renderizado con Jinja2 y usa htmx para actualizaciones parciales:

- **`GET /`** → index con categorías musculares y gráfica global (PFR sistémico).
- **`POST /sync`** → re-descarga Google Sheets, repuebla la DB y recarga.
- **`GET /select`** → lista de ejercicios del grupo (`grupo=""` para global) con gráfica OOB.
- **`GET /grupo/reset`** → actualiza la gráfica con el rendimiento del grupo (PFR del grupo muscular).
- **`GET /ejercicio`** → tablas de detalle (raw + resumen por sesión) con gráfica OOB del ejercicio.

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
  - La fatiga acumulada aplica un decaimiento exponencial diario de 0.65 entre sesiones.
  - Puedes extender `metrics_engine.py`/`diagnostics.py` para nuevas métricas, manteniendo los mismos patrones (DataFrame + filtros `systemic`/`muscle_group`/`exercise`).
- **SQL Seguro:** Usa consultas parametrizadas (`?`) en SQLite para evitar cualquier vulnerabilidad, incluso si los datos provienen de tu propia hoja.

## 7. Estética del Frontend
- Mantén la identidad visual actual: fondo oscuro (`bg-matte-950`/`bg-neutral-900`), acento borgoña **`burgundy-700` / `burgundy-400`** (`#9b1b30`/`#e56d88`), toques "neón" (`neon-border`, `neon-title`).
- Las gráficas Plotly usan `plot_bgcolor`/`paper_bgcolor` transparentes para integrarse con el tema oscuro.
- Respeta el patrón de fracciones de template (`exercise_list.html`, `exercise_detail.html`) y la gráfica única con `hx-swap-oob`.

## 8. Control de Calidad y Pruebas
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