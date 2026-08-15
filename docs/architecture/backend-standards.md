# Backend Standards — Guía Unificada de Desarrollo

> **Propósito:** Referencia única de buenas prácticas backend para este proyecto,
> sintetizada de las guías de industria (12-Factor App, Clean/Hexagonal Architecture,
> SOLID, OWASP API Security Top 10, RFC 9110, OpenAPI, pirámide de testing) y adaptada a
> la arquitectura real (FastAPI + SQLite + servicios de dominio + scripts CLI). Cualquier
> cambio en `app.py`, `src/`, migraciones o scripts debe respetar estos principios; los
> ítems de la sección 11 son la lista de verificación mínima antes de declarar una tarea
> completa. Complementa a `docs/architecture/web-standards.md` (frontend) y a
> `docs/architecture/security-model.md` (modelo de amenazas).

---

## 1. Principio rector — Monolito modular con dominio puro

La arquitectura del proyecto **es** el patrón recomendado por la industria para este
tamaño: un **monolito modular** sin microservicios, colas ni cachés (la complejidad
distribuida se añade solo cuando un problema real lo justifique — "earn the complexity").

Regla de dependencias (Clean/Hexagonal aplicada con pragmatismo):

```
app.py (handlers HTTP: parseo de request + selección de respuesta)
   ↓
src/*_service.py (casos de uso: validación de dominio, orquestación, error mapping)
   ↓
src/database.py (persistencia SQLite; única capa que conoce el esquema SQL)
   ↓
SQLite (data/lifestyle.db)
```

- Los handlers son delgados: no contienen SQL ni lógica de negocio multi-paso
  (patrón vigente: `app.py` solo parsea, llama al servicio y construye la respuesta).
- Los servicios de dominio no conocen HTTP ni templates: reciben inputs tipados
  (`TrainingSetInput`, `AlimentoInput`, `CardioAnnotationInput`) y lanzan
  `ValidationError`/`NotFoundError`/`ConflictError` (`src/models.py`).
- La capa de persistencia (`src/database.py`) es la única que ejecuta SQL; los servicios
  la usan, nunca `sqlite3` directo (excepciones puntuales con justificación: cascada de
  `_cascade_items` en `app.py`).
- Sin estado crítico en proceso: la pila de undo (`mutation_service.py`) es un límite
  conocido y documentado (se pierde al reiniciar), no una fuente de verdad.
- Prohibido introducir: microservicios, ORM pesado, colas de mensajes, framework de
  inyección de dependencias o capas de abstracción sin un problema concreto que resuelvan.

## 2. Configuración y 12-Factor App

- **Config por entorno:** `DB_PATH` (`LIFESTYLE_DB_PATH`/`GYM_DB_PATH`), `HC_SYNC_TOKEN`
  (env o `data/hc_sync_token`, gitignored), `GYM_CSRF_SECRET`, `GYM_CSRF_WINDOW_HOURS`.
  Los secretos **nunca** van en el código ni en git.
- `GYM_CSRF_SECRET` **obligatorio** en cualquier despliegue que no sea loopback; el
  fallback de desarrollo (`security.py:54`) solo es aceptable en `127.0.0.1`. El arranque
  oficial (`scripts/start_server.sh`, expone `0.0.0.0` para la app Android) debe generar
  y persistir el secreto igual que hace con `hc_sync_token`.
- **Procesos admin separados:** las importaciones de Google Sheets son scripts CLI
  (`scripts/import_google_sheets.py`, `scripts/import_nutrition.py`), no rutas HTTP.
- Constantes de dominio (ciclo, hoja de cálculo, categorías) viven en `config.py` como
  configuración declarativa; si una cambia con el entorno, pasa a env.
- **Disposability:** los handlers son `def` síncronos en threadpool; no se bloquea el
  event loop ni se introduce I/O asíncrono innecesario.

## 3. API y contratos

- **Semántica HTTP (RFC 9110):** `GET` nunca muta; mutaciones solo `POST` (htmx y JSON).
  Status codes correctos: `200` éxito, `400` error de dominio/validación, `401` token de
  sync inválido, `403` CSRF, `404` recurso inexistente, `409` conflicto (duplicados),
  `413` lote excesivo, `500` inesperado, `503` endpoint no configurado.
- **Error contract:** los errores de dominio devuelven mensajes seguros y en español
  (visible al usuario vía notices htmx); las excepciones inesperadas **nunca** revelan
  detalles internos (log servidor + mensaje genérico). El contrato JSON del sync usa
  `{"detail": ...}`; no se introduce un formato nuevo sin documentarlo en
  `docs/architecture/health-sync-contract.md`.
- **OpenAPI:** las rutas de documentación (`/openapi.json`, `/docs`, `/redoc`) están
  **deshabilitadas por decisión** (sin consumidores externos de API; OWASP API9). El
  contrato real vive en `docs/architecture/current-ui-contract.md` (UI) y
  `docs/architecture/health-sync-contract.md` (sync). El inventario de rutas debe ser
  conocido e intencional; cualquier endpoint nuevo requiere su test y su entrada en
  el contrato.
- **Inventario de rutas:** toda ruta muerta (no referenciada por templates/JS/android)
  se elimina en la misma iteración que la deja obsoleta. No acumular endpoints legacy.
- **Paginación:** aplicar offset/limit solo cuando la vista lo requiera y el volumen lo
  justifique; documentar el contrato (el catálogo local no necesita keyset pagination).
- **Idempotencia:** las mutaciones que reemplazan un agregado completo (sesión por
  fecha, diario por fecha) son idempotentes por construcción; la ingesta de Health
  Connect usa upsert condicionado por revisión (`last_modified_epoch_ms`) con acuse
  individual por `hc_id`. Mantener esas propiedades; no añadir campos que las rompan.

## 4. Datos y persistencia

- **Integridad en la base de datos, no solo en el código:** `UNIQUE` (ejercicios,
  plantillas, alimentos), FKs con `ON DELETE CASCADE` (plantilla_sets), PKs naturales
  donde existen (`hc_id`, `parametros_diarios.fecha`). Toda nueva tabla los declara en
  su migración.
- **Transacciones ACID:** toda escritura multi-fila usa `src/db_connection.transaction`
  (delete+insert de sesión, diario, plantillas, restauraciones de undo). Una escritura
  sin transacción es un bug.
- **Migraciones versionadas** (`src/migrations/vNNN_*.py` + `runner.py`): transaccionales,
  con backup automático antes de aplicar pendientes, registradas en `schema_migrations`.
  Nunca `ALTER TABLE` a mano ni cambios de esquema fuera de una migración.
- **Backups:** antes de toda mutación destructiva (`backup_or_raise`) con retención
  (`prune_backups`, 30 copias). Un backup que falla bloquea la escritura.
- **Índices con intención:** crear índices para las consultas frecuentes por clave/rango
  (fecha, semana, ejercicio, record_type); **medir antes de indexar** (el volumen actual
  es pequeño); los filtros con funciones (`LOWER(col)`) no usan índice — considerar
  índices de expresión si la consulta lo merece.
- **WAL:** SQLite debe operar en `journal_mode=WAL` (lecturas concurrentes sin bloquear
  escrituras) con `busy_timeout` (ya 5 s) y `foreign_keys=ON` por conexión.
- **UPSERT:** preferir `INSERT ... ON CONFLICT DO UPDATE` sobre `INSERT OR REPLACE`
  (que borra y reinserta la fila, cambiando rowid y rompiendo FKs si aparecieran).
- **Volumen:** las lecturas vía `pandas.read_sql_query` (gráficas, métricas) cargan
  tablas completas en memoria: mantener el contrato de datos acotado y documentar el
  límite operativo (una hoja personal no escala a millones de filas).

## 5. Validación en el borde

- **Nunca confiar en el cliente:** el servidor valida tipo, formato, rango y relaciones
  en los servicios de dominio (`validate_sets`, `_positive_float`, `parse_form_date`,
  `entries_from_form`) antes de tocar la base de datos.
- Los valores calculados se **recalculan en servidor** contra la fuente autoritativa
  (nutrientes desde el catálogo con `ROUND_HALF_UP(catálogo_100g × g / 100)`; RM desde
  kg/reps/rir); el cliente solo previsualiza.
- Los arrays paralelos del formulario (`ejercicio[]`, `kg[]`, ...) se normalizan y
  validan con el mismo número de elementos; filas vacías se omiten, filas parciales
  fallan.
- La ingesta externa (`/sync/health-connect`) valida estructura y semántica de **todo el
  lote** antes de persistir (400 atómico; rechazos por política se acusan individualmente
  con `reason`).
- No duplicar la misma validación en varias capas: una sola fuente de reglas por caso de
  uso (servicio de dominio), con excepciones documentadas (gating client-side es UX, no
  seguridad).

## 6. Seguridad OWASP API aplicada

Checklist operativo del OWASP API Security Top 10 adaptado a esta app (loopback + sync
Android):

- **AuthN del sync:** `X-Sync-Token` comparado con `hmac.compare_digest`; sin env →
  503. No existe autenticación de usuarios (modelo documentado en `security-model.md`);
  cualquier exposición a red exige revisar ese modelo.
- **BOLA / función:** sin multi-usuario; la autorización se limita al token estático del
  sync — no mezclar credenciales.
- **Resource consumption:** límites de cuerpo (1 MiB) y lote (500 ops) en la ingesta;
  **rate limiting** pendiente de diseñar si el endpoint deja el loopback (mitigación
  actual: token secreto + límites de tamaño).
- **SSRF:** las únicas URLs externas son constantes de `config.py` (Google Sheets);
  ninguna deriva de input del usuario. Mantener esa invariante.
- **Validation:** Pydantic-idiom no usado; la validación manual tipada es el patrón
  (ver §5). Todo input llega validado al dominio.
- **Security misconfiguration:** CSP/headers/CSRF en `src/security.py` (ver
  `web-standards.md` §5 y `security-model.md`); `GYM_CSRF_SECRET` fuera del fallback de
  desarrollo en cualquier arranque no-loopback; `start_server.sh` sin secret → abortar.
- **Inventory:** rutas muertas se eliminan (§3); `/docs`/`/redoc`/`/openapi.json`
  deshabilitados (decisión explícita); liveness en `/healthz`.
- **Secrets:** nunca en git (`.gitignore` cubre `data/hc_sync_token`, `.env` si existiera);
  el token HC viaja solo al servidor (server-side) y a la app Android (Keystore/DataStore).
- **Dependencias:** `uv.lock` como fuente de verdad; `uv sync --locked` en CI.

## 7. Observabilidad

Si no se puede medir, no se puede operar:

- **Logs estructurados:** los módulos de `src/` ya usan `logging.getLogger(...)`
  (`security`, `dashboard`, `mutations`, `health_sync`); mantener ese patrón y emitir
  contexto útil (path, ruta, resultado) en `logger.warning`/`logger.exception`. Todo
  error inesperado se registra con stack (`logger.exception`), nunca silenciado.
- **`request_id`:** implementado vía `RequestIdMiddleware` (`app.py`, el add_middleware
  más externo): genera `uuid4().hex[:12]` por petición, lo propaga con
  `contextvars` (`src/logging_setup.py`) a todos los logs (`[request_id]` en el
  formatter) y lo expone en el header `x-request-id` de toda respuesta (incluidos los
  403/429 de middlewares internos). Emite un access log propio con método, path,
  status y duración.
- **Health check:** `GET /healthz` (liveness): `{"status": "ok", "db": "ok"}` con `SELECT 1`
  contra la DB; 503 si no responde (nunca detalles internos en la respuesta).
- **Métricas:** sin necesidad de Prometheus/Grafana en este tamaño; la telemetría mínima
  es: uvicorn access log (RPS/status/latencia) + logs de error con stack. Si se añade
  instrumentación, preferir percentiles (p95/p99) sobre promedios.
- **Errores:** los 500 nunca exponen traza al cliente (ya: `translate_error` → mensaje
  genérico); el detalle vive solo en el log del servidor.

## 8. Resiliencia e idempotencia

- **Backups antes de mutaciones** (`backup_or_raise`): un backup fallido bloquea la
  escritura (mejor error visible que pérdida silenciosa).
- **Undo:** pila en memoria (máx. 10) con restauración transaccional; el pop solo ocurre
  tras restaurar con éxito. Límite conocido: se pierde al reiniciar el servidor.
- **Ingesta Health Connect:** idempotente por `hc_id` + revisión (upsert condicionado),
  baja lógica (`deleted_at`) para auditoría, acuse individual. No romper estas
  propiedades.
- **Fetcher (Google Sheets):** timeout explícito (`requests.get(..., timeout=30)`);
  ante fallo de red, reintento manual del script (no reintentos automáticos agresivos).
- **Importaciones:** la importación de alimentación es idempotente (backup previo,
  reemplaza solo `origen='google'`); la de entrenamiento debe alcanzar el mismo
  contrato (re-ejecución sin duplicar series) antes de considerarse segura.
- **Límites de input:** formularios y JSON con límites de tamaño/longitud donde el
  abuso local sea plausible (lotes, arrays, textos).

## 9. Testing y CI

- **Pirámide:** unitarios (servicios/dominio) > integración (DB real temporal) > e2e
  (Playwright con servidor aislado). La cobertura ≥90% (gate `--cov-fail-under=90` +
  por módulo para charts/metrics) es un piso, no el objetivo: **un test de
  comportamiento vale más que líneas cubiertas**.
- **Puertas obligatorias** (idénticas a `AGENTS.md` §8): `uv run pytest`,
  `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app.py src tests`.
- **CI** (`.github/workflows/ci.yml`): jobs `quality` (lint+tipos+lock), `unit`
  (cobertura), `browser` (e2e aislado). Cualquier cambio de contrato UI o de sync lleva
  su test de browser asociado.
- Casos borde obligatorios: fechas inválidas, arrays paralelos desalineados, NaN/Inf en
  números, duplicados (case-insensitive), lotes vacíos/excesivos, revisiones obsoletas,
  CSRF/Origin hostiles, payloads hostiles (XSS en nombres).

## 10. Documentación y ADRs

- Las decisiones de arquitectura se registran: `docs/architecture/*` (contratos y modelo
  de seguridad), `docs/plans/*` (planes con justificación y archivo), `docs/operations/*`
  (runbooks: arranque, release, migraciones). Ante una decisión relevante sin registro,
  crear o actualizar el documento correspondiente en la misma iteración.
- Contratos vigentes: `current-ui-contract.md` (DOM/htmx), `health-sync-contract.md`
  (ingesta JSON), `security-model.md` (amenazas y controles). Cambiar un contrato sin
  actualizar su documento es un defecto.
- `AGENTS.md` debe reflejar el estado real (migraciones, rutas, catálogos): el drift
  documental se corrige en la iteración que lo detecta.

## 11. Checklist mínimo (antes de dar una tarea por completa)

- [ ] Nueva lógica en servicios de dominio (no en handlers); inputs tipados; sin SQL
      fuera de `src/database.py`.
- [ ] Toda escritura multi-fila dentro de `transaction(...)`; constraints declaradas en
      la migración (UNIQUE/FK/NOT NULL).
- [ ] Validación de borde completa (tipo/formato/rango/relaciones) con mensajes seguros
      en español; valores calculados recalculados en servidor.
- [ ] Mutaciones con backup (`backup_or_raise`) + push a la pila de undo (o
      justificación explícita de exclusión).
- [ ] Sin secretos en código ni logs; `GYM_CSRF_SECRET` no-loopback cubierto.
- [ ] Rutas: sin endpoints muertos; semántica HTTP correcta; cambios de contrato
      documentados (OpenAPI/contracts).
- [ ] Errores inesperados con `logger.exception` (stack server-side) y mensaje genérico
      al cliente.
- [ ] Logs con contexto correlacionable (request_id cuando exista); sin logging
      silencioso de fallos.
- [ ] Tests: unitario o integración para la nueva lógica; e2e si cambia contrato;
      `pytest` + `ruff` + `mypy` en verde.
- [ ] `AGENTS.md`/docs actualizados si el cambio afecta migraciones, rutas o contratos.
