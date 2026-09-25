"""Raiz de composicion HTTP: app, middlewares, handlers y routers (spec 009).

Las rutas viven en src/routes/*; los fragmentos en src/ui_fragments.py.
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from src import web_context
from src.database import init_db
from src.db_connection import read_connection
from src.logging_setup import attach_silence_filters, request_id_var, setup_logging
from src.models import ValidationError
from src.network_access import LanSyncOnlyMiddleware, lan_sync_only_enabled
from src.response_fragments import notice_oob
from src.routes.api_daily import router as api_daily_router
from src.routes.api_nutrition import router as api_nutrition_router
from src.routes.api_session import router as api_session_router
from src.routes.api_training import router as api_training_router
from src.routes.ui_daily import router as ui_daily_router
from src.routes.ui_explore import router as ui_explore_router
from src.routes.ui_food import router as ui_food_router
from src.routes.ui_plan import router as ui_plan_router
from src.security import CSRFProtectionMiddleware, SecurityHeadersMiddleware
from src.static_assets import is_current_digest
from src.web_context import templates

__all__ = ["app", "templates"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    attach_silence_filters()
    lan_mode = lan_sync_only_enabled()
    has_secret = bool(os.environ.get("GYM_CSRF_SECRET"))
    if lan_mode and not has_secret:
        raise RuntimeError(
            "GYM_LAN_SYNC_ONLY=1 requires GYM_CSRF_SECRET "
            "(data/csrf_secret, generado por scripts/start_server.sh)"
        )
    if has_secret and not lan_mode:
        raise RuntimeError(
            "GYM_CSRF_SECRET is set without GYM_LAN_SYNC_ONLY=1: the dashboard "
            "would be reachable from the LAN; use scripts/start_server.sh"
        )
    if not has_secret:
        logging.getLogger("security").warning(
            "GYM_CSRF_SECRET no configurado: usando secreto de desarrollo."
        )
    logging.getLogger("dashboard").info(
        "DB_PATH=%s (absoluta: %s)", web_context.DB_PATH, os.path.abspath(web_context.DB_PATH)
    )
    init_db(web_context.DB_PATH)
    yield


class RequestIdMiddleware:
    """Asigna request_id por petición, lo propaga a los logs y emite un
    access log propio (método, path, status, duración).

    Registrado como ÚLTIMO add_middleware: queda el más externo de la pila y
    su header x-request-id llega a toda respuesta, incluidas las de 403/429
    de los middlewares internos.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = dict(message.get("headers", []))
                headers[b"x-request-id"] = request_id.encode()
                message["headers"] = list(headers.items())
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logging.getLogger("access").info(
                "%s %s status=%s duration_ms=%.1f",
                scope["method"],
                scope.get("path", ""),
                status_holder["status"],
                duration_ms,
            )
            request_id_var.reset(token)


app = FastAPI(
    title="Gym Tracker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LanSyncOnlyMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestIdMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def static_cache_policy(request: Request, call_next):
    """Assets con digest vigente → immutable (1 año); el resto → no-cache.

    Evita copias de assets y deploys con caché vieja: el navegador solo
    revalida cuando el ?v= no coincide con el digest actual del archivo.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        rel = request.url.path[len("/static/") :]
        version = request.query_params.get("v")
        if is_current_digest(rel, version):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """Errores de dominio no capturados por el handler → 400 con aviso seguro."""
    return HTMLResponse(
        content=notice_oob(
            templates,
            request,
            target="notice-container",
            message=str(exc),
            kind="notice-error",
            dismiss=4500,
        ),
        status_code=400,
    )


@app.get("/healthz", response_class=JSONResponse)
def healthz():
    """Liveness: la app responde y la DB es consultable."""
    try:
        with read_connection(web_context.DB_PATH) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        logging.getLogger("dashboard").exception("healthz: la DB no responde")
        return JSONResponse({"status": "error", "db": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})


@app.get("/exportar/csv", response_class=Response)
def export_csv():
    """CSV completo de training_sets (export de compatibilidad)."""
    with read_connection(web_context.DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM training_sets ORDER BY fecha, set_orden", conn)
    csv = "\ufeff" + df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entrenamientos.csv"'},
    )


@app.get("/alimentacion/exportar/csv", response_class=Response)
def export_nutrition_csv():
    """CSV completo de diario_alimentacion (export de compatibilidad)."""
    with read_connection(web_context.DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT fecha, orden, alimento, cantidad_g, kcal, carbohidratos, fibra, "
            "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, magnesio, zinc, "
            "potasio, sodio, vitamina_d, vitamina_e, vitamina_k, folato, vitamina_b12, "
            "vitamina_b6, yodo, selenio, origen "
            "FROM diario_alimentacion ORDER BY fecha, orden",
            conn,
        )
    csv = "\ufeff" + df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alimentacion.csv"'},
    )


@app.get("/exportar/health-connect.csv", response_class=Response)
def export_health_connect_csv(incluir_borrados: bool = Query(default=False)):
    """CSV de health_records activos ordenado por (record_type, start_epoch_ms).

    Parámetro incluir_borrados=1 para auditoría de bajas (filas con deleted_at).
    """
    deleted_clause = "" if incluir_borrados else "WHERE deleted_at IS NULL"
    with read_connection(web_context.DB_PATH) as conn:
        df = pd.read_sql_query(
            f"SELECT hc_id, record_type, start_epoch_ms, end_epoch_ms, "
            f"last_modified_epoch_ms, data_origin_package, payload_schema_version, "
            f"value_json, device_id, received_at, updated_at, deleted_at "
            f"FROM health_records {deleted_clause} "
            f"ORDER BY record_type, start_epoch_ms",
            conn,
        )
    csv = "\ufeff" + df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="health-connect.csv"'},
    )


app.include_router(ui_daily_router)
app.include_router(ui_food_router)
app.include_router(ui_plan_router)
app.include_router(ui_explore_router)
app.include_router(api_session_router)
app.include_router(api_training_router)
app.include_router(api_daily_router)
app.include_router(api_nutrition_router)
