# Spec 009 — Partir `app.py` con APIRouters sin cambio de conducta

Constitución: `docs/constitution.md` (principios 1, 2, 6).
Plan de etapa: `/Users/jhomc/.opencode/plan/refactors-006-009.md`.

## Contexto y objetivo

`app.py` tiene 2758 líneas de código (tope: 500 aviso / 800 bloqueo) con
68 rutas. Es el hub: va último (006–008 lo permiten). Partirlo con el patrón
estándar FastAPI APIRouter por área: `app.py` queda como raíz de composición
(app, lifespan, middleware, exception handler, healthz, exports, includes).
Cero cambios de conducta: mismas rutas, mismos paths, mismos contratos.

Línea base remedida (2026-09-25): app 2758 (2440 en funciones).

## Usuarios

Cualquier agente que toque HTTP; ningún cambio visible para el dueño.
Los tests solo usan `appmod.app` y `appmod.templates`: ambos se conservan.

## Requisitos funcionales (criterios de aceptación en EARS)

- RF-1: CUANDO un cliente llame a cualquier ruta actual, EL SISTEMA responderá idéntico path × método × contrato (los routers no usan prefijos; los paths se copian byte a byte). Excepción registrada (precedente 006): 221 parches de tests pinchaban `DB_PATH`/`HC_SYNC_TOKEN`/`MAX_BODY_BYTES` en el namespace de `app`; se retargetean al módulo lector (`src.web_context` / `src.http_shared` / `src.routes.api_session`) y las rutas leen `DB_PATH` por atributo de módulo. Lo afirmado no cambia.
- RF-2: EL SISTEMA ubicará cada ruta en su router por área:
  - `src/routes/ui_daily.py`: índice, diario, cardio UI (~225).
  - `src/routes/ui_food.py`: sesión entreno, alimentación UI (~250).
  - `src/routes/ui_plan.py`: plantillas, sugerencia, splits, undo (~300).
  - `src/routes/ui_explore.py`: cascada, nivel, gráfica (~205).
  - `src/routes/api_session.py`: token, sesión, respiración, health-sync (~290).
  - `src/routes/api_training.py`: ejercicios, plantillas, undo, sugerencia, último (~350).
  - `src/routes/api_daily.py`: cardio API + fechas del día (~100).
  - `src/routes/api_nutrition.py`: diario, alimentos, plantillas comida (~325).
  - `src/ui_fragments.py`: builders HTML (~270). `src/http_shared.py`: validadores y errores (~80). `src/web_context.py`: templates, DB_PATH, ciclo (~30).
- RF-3: SI un módulo nuevo supera 500 líneas de código, ENTONCES el refactor se rechaza.
- RF-4: MIENTRAS se ejecuta el refactor, `tests/test_app.py` + `tests/test_training_api.py` permanecen en verde; al cierre, gates §8 completos pasan.
- RF-5: Al cerrar, la allowlist pierde `app.py` y `tests/test_app.py` sigue pineado (no se parte en 009).

## Fuera de alcance

Ningún cambio de rutas, contratos, UI o seguridad (CSRF/Origin intactos).
Partir `tests/test_app.py` (futura spec si se desea).

## Criterios de finalización

- Caracterización verde antes y después + gates §8 + RF×test registrado.

## Dudas abiertas

- Ninguna.

## Veredicto (recorrido RF×test, 2026-09-25)

- RF-1: OK — 68/68 rutas idénticas por AST (path × método); 0 cambios en contratos. Excepción: 221 parches retargeteados + lectura por atributo de módulo.
- RF-2: OK — 8 routers (132–410), fragments 394, shared 92, context 9, raíz 198.
- RF-3: OK — máx 410.
- RF-4: OK — caracterización 231/231 antes y después; unitaria 893 passed (91.01%); ruff/mypy/module-coverage/file-size verdes. e2e `test_dashboard_flow.py`: mismos 14 preexistentes que en `dev` limpio.
- RF-5: OK — `app.py` fuera de la allowlist (quedan solo tests pineados); gate `tamaño OK`.
