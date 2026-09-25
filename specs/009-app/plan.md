# Plan técnico — Spec 009 (routers por área + raíz de composición)

## Estrategia

Patrón FastAPI estándar: `APIRouter()` por área (sin prefijos: paths
idénticos) + `app.include_router` en la raíz. `@app.get/post/delete` →
`@router.get/post/delete` (mecánico). En `app.py` quedan: imports mínimos,
lifespan, middleware, exception handler, healthz, exports CSV (~47),
`templates`/`DB_PATH` re-exportados (los tests los importan de `app`),
e includes.

## Anticipación de riesgos

- Circulares: routers importan servicios + `web_context`/`http_shared`;
  `app.py` importa routers. `web_context` solo depende de `config` (+
  Jinja2). Verificar DAG por AST antes del commit.
- `templates` se construye en `web_context` (con su `static_url` global);
  `app.py` lo re-exporta para `from app import templates`.
- `CICLO_START_DATE`, `MAX_*`, `GRANULARITY_VALUES` → `http_shared`/`web_context`.
- Imports: bloque original completo por módulo; poda `ruff --fix` al final
  (sin re-exports aquí: poda segura). Verificar decoradores en fronteras
  (lección 007): los `@app.*` se reescriben, no se cortan.

## Cortes (líneas 1-indexed de `app.py`)

| Módulo | Líneas | Code est. |
|---|---|---|
| `src/web_context.py` | nuevo (templates+DB_PATH+ciclo) | ~30 |
| `src/http_shared.py` | 178–180, 260–286, 633–643, 2156–2175, 2511–2521 + consts | ~80 |
| `src/ui_fragments.py` | 289–630 | ~270 |
| `src/routes/ui_daily.py` | 647–907 | ~225 |
| `src/routes/ui_food.py` | 908–1186 | ~250 |
| `src/routes/ui_plan.py` | 1190–1529 | ~300 |
| `src/routes/ui_explore.py` | 1561–1805 | ~205 |
| `src/routes/api_session.py` | 1809–2129 | ~290 |
| `src/routes/api_training.py` | 2133–2508 | ~350 |
| `src/routes/api_daily.py` | 2525–2622 | ~100 |
| `src/routes/api_nutrition.py` | 2661–3011 | ~325 |
| `app.py` | resto + includes | ~250 |

`validation_error_handler` + middleware + healthz + exports quedan en raíz.

## Orden de tareas

T1 spec+plan+tasks y línea base (hecho). T2 caracterización. T3 contexto+
shared+fragments. T4 routers UI. T5 routers API. T6 raíz+includes, DAG,
tamaños. T7 gates + allowlist + commit.
