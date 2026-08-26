import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from config import CICLO_START, DB_PATH, HC_SYNC_TOKEN, MUSCLE_CATEGORIES
from src.charts import chart_pfr_timeline, get_exercise_raw_data, get_exercise_session_summary
from src.dashboard_service import (
    build_date_navigator,
    build_nutrition_editor,
    build_session_editor,
    chart_shell_html,
    get_filters,
    get_first_session_date,
    translate_error,
)
from src.database import (
    get_alimentos_catalog,
    get_categories,
    get_dashboard_catalog,
    get_ejercicio_categoria,
    get_exercises_catalog,
    get_plantillas,
    get_plantillas_alimentacion,
    get_sets_by_fecha,
    get_split_catalog,
    get_splits_summary,
    init_db,
)
from src.db_connection import read_connection
from src.exercise_service import create_exercise
from src.health_sync_service import MAX_BODY_BYTES, ingest_health_records, parse_payload
from src.logging_setup import request_id_var, setup_logging
from src.models import (
    SPLIT_DAYS,
    AlimentoInput,
    Split,
    SplitInput,
    SplitMetrics,
    TemplateInput,
    ValidationError,
)
from src.mutation_service import (
    delete_diary_with_undo_snapshot,
    delete_session,
    delete_split_with_undo_snapshot,
    delete_template_with_undo_snapshot,
    edit_template_with_undo_snapshot,
    reorder_templates_with_undo_snapshot,
    save_diary_with_undo_snapshot,
    save_session_with_undo_snapshot,
    save_split_with_undo_snapshot,
    save_template_with_undo_snapshot,
    undo_last_action,
)
from src.network_access import LanSyncOnlyMiddleware, lan_sync_only_enabled
from src.nutrition_service import (
    NUTRIENT_FIELDS,
    apply_meal_template,
    create_alimento,
    entries_from_form,
    save_meal_template,
)
from src.response_fragments import (
    STATIC_MARKERS,
    app_config_oob,
    chart_data_oob,
    chart_empty_oob,
    chart_header_oob,
    editor_state_oob,
    editor_wrap_oob,
    fragment_oob,
    notice_oob,
    nutrition_editor_wrap_oob,
    render_fragment,
    summary_oob,
    undo_result_oob,
)
from src.security import (
    CSRFProtectionMiddleware,
    SecurityHeadersMiddleware,
    get_csrf_secret,
    make_csrf_token,
)
from src.split_service import compute_split_metrics, get_split_board, split_items_from_form
from src.static_assets import is_current_digest, static_url
from src.template_service import apply_template_rows
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_display,
    fecha_to_db,
    parse_cycle_start,
    parse_form_date,
    sets_from_form,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
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
    init_db(DB_PATH)
    yield


MAX_FORM_SETS = 100  # series por sesión
MAX_DIARY_ROWS = 100  # filas del diario
MAX_REORDER_IDS = 500  # ids de reordenamiento
MAX_NAME_LEN = 200  # nombres (ejercicio, alimento, plantilla)
MAX_SPLIT_ITEMS = 300  # items (instancias/series) por split


def _check_lote(rows: list, max_rows: int, campo: str) -> None:
    if len(rows) > max_rows:
        raise ValidationError(f"Demasiadas filas de {campo} (máx. {max_rows}).")


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
templates = Jinja2Templates(directory="templates")
templates.env.globals["static_url"] = static_url


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


CICLO_START_DATE = parse_cycle_start(CICLO_START)


def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")


def _muscle_names() -> list[str]:
    return sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]})


GRANULARITY_VALUES = ("day", "week", "month")


def _validate_granularity(gran: str) -> str:
    """Valida gran y devuelve el valor canónico. Default: 'day' (contrato B1)."""
    if gran not in GRANULARITY_VALUES:
        raise ValidationError(
            f"Granularidad inválida: {gran!r}. Valores permitidos: day, week, month."
        )
    return gran


def _validate_window(ventana: int) -> int:
    """Valida la ventana del panel: solo 4 u 8 semanas (contrato Fase 2)."""
    if ventana not in (4, 8):
        raise ValidationError(f"Ventana inválida: {ventana}. Valores permitidos: 4, 8.")
    return ventana


def _render_body(response) -> str:
    return bytes(response.body).decode()


def _navigator_html(
    request: Request,
    fecha_iso: str,
    grupo: str | None = None,
    ejercicio: str | None = None,
) -> str:
    vm = build_date_navigator(
        DB_PATH, fecha_iso, CICLO_START_DATE, date.today(), grupo=grupo, ejercicio=ejercicio
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="date_navigator.html",
            context={
                "dates": vm.dates,
                "selected_iso": vm.selected_iso,
                "today_iso": vm.today_iso,
            },
        )
    )


def _editor_html(
    request: Request,
    fecha_iso: str,
    *,
    rows=None,
    error: str | None = None,
    success: str | None = None,
    force_editable: bool = False,
    force_readonly: bool = False,
) -> str:
    vm = build_session_editor(
        DB_PATH,
        fecha_iso,
        CICLO_START_DATE,
        rows=rows,
        error=error,
        success=success,
        force_editable=force_editable,
        force_readonly=force_readonly,
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="session_editor.html",
            context={
                "fecha_iso": vm.fecha_iso,
                "fecha_display": vm.fecha_display,
                "semana": vm.semana,
                "dia": vm.dia,
                "rows": vm.rows,
                "readonly": vm.readonly,
                "has_data": vm.has_data,
                "error": vm.error,
                "success": vm.success,
                "catalog": vm.catalog,
            },
        )
    )


def _exercise_form_html(
    request: Request, *, error: str | None = None, success: str | None = None
) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_create_form.html",
            context={
                "categories": MUSCLE_CATEGORIES,
                "muscle_names": _muscle_names(),
                "error": error,
                "success": success,
            },
        )
    )


def _plantillas_list_html(
    request: Request, *, editing_id: int | None = None, error: str | None = None
) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="plantillas_list.html",
            context={
                "plantillas": get_plantillas(DB_PATH),
                "catalog": get_exercises_catalog(DB_PATH),
                "editing_id": editing_id,
                "error": error,
            },
        )
    )


def _split_accordion_item_html(
    request: Request,
    split_id: int | None,
    *,
    open_: bool = False,
    max_items: int = MAX_SPLIT_ITEMS,
) -> str:
    """Fragmento de un item del acordeón de splits (cabecera + board semanal).

    `split_id=None` renderiza un split nuevo vacío (sin persistir) en modo
    edición, para el flujo "Crear nuevo split" (GET /split/nuevo).
    """
    split: Split | None = None
    metrics: SplitMetrics = compute_split_metrics([])
    if split_id is not None:
        board = get_split_board(DB_PATH, split_id)
        split = board["split"]
        metrics = board["metrics"]
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="partials/split_accordion_item.html",
            context={
                "days": SPLIT_DAYS,
                "split": split,
                "metrics": metrics,
                "editmode": "0" if split else "1",
                "max_items": max_items,
                "open": open_,
            },
        )
    )


def _split_section_html(request: Request, abrir_id: int | None = None) -> str:
    """Contenido de #splits-section: estado vacío o items del acordeón."""
    items_html = ""
    for s in get_splits_summary(DB_PATH):
        items_html += _split_accordion_item_html(
            request, s["id"], open_=(abrir_id is not None and abrir_id == s["id"])
        )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="partials/split_accordion.html",
            context={"splits_html": items_html},
        )
    )


def _split_page_html(request: Request, abrir_id: int | None = None) -> str:
    """Página completa del gestor de splits (base.html + fragmentos)."""
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="splits.html",
            context={
                "catalog": get_split_catalog(DB_PATH),
                "splits_html": _split_section_html(request, abrir_id=abrir_id),
                "app_config_json": {"csrf_token": make_csrf_token(get_csrf_secret())},
            },
        )
    )


NUTRIENT_FIELD_LABELS: list[dict[str, str]] = [
    {"name": "kcal", "label": "kcal"},
    {"name": "carbohidratos", "label": "Carb (g)"},
    {"name": "fibra", "label": "Fibra (g)"},
    {"name": "proteina", "label": "Prot (g)"},
    {"name": "grasa", "label": "Grasa (g)"},
    {"name": "hierro", "label": "Hierro (mg)"},
    {"name": "calcio", "label": "Calcio (mg)"},
    {"name": "vitamina_c", "label": "Vit C (mg)"},
    {"name": "vitamina_a", "label": "Vit A (µg)"},
]


def _alimento_preview_map() -> dict[str, dict[str, float]]:
    """Mapa compacto nombre -> 9 nutrientes por 100 g para previsualización client."""
    return {a["nombre"]: {k: a[k] for k in NUTRIENT_FIELDS} for a in get_alimentos_catalog(DB_PATH)}


def _nutrition_app_config() -> dict:
    return {
        "alimento_map": _alimento_preview_map(),
        "csrf_token": make_csrf_token(get_csrf_secret()),
    }


def _nutrition_fecha_display(fecha_iso: str) -> str:
    from datetime import date as _date

    d = _date.fromisoformat(fecha_iso)
    return f"{d.day}/{d.month}/{d.year}"


def _plantillas_alimentacion_list_html(request: Request, fecha_iso: str) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="plantillas_alimentacion_list.html",
            context={
                "plantillas": get_plantillas_alimentacion(DB_PATH),
                "selected_iso": fecha_iso,
            },
        )
    )


def _nutrition_editor_html(
    request: Request,
    fecha_iso: str,
    *,
    rows: list[dict] | None = None,
    force_editable: bool = False,
    error: str | None = None,
    success: str | None = None,
) -> str:
    vm = build_nutrition_editor(
        DB_PATH,
        fecha_iso,
        rows=rows,
        force_editable=force_editable,
        error=error,
        success=success,
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="nutrition_editor.html",
            context={
                "fecha_iso": vm.fecha_iso,
                "rows": vm.rows,
                "totals": vm.consumido,
                "objetivo": vm.objetivo,
                "consumido": vm.consumido,
                "parametros": vm.parametros,
                "catalog": vm.catalog,
                "has_data": vm.has_data,
                "readonly": vm.readonly,
                "prefilled": vm.prefilled,
                "prefill_source": vm.prefill_source,
                "error": vm.error,
                "success": vm.success,
            },
        )
    )


def _alimento_form_html(request: Request) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="alimento_create_form.html",
            context={"nutrient_fields": NUTRIENT_FIELD_LABELS},
        )
    )


def _domain_error_response(
    request: Request, error: Exception, target: str, *, extra: str = ""
) -> HTMLResponse:
    message, status = translate_error(error)
    return HTMLResponse(
        content=notice_oob(
            templates, request, target=target, message=message, kind="notice-error", dismiss=4500
        )
        + extra,
        status_code=status,
    )


@app.get("/", response_class=HTMLResponse)
def read_index(request: Request, gran: str = Query(default="day")):
    from datetime import date as _date

    from src.summary_service import build_period_summary

    ejercicios_list, grupos_list = get_filters(DB_PATH)
    categories = get_categories(DB_PATH) or MUSCLE_CATEGORIES
    fecha = _today_iso()
    _fecha_date = _date.fromisoformat(fecha)
    granularity = _validate_granularity(gran)
    # Render inicial del panel derecho server-side: sin flash ni layout shift
    # (misma técnica anti-parpadeo de la granularidad). El servicio devuelve
    # estado error/empty controlado; nunca propaga a HTTP.
    period_summary = build_period_summary(DB_PATH, [], [], granularity, 8)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "grupos_list": grupos_list,
            "ejercicios_list": ejercicios_list,
            "ejercicios_grupo": ejercicios_list,
            "muscle_categories": categories,
            "effective_gran": granularity,
            "period_summary": period_summary,
            "dashboard_catalog": get_dashboard_catalog(DB_PATH),
            "cascade_row_html": _cascade_row_html(request, "musculo", ""),
            "systemic_chart_html": chart_shell_html(
                "Rendimiento",
                chart_pfr_timeline(DB_PATH, "systemic", "", granularity=granularity),
            ),
            "navigator_html": _navigator_html(request, fecha),
            "editor_html": _editor_html(request, fecha),
            "dia": day_from_date(_fecha_date),
            "fecha_display": fecha_display(fecha),
            "semana": calculate_cycle_week(_fecha_date, CICLO_START_DATE),
            "exercise_form_html": _exercise_form_html(request),
            "plantillas_html": _plantillas_list_html(request),
            "nutrition_editor_html": _nutrition_editor_html(request, fecha),
            "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
            "alimento_form_html": _alimento_form_html(request),
            "app_config_json": {
                "categoria_map": get_ejercicio_categoria(DB_PATH),
                "alimento_map": _alimento_preview_map(),
                "ciclo_start": CICLO_START_DATE.isoformat(),
                "csrf_token": make_csrf_token(get_csrf_secret()),
            },
        },
    )


@app.get("/fecha/editor", response_class=HTMLResponse)
def fecha_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_editor_html(request, fecha))


def _cardio_day_html(request: Request, fecha: str) -> str:
    from src.cardio_service import get_day_cardio

    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="cardio_day.html",
            context={"cardio": get_day_cardio(DB_PATH, fecha), "fecha_iso": fecha},
        )
    )


@app.get("/registro", response_class=HTMLResponse)
def registro_page(request: Request, fecha: str = Query(default="")):
    """Página dedicada de registro diario: navegador + editores + cardio."""
    from datetime import date as _date

    if not fecha:
        fecha = _date.today().isoformat()
    fecha_date = _date.fromisoformat(fecha)
    context = {
        "navigator_html": _navigator_html(request, fecha),
        "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
        "nutrition_editor_html": _nutrition_editor_html(request, fecha),
        "editor_html": _editor_html(request, fecha),
        "cardio_html": _cardio_day_html(request, fecha),
        "exercise_form_html": _exercise_form_html(request),
        "alimento_form_html": _alimento_form_html(request),
        "plantillas_html": _plantillas_list_html(request),
        "dia": day_from_date(fecha_date),
        "fecha_display": fecha_display(fecha),
        "semana": calculate_cycle_week(fecha_date, CICLO_START_DATE),
    }
    return HTMLResponse(
        content=_render_body(
            templates.TemplateResponse(request=request, name="registro.html", context=context)
        )
    )


@app.get("/editor/popup", response_class=HTMLResponse)
def editor_popup(request: Request, fecha: str = Query(...)):
    """Cuerpo de la ventana emergente de registro: navegador + editores + cardio."""
    from datetime import date as _date

    fecha_date = _date.fromisoformat(fecha)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="editor_popup.html",
            context={
                "navigator_html": _navigator_html(request, fecha),
                "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
                "nutrition_editor_html": _nutrition_editor_html(request, fecha),
                "editor_html": _editor_html(request, fecha),
                "cardio_html": _cardio_day_html(request, fecha),
                "exercise_form_html": _exercise_form_html(request),
                "alimento_form_html": _alimento_form_html(request),
                "plantillas_html": _plantillas_list_html(request),
                "dia": day_from_date(fecha_date),
                "fecha_display": fecha_display(fecha),
                "semana": calculate_cycle_week(fecha_date, CICLO_START_DATE),
            },
        )
    )


@app.get("/cardio/day", response_class=HTMLResponse)
def cardio_day(request: Request, fecha: str = Query(...)):
    """Fragmento del panel de cardio de una fecha (navegación dentro del popup)."""
    return HTMLResponse(content=_cardio_day_html(request, fecha))


@app.post("/cardio/annotation", response_class=HTMLResponse)
def cardio_annotation_save(
    request: Request,
    hc_id: str = Form(...),
    velocidad_kmh: float | None = Form(None),
    inclinacion_pct: float | None = Form(None),
    notas: str = Form(""),
    fecha: str = Form(""),
):
    """Upsert de velocidad/inclinación sobre una sesión EXERCISE_SESSION."""
    from src.cardio_service import CardioAnnotationInput, upsert_cardio_annotation

    try:
        upsert_cardio_annotation(
            DB_PATH,
            CardioAnnotationInput(
                hc_id=hc_id,
                velocidad_kmh=velocidad_kmh,
                inclinacion_pct=inclinacion_pct,
                notas=notas,
            ),
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates,
        request,
        target="notice-container",
        message="Anotación de cardio guardada.",
        dismiss=2500,
    )
    if fecha:
        return HTMLResponse(
            content=notice
            + fragment_oob(
                templates,
                request,
                "cardio-day",
                _cardio_day_html(request, fecha),
                swap="outerHTML",
            )
        )
    return HTMLResponse(content=notice)


@app.post("/entrenamiento/session/save", response_class=HTMLResponse)
def entrenamiento_session_save(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
    descanso: list[str] = Form(default=[]),
):
    _check_lote(ejercicio, MAX_FORM_SETS, "series")
    sets = sets_from_form(ejercicio, kg, reps, rir, descansos=descanso)
    notice_success = notice_oob(
        templates, request, target="editor-notice", message="Entrenamiento guardado."
    )
    outcome_ok = STATIC_MARKERS["outcome_ok"]
    outcome_fail = STATIC_MARKERS["outcome_fail"]
    try:
        save_session_with_undo_snapshot(DB_PATH, fecha, sets)
        saved_rows = get_sets_by_fecha(DB_PATH, fecha_to_db(parse_form_date(fecha)))
        if saved_rows:
            return HTMLResponse(
                content=notice_success + outcome_ok + editor_state_oob(templates, request)
            )
        editor = _editor_html(request, fecha)
        return HTMLResponse(
            content=notice_success + outcome_ok + editor_wrap_oob(templates, request, editor)
        )
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice", extra=outcome_fail)


@app.post("/entrenamiento/session/eliminar", response_class=HTMLResponse)
def entrenamiento_session_eliminar(request: Request, fecha: str = Form(...)):
    notice = notice_oob(templates, request, target="editor-notice", message="Entreno eliminado.")
    outcome_ok = STATIC_MARKERS["outcome_ok"]
    outcome_fail = STATIC_MARKERS["outcome_fail"]
    try:
        delete_session(DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice", extra=outcome_fail)
    editor = _editor_html(request, fecha)
    return HTMLResponse(content=notice + outcome_ok + editor_wrap_oob(templates, request, editor))


@app.post("/ejercicio/nuevo", response_class=HTMLResponse)
def ejercicio_nuevo(
    request: Request,
    ejercicio: str = Form(..., max_length=MAX_NAME_LEN),
    grupo_muscular: str = Form(..., max_length=MAX_NAME_LEN),
    categoria: str = Form(..., max_length=MAX_NAME_LEN),
):
    try:
        create_exercise(DB_PATH, ejercicio, grupo_muscular, categoria)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice_success = notice_oob(
        templates,
        request,
        target="notice-container",
        message=f"Ejercicio '{ejercicio.strip()}' creado.",
    )
    form_html = _exercise_form_html(request)
    return HTMLResponse(
        content=notice_success
        + fragment_oob(templates, request, "exercise-create", form_html, swap="outerHTML")
    )


@app.get("/alimentacion/editor", response_class=HTMLResponse)
def alimentacion_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_nutrition_editor_html(request, fecha))


@app.post("/alimentacion/save", response_class=HTMLResponse)
def alimentacion_save(
    request: Request,
    fecha: str = Form(...),
    alimento: list[str] = Form(default=[]),
    cantidad: list[str] = Form(default=[]),
    peso_kg: float | None = Form(None),
    factor_proteina: float | None = Form(None),
    factor_grasa: float | None = Form(None),
    kcal_objetivo: float | None = Form(None),
):
    notice = notice_oob(templates, request, target="notice-container", message="Día guardado.")
    parametros = {
        "peso_kg": peso_kg,
        "factor_proteina": factor_proteina,
        "factor_grasa": factor_grasa,
        "kcal_objetivo": kcal_objetivo,
    }
    parametros = {k: v for k, v in parametros.items() if v is not None}
    try:
        entries = entries_from_form(alimento, cantidad)
        save_diary_with_undo_snapshot(DB_PATH, fecha, entries, parametros=parametros or None)
    except Exception as e:
        return _domain_error_response(
            request, e, "notice-container", extra=STATIC_MARKERS["outcome_fail"]
        )
    editor = _nutrition_editor_html(request, fecha)
    return HTMLResponse(
        content=notice
        + STATIC_MARKERS["outcome_ok"]
        + nutrition_editor_wrap_oob(templates, request, editor)
    )


@app.post("/alimentacion/eliminar", response_class=HTMLResponse)
def alimentacion_eliminar(request: Request, fecha: str = Form(...)):
    notice = notice_oob(templates, request, target="notice-container", message="Día eliminado.")
    try:
        delete_diary_with_undo_snapshot(DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(
            request, e, "notice-container", extra=STATIC_MARKERS["outcome_fail"]
        )
    editor = _nutrition_editor_html(request, fecha)
    return HTMLResponse(
        content=notice
        + STATIC_MARKERS["outcome_ok"]
        + nutrition_editor_wrap_oob(templates, request, editor)
    )


@app.post("/alimento/nuevo", response_class=HTMLResponse)
def alimento_nuevo(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    categoria: str = Form("", max_length=MAX_NAME_LEN),
    kcal: float = Form(0),
    carbohidratos: float = Form(0),
    fibra: float = Form(0),
    proteina: float = Form(0),
    grasa: float = Form(0),
    hierro: float = Form(0),
    calcio: float = Form(0),
    vitamina_c: float = Form(0),
    vitamina_a: float = Form(0),
):
    try:
        create_alimento(
            DB_PATH,
            AlimentoInput(
                nombre=nombre,
                categoria=categoria,
                kcal=kcal,
                carbohidratos=carbohidratos,
                fibra=fibra,
                proteina=proteina,
                grasa=grasa,
                hierro=hierro,
                calcio=calcio,
                vitamina_c=vitamina_c,
                vitamina_a=vitamina_a,
            ),
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates,
        request,
        target="notice-container",
        message=f"Alimento '{nombre.strip()}' creado.",
    )
    form_html = _alimento_form_html(request)
    return HTMLResponse(
        content=notice
        + app_config_oob(_nutrition_app_config())
        + fragment_oob(templates, request, "alimento-create", form_html, swap="outerHTML")
    )


@app.post("/alimentacion/plantilla/guardar", response_class=HTMLResponse)
def plantilla_alimentacion_guardar(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    alimento: list[str] = Form(default=[]),
    cantidad: list[str] = Form(default=[]),
):
    try:
        entries = entries_from_form(alimento, cantidad)
        rows = [{"alimento": e.alimento, "cantidad_g": float(e.cantidad_g)} for e in entries]
        save_meal_template(DB_PATH, nombre, rows)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates, request, target="notice-container", message="Plantilla guardada."
    )
    return HTMLResponse(
        content=notice
        + fragment_oob(
            templates,
            request,
            "nutrition-templates-section",
            _plantillas_alimentacion_list_html(request, _today_iso()),
            swap="outerHTML",
        )
    )


@app.post("/alimentacion/plantilla/eliminar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_alimentacion_eliminar(request: Request, plantilla_id: int):
    from src.database import delete_plantilla_alimentacion

    try:
        delete_plantilla_alimentacion(DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=fragment_oob(
            templates,
            request,
            "nutrition-templates-section",
            _plantillas_alimentacion_list_html(request, _today_iso()),
            swap="outerHTML",
        )
    )


@app.post("/alimentacion/plantilla/reordenar", response_class=HTMLResponse)
def plantilla_alimentacion_reordenar(request: Request, id: list[int] = Form(default=[])):
    from src.database import reorder_plantillas_alimentacion

    try:
        _check_lote(id, MAX_REORDER_IDS, "orden")
        reorder_plantillas_alimentacion(DB_PATH, id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content="")


@app.get("/alimentacion/plantilla/aplicar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_alimentacion_aplicar(request: Request, plantilla_id: int, fecha: str = Query(...)):
    try:
        rows = apply_meal_template(DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    editor = _nutrition_editor_html(request, fecha, rows=rows, force_editable=True)
    notice = notice_oob(
        templates, request, target="notice-container", message="Plantilla aplicada."
    )
    return HTMLResponse(content=notice + nutrition_editor_wrap_oob(templates, request, editor))


@app.get("/plantillas", response_class=HTMLResponse)
def plantillas_view(request: Request, editar: int | None = Query(None)):
    return HTMLResponse(content=_plantillas_list_html(request, editing_id=editar))


@app.post("/plantilla/guardar", response_class=HTMLResponse)
def plantilla_guardar(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        result = save_template_with_undo_snapshot(
            DB_PATH, TemplateInput(nombre=nombre, ejercicios=ejercicio)
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    msg = "Entreno actualizado." if result.updated else "Entreno guardado."
    return HTMLResponse(
        content=notice_oob(templates, request, target="notice-container", message=msg)
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
    )


@app.post("/plantilla/editar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_editar(
    request: Request,
    plantilla_id: int,
    nombre: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        edit_template_with_undo_snapshot(
            DB_PATH, plantilla_id, TemplateInput(nombre=nombre, ejercicios=ejercicio)
        )
    except Exception as e:
        message, status = translate_error(e)
        if status != 400:
            return _domain_error_response(request, e, "notice-container")
        html = _plantillas_list_html(request, editing_id=plantilla_id, error=message)
        return HTMLResponse(
            content=fragment_oob(templates, request, "plantillas-section", html, swap="outerHTML")
        )
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Entreno guardado."
        )
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
    )


@app.post("/plantilla/eliminar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_eliminar(request: Request, plantilla_id: int):
    try:
        delete_template_with_undo_snapshot(DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Entreno eliminado."
        )
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
    )


@app.post("/plantilla/reordenar", response_class=HTMLResponse)
def plantilla_reordenar(request: Request, id: list[int] = Form(default=[])):
    try:
        _check_lote(id, MAX_REORDER_IDS, "orden")
        reorder_templates_with_undo_snapshot(DB_PATH, id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content="")


@app.get("/plantilla/aplicar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_aplicar(request: Request, plantilla_id: int, fecha: str = Query(...)):
    try:
        rows = apply_template_rows(DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice")
    editor = _editor_html(request, fecha, rows=rows, force_editable=True)
    notice = notice_oob(templates, request, target="editor-notice", message="Entreno aplicado.")
    return HTMLResponse(
        content=notice
        + editor_wrap_oob(templates, request, editor + STATIC_MARKERS["plantilla_applied"])
    )


@app.get("/splits", response_class=HTMLResponse)
def splits_view(request: Request, abrir: int | None = Query(None)):
    try:
        if abrir is not None:
            get_split_board(DB_PATH, abrir)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content=_split_page_html(request, abrir_id=abrir))


@app.get("/split/nuevo", response_class=HTMLResponse)
def split_nuevo(request: Request):
    """Fragmento del item de un split nuevo (vacío, en modo edición).

    GET puro sin efectos colaterales: el JS lo inserta al tope de la sección
    y lo persiste solo al pulsar Guardar.
    """
    return HTMLResponse(content=_split_accordion_item_html(request, None))


@app.post("/split/guardar", response_class=HTMLResponse)
def split_guardar(
    request: Request,
    split_id: int | None = Form(None),
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    dia: list[str] = Form(default=[]),
    item_type: list[str] = Form(default=[]),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        _check_lote(dia, MAX_SPLIT_ITEMS, "elementos")
        items = split_items_from_form(dia, item_type, ejercicio)
        result = save_split_with_undo_snapshot(
            DB_PATH, split_id, SplitInput(nombre=nombre, items=items)
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    msg = "Split actualizado." if result.updated else "Split guardado."
    return HTMLResponse(
        content=notice_oob(templates, request, target="notice-container", message=msg)
        + fragment_oob(
            templates,
            request,
            "splits-section",
            _split_section_html(request),
            swap="outerHTML",
        )
    )


@app.post("/split/eliminar/{split_id}", response_class=HTMLResponse)
def split_eliminar(request: Request, split_id: int):
    try:
        delete_split_with_undo_snapshot(DB_PATH, split_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Split eliminado."
        )
        + fragment_oob(
            templates,
            request,
            "splits-section",
            _split_section_html(request),
            swap="outerHTML",
        )
    )


@app.post("/undo", response_class=HTMLResponse)
def undo(request: Request, fecha: str = Form("")):
    notice_ok = notice_oob(
        templates, request, target="notice-container", message="Acción deshecha.", dismiss=2500
    )
    notice_empty = notice_oob(
        templates,
        request,
        target="notice-container",
        message="Nada que deshacer.",
        kind="notice-error",
        dismiss=2500,
    )
    try:
        result = undo_last_action(DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    if result["kind"] == "empty":
        return HTMLResponse(content=notice_empty)
    if result["kind"] == "sesion":
        fecha_iso = result["fecha_iso"]
        marker = undo_result_oob(templates, request, fecha_iso, result["has_data"])
        if fecha == fecha_iso:
            outcome_ok = STATIC_MARKERS["outcome_ok"]
            editor = _editor_html(request, fecha_iso)
            return HTMLResponse(
                content=notice_ok
                + outcome_ok
                + marker
                + editor_wrap_oob(templates, request, editor)
            )
        return HTMLResponse(content=notice_ok + marker)
    if result["kind"] == "alimentacion":
        fecha_iso = result["fecha_iso"]
        marker = undo_result_oob(templates, request, fecha_iso, result["has_data"])
        if fecha == fecha_iso:
            outcome_ok = STATIC_MARKERS["outcome_ok"]
            editor = _nutrition_editor_html(request, fecha_iso)
            return HTMLResponse(
                content=notice_ok
                + outcome_ok
                + marker
                + nutrition_editor_wrap_oob(templates, request, editor)
            )
        return HTMLResponse(content=notice_ok + marker)
    if result["kind"] == "splits":
        return HTMLResponse(
            content=notice_ok
            + fragment_oob(
                templates,
                request,
                "splits-section",
                _split_section_html(request),
                swap="outerHTML",
            )
        )
    return HTMLResponse(
        content=notice_ok
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
    )


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
        with read_connection(DB_PATH) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        logging.getLogger("dashboard").exception("healthz: la DB no responde")
        return JSONResponse({"status": "error", "db": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})


@app.get("/semana/primer-entreno", response_class=JSONResponse)
def semana_primer_entreno(
    semana: int = Query(...),
    grupo: str | None = Query(None),
    ejercicio: str | None = Query(None),
):
    fecha = get_first_session_date(DB_PATH, semana, grupo, ejercicio)
    return JSONResponse({"fecha": fecha})


def _cascade_items(nivel: str, foco: str) -> list[str]:
    """Siguiente fila de la cascada: categorías → músculos → ejercicios."""
    from src.db_connection import read_connection

    if nivel == "grupo" and not foco:
        return [str(c["name"]) for c in get_categories(DB_PATH) or MUSCLE_CATEGORIES]
    if nivel == "grupo":
        with read_connection(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo_muscular FROM ejercicios "
                "WHERE LOWER(categoria) = LOWER(?) AND grupo_muscular IS NOT NULL "
                "ORDER BY grupo_muscular",
                (foco,),
            ).fetchall()
        return [str(r[0]) for r in rows]
    if nivel == "musculo":
        with read_connection(DB_PATH) as conn:
            if foco and foco.lower() != "cardio":
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios "
                    "WHERE LOWER(grupo_muscular) = LOWER(?) ORDER BY ejercicio",
                    (foco,),
                ).fetchall()
                return [str(r[0]) for r in rows]
            if not foco:
                rows = conn.execute(
                    "SELECT DISTINCT grupo_muscular FROM ejercicios "
                    "WHERE grupo_muscular IS NOT NULL ORDER BY grupo_muscular"
                ).fetchall()
                items = [str(r[0]) for r in rows]
                items.append("Cardio")
                return items
        return []
    if nivel == "ejercicio":
        with read_connection(DB_PATH) as conn:
            rows = conn.execute("SELECT ejercicio FROM ejercicios ORDER BY ejercicio").fetchall()
        return [str(r[0]) for r in rows]
    return []


def _cascade_chip_tipo(nivel: str, foco: str) -> str:
    """Tipo de la fila desplegada: mismo nivel si es selección directa, o el
    siguiente nivel cuando un foco avanza la cascada (grupo→músculo→ejercicio)."""
    if foco:
        return {"grupo": "musculo", "musculo": "ejercicio"}.get(nivel, "")
    return nivel


def _cascade_row_html(request: Request, nivel: str, foco: str) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="cascade_row.html",
            context={
                "items": _cascade_items(nivel, foco),
                "tipo": _cascade_chip_tipo(nivel, foco),
            },
        )
    )


def _ejercicios_row_html(request: Request, musculo: str, seleccionados: list[str]) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="ejercicios_row.html",
            context={
                "items": _cascade_items("musculo", musculo),
                "padre": musculo,
                "seleccionados": seleccionados,
            },
        )
    )


def _exercise_detail_html(request, ejercicio):

    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_detail.html",
            context={
                "raw_data": raw_df.to_dict(orient="records") if not raw_df.empty else [],
                "session_summary": (
                    session_df.to_dict(orient="records") if not session_df.empty else []
                ),
                "ejercicio": ejercicio,
            },
        )
    )


@app.get("/nivel", response_class=HTMLResponse)
def nivel_view(
    request: Request,
    tipo: str = Query(...),
    foco: str = Query(default=""),
    ejercicios: list[str] = Query(default=[]),
    gran: str = Query(default="day"),
):
    """Cascada: músculos (fila persistente) → ejercicios del músculo → detalle.

    - tipo=musculo sin foco: fila de músculos (no toca la gráfica).
    - tipo=musculo con foco: fila de ejercicios del músculo con aria-pressed.
    - tipo=ejercicio con foco: detalle tabular en #history-section.
    - tipo=ejercicio sin foco: placeholder de detalle.
    - tipo=global: fila de músculos únicamente (sin OOB de gráfica).
    """
    _validate_granularity(gran)
    if tipo == "ejercicio":
        if foco:
            body = _exercise_detail_html(request, foco)
        else:
            body = _render_body(
                templates.TemplateResponse(
                    request=request,
                    name="exercise_detail.html",
                    context={"raw_data": [], "session_summary": [], "ejercicio": ""},
                )
            )
        return HTMLResponse(content=body)
    if tipo == "musculo" and foco:
        selected = []
        if ejercicios and len(ejercicios) == 1:
            selected = [s.strip() for s in ejercicios[0].split(",") if s.strip()]
        elif ejercicios:
            selected = [s.strip() for s in ejercicios if s.strip()]
        return HTMLResponse(content=_ejercicios_row_html(request, foco, selected))
    if tipo == "global":
        return HTMLResponse(content=_cascade_row_html(request, "musculo", ""))
    return HTMLResponse(content=_cascade_row_html(request, tipo, foco))


@app.get("/grafica", response_class=HTMLResponse)
def grafica_view(
    request: Request,
    musculos: list[str] = Query(default=[]),
    ejercicios: list[str] = Query(default=[]),
    gran: str = Query(default="day"),
    ventana: int = Query(default=8),
):
    """Gráfica + panel de resumen en UNA sola respuesta (contrato Fase 2).

    Targets OOB exclusivos: unified-chart-header/data/empty + period-summary-wrap.
    Gráfica y panel comparten exactamente la misma selección y granularidad;
    la ventana del panel es propia (4|8 semanas, default 8) e independiente de
    las ventanas visuales de la gráfica.
    """
    from src.charts import chart_selection
    from src.summary_service import build_period_summary

    granularity = _validate_granularity(gran)
    semanas = _validate_window(ventana)

    if not musculos:
        fig = chart_pfr_timeline(DB_PATH, "systemic", "", "", granularity)
    else:
        fig = chart_selection(DB_PATH, musculos, ejercicios, granularity)

    has_data = hasattr(fig, "data") and fig.data
    if has_data:
        from src.dashboard_service import _json_for_inline

        data_json = _json_for_inline(fig.to_json())
        content = (
            chart_header_oob("Rendimiento") + chart_data_oob(data_json) + chart_empty_oob(False)
        )
    else:
        empty_text = "Sin datos para esta selección" if musculos else "Sin datos"
        content = (
            chart_header_oob("Rendimiento")
            + chart_data_oob("{}")
            + chart_empty_oob(True, empty_text)
        )

    # El panel viaja en la MISMA respuesta: una petición actualiza ambos y el
    # abort existente (cancelPending('/grafica')) protege gráfica+panel juntos.
    summary = build_period_summary(DB_PATH, musculos, ejercicios, granularity, semanas)
    summary_html = render_fragment(
        templates,
        request,
        "partials/period_summary_panel.html",
        summary=summary,
        oob=True,
    )
    content += summary_oob(summary_html)

    return HTMLResponse(content=content)


@app.post("/sync/health-connect")
async def health_sync_ingest(request: Request):
    """API ingestion endpoint (JSON, not htmx): CSRF-exempt by exact path in
    src/security.py; authenticated with X-Sync-Token (HC_SYNC_TOKEN env)."""
    if not HC_SYNC_TOKEN:
        return JSONResponse({"detail": "Endpoint no configurado (HC_SYNC_TOKEN)"}, status_code=503)
    token = request.headers.get("X-Sync-Token", "")
    if not token or not hmac.compare_digest(token, HC_SYNC_TOKEN):
        return JSONResponse({"detail": "Token inválido"}, status_code=401)
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        payload = parse_payload(json.loads(raw_body))
    except (json.JSONDecodeError, ValidationError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    try:
        result = ingest_health_records(DB_PATH, payload)
    except Exception:
        logging.getLogger("health_sync").exception("ingesta fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": 1,
            "received": result.received,
            "accepted_count": result.accepted_count,
            "accepted": [{"hc_id": a.hc_id, "revision": a.revision} for a in result.accepted],
            "rejected": [
                {"hc_id": r.hc_id, "revision": r.revision, "reason": r.reason}
                for r in result.rejected
            ],
        }
    )


@app.get("/exportar/health-connect.csv", response_class=Response)
def export_health_connect_csv(incluir_borrados: bool = Query(default=False)):
    """CSV de health_records activos ordenado por (record_type, start_epoch_ms).

    Parámetro incluir_borrados=1 para auditoría de bajas (filas con deleted_at).
    """
    deleted_clause = "" if incluir_borrados else "WHERE deleted_at IS NULL"
    with read_connection(DB_PATH) as conn:
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
