# Instrucciones del Agente - Gym Tracker Dashboard

## 0. Máxima del Sandbox (obligatoria, permanente)

1. **Todo dentro del directorio del proyecto.** Ningún archivo temporal, log, backup o artefacto puede crearse fuera del directorio de trabajo. Prohibido escribir en `/tmp`, `/var/folders`, `~/Library` u otras rutas del sistema.
2. **Siempre el entorno virtual** `.venv` del proyecto (`uv run ...`). Nada se ejecuta con el Python/uv global del sistema.
3. **Nada sale del sandbox**: no instalar paquetes globales, no lanzar procesos que escriban fuera del proyecto, no usar rutas absolutas externas.
4. Si un comando/script necesita un directorio temporal, crear `.tmp/` dentro del proyecto y limpiarlo al terminar.
5. Esta máxima aplica a cualquier tarea y herramienta, sin excepciones.

## 0.5. Máxima de Git y Worktrees (obligatoria, permanente)

1. **Una tarea = una rama = un worktree dentro del proyecto.** Cada agente o tarea trabaja en su propio
   directorio (`git worktree` en `.tmp/entrenamiento-<tarea>`, siempre dentro del proyecto, nunca fuera
   de él — la máxima §0 prevalece sobre cualquier ejemplo de ruta en `docs/`) con su propia rama.
   **Prohibido** que dos agentes o dos tareas compartan el mismo directorio de trabajo.
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
   el worktree (`git worktree remove .tmp/entrenamiento-<tarea>`) y poda (`git worktree prune`), y borra las
   ramas ya integradas.
5. Esta máxima aplica a cualquier tarea, agente y herramienta, sin excepciones.
   Procedimiento operativo: `docs/operations/local-development.md` § "Parallel work".

## 1. Identidad y Rol

Mantén, optimiza y extiende el dashboard de progresión de gimnasio (FastAPI + SQLite + htmx). Detalle técnico en §2-§7; reglas de proceso en §8-§9.

## 2. Tech Stack y Entorno

- **Lenguaje:** Python 3.11+ con type hints en toda firma de `src/`. **`uv`** obligatorio: dependencias solo vía `pyproject.toml` + `uv lock && uv sync --locked` (`requirements.txt` es export, no se edita). Ejecuta con `uv run <comando>`.
- **Librerías:** `fastapi` + `uvicorn`, `jinja2`, `pandas`, `plotly`, `requests`, `pytest`.
- **Frontend:** HTML + **htmx** + **Tailwind compilado** (sin CDN): `scripts/build_css.sh` compila `static/css/input.css` → `static/css/tailwind.css` (commiteado). Tras tocar clases, recompila o no se verá.
- **Android** (app HealthSync, Kotlin): Gradle SIEMPRE desde `android/` con `GRADLE_USER_HOME=$PWD/.gradle` y `ANDROID_HOME=$PWD/android/sdk`; `JAVA_HOME=/opt/homebrew/opt/openjdk@21`.

## 3. Mapa del repo (leer primero según el área)

| Área | Leer primero |
|---|---|
| Entrada HTTP / rutas | `app.py` + contratos en §5 |
| Dominio y validación | `src/training_service.py`, `src/nutrition_service.py`, `src/models.py` |
| Persistencia y esquema | `src/database.py`, `src/db_connection.py`, `src/migrations/` + §4 |
| Métricas y gráficas | `src/metrics_engine.py`, `src/charts.py` |
| Sync / seguridad / red | `src/health_sync_service.py`, `src/security.py`, `src/network_access.py` |
| Mutaciones y undo | `src/mutation_service.py`, `src/backup_utils.py` |
| UI (templates/JS/CSS) | `templates/`, `static/js/app.js`, `static/css/components.css` + §7 |
| Tests | `tests/` (unitarias, integración, `e2e/` Playwright) |
| Operación local | `docs/operations/local-development.md` |
| SDD (proceso) | `docs/constitution.md`, `docs/sdd/SDD_BOOTSTRAP.md`, `specs/` |

## 4. Datos (trampas, no el schema completo)

- El esquema vive en `src/migrations/` (v001..v021, **no existe `v004`**; v021 `breathing_sessions` del pacer móvil). Prohibido `ALTER TABLE` a mano; la app aplica pendientes al arrancar con backup previo.
- `DB_PATH` vía `LIFESTYLE_DB_PATH` (`GYM_DB_PATH` es alias). `HC_SYNC_TOKEN`: env o `data/hc_sync_token` (gitignored, lo genera `scripts/start_server.sh`).
- `origen`: `'google'` (imports, reemplazable) vs `'manual'` (UI). Los imports reemplazan solo `origen='google'` con backup previo.
- Series HIIT: `velocidad_kmh`/`dificultad` solo en HIIT. Fechas siempre ISO `YYYY-MM-DD`.
- Tablas: `ejercicios`, `training_sets`, `plantillas`, `plantilla_sets`, `alimentos`, `diario_alimentacion`, `parametros_diarios`, `health_records`, `cardio_annotations`, `training_splits`, `training_split_items`, `undo_entries`, `schema_migrations`.

## 5. Arquitectura (esencia + contratos)

- Monolito modular: handlers delgados en `app.py` (`def` síncronos) → servicios de dominio tipados → `src/database.py` (**único SQL**). Sin lógica de negocio en `app.py`.
- Handlers: parseo + servicio + respuesta. Dominio: `ValidationError`/`NotFoundError`/`ConflictError` → 400 seguro; inesperado → 500 genérico + `logger.exception`.
- Mutaciones exigen CSRF (`X-CSRF-Token` de `#app-config`) + Origin mismo sitio; exención solo por igualdad exacta de ruta. Importación Sheets = scripts CLI, nunca ruta HTTP.
- Gate LAN (`GYM_LAN_SYNC_ONLY=1`): remoto solo allow-list exacta en `src/network_access.py`, resto 403/429.

| Contrato | Documento |
|---|---|
| UI/htmx (cascada, gráfica única, OOB) | `docs/architecture/current-ui-contract.md` |
| Sync Health Connect JSON | `docs/architecture/health-sync-contract.md` |
| API v1 diario móvil | `docs/architecture/training-api-contract.md` |
| Amenazas y controles | `docs/architecture/security-model.md` |

## 5.5 Backend Standards (esencia)

Detalle: `docs/architecture/backend-standards.md`. Innegociables: `transaction(...)` en escrituras multi-fila; constraints en la migración; validación en el borde y recálculo en servidor (nutrientes `ROUND_HALF_UP`, RM); `compare_digest` en sync + límites de lote/cuerpo; URLs externas solo constantes de `config.py`; logs con `request_id`, nunca fallos silenciosos; undo máx. 10.

## 6. Codificación (esencia)

- Type hints siempre; nunca `except:` genérico (en `app.py`, auxiliares de lectura devuelven valores seguros).
- Parser (`src/parser.py`): hoja `ciclo_16` iterativa; vacíos → `None`/`NaN` → `NULL`.
- Métricas (`src/metrics_engine.py`): `RM = kg * (1 + 0.0333 * (reps + 1 + rir))`, relativo vs promedio RM de semana 1.
- SQL siempre parametrizado (`?`).

## 7. Frontend (esencia)

- Server-first + htmx; sin SPAs ni hidratación; sin handlers inline (`data-action` + delegación).
- Tokens (`static/design-tokens.json` + `tailwind.config.js`) como única verdad visual; vocabulario en `static/css/components.css` (gate `scripts/audit_consistency.py` en CI: prohibido color/micro-tipografía inline y hex literales).
- WCAG 2.2 AA, Core Web Vitals (LCP ≤2.5s, INP ≤200ms, CLS ≤0.1), CSP estática, estados vacío/carga/error/éxito, toda mutación con backup + undo. Detalle: `docs/architecture/web-standards.md`.

## 8. Control de Calidad y Pruebas

- No hay commits ni pushes automáticos; rama y diff se revisan antes de confirmar.
- Gates (en este orden):
  ```bash
  uv sync --locked
  uv run pytest --ignore=tests/e2e   # cobertura ramas ≥90 % (addopts pyproject)
  uv run pytest tests/e2e -q --no-cov
  uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py --min 90
  uv run ruff format --check . && uv run ruff check .
  uv run mypy app.py src tests
  ```
  (Una vez por máquina: `uv run playwright install chromium`.)
- Cambios visuales: `./scripts/build_css.sh` + arranque único `./scripts/start_server.sh` (puerto 8000, genera secretos). Dependencias nuevas: `uv lock && uv sync --locked`.

## 9. SDD (Spec-Driven Development)

- Lee `docs/constitution.md` y la spec activa en `specs/` antes de tocar código.
- Flujo: Constitución → Spec (EARS) → Clarificación → Plan → Tareas → Implementación (una tarea cada vez, tests primero) → Validación (RF × test).
- Ningún comportamiento se implementa si no está en la spec activa; todo cambio empieza actualizando la spec y mostrando su diff.
- La línea base vive en `specs/000-sdd-bootstrap/`; cada funcionalidad nueva usa `specs/NNN-<nombre>/spec|plan|tasks.md`.
- Kit portable en `docs/sdd/` (protocolo, plantillas, prompts, skill de entrevista): úsalo para no improvisar el proceso.
- Deber de criterio propio: no obedezcas a ciegas. El dueño decide el problema, tú el juicio técnico. Bloqueante (constitución, inviabilidad, pérdida de datos, inseguridad) = detenerse y exigir resolución. Advertencia/sugerencia = alternativa con trade-offs + confirmación explícita. Si el dueño confirma seguir contra tu recomendación, obedece y regístralo en la spec como decisión consciente contra recomendación.
