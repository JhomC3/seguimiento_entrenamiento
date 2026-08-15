import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import CICLO_START, DB_PATH, HC_SYNC_TOKEN, MUSCLE_CATEGORIES
from src.charts import get_exercise_raw_data, get_exercise_session_summary
from src.dashboard_service import (
    build_date_navigator,
    build_nutrition_editor,
    build_session_editor,
    chart_html,
    get_ejercicios_por_grupo,
    get_filters,
    get_first_session_date,
    translate_error,
)
from src.database import (
    get_alimentos_catalog,
    get_categories,
    get_ejercicio_categoria,
    get_exercises_catalog,
    get_plantillas,
    get_plantillas_alimentacion,
    get_sets_by_fecha,
    init_db,
)
from src.db_connection import read_connection
from src.exercise_service import create_exercise
from src.health_sync_service import MAX_BODY_BYTES, ingest_health_records, parse_payload
from src.models import AlimentoInput, TemplateInput, ValidationError
from src.mutation_service import (
    delete_diary_with_undo_snapshot,
    delete_session,
    delete_template_with_undo_snapshot,
    edit_template_with_undo_snapshot,
    reorder_templates_with_undo_snapshot,
    save_diary_with_undo_snapshot,
    save_session_with_undo_snapshot,
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
    chart_oob_wrapper,
    editor_state_oob,
    editor_wrap_oob,
    fragment_oob,
    notice_oob,
    nutrition_editor_wrap_oob,
    undo_result_oob,
)
from src.security import (
    CSRFProtectionMiddleware,
    SecurityHeadersMiddleware,
    get_csrf_secret,
    make_csrf_token,
)
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


app = FastAPI(title="Gym Tracker", lifespan=lifespan)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LanSyncOnlyMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Revalidación de assets en desarrollo: el navegador nunca usa JS/CSS viejos."""
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


CICLO_START_DATE = parse_cycle_start(CICLO_START)


def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")


def _muscle_names() -> list[str]:
    return sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]})


def _chart_title(filtro: str | None = None) -> str:
    base = "Rendimiento"
    return f"{base} – {filtro}" if filtro else base


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
def read_index(request: Request):
    from datetime import date as _date

    ejercicios_list, grupos_list = get_filters(DB_PATH)
    categories = get_categories(DB_PATH) or MUSCLE_CATEGORIES
    fecha = _today_iso()
    _fecha_date = _date.fromisoformat(fecha)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "grupos_list": grupos_list,
            "ejercicios_list": ejercicios_list,
            "ejercicios_grupo": ejercicios_list,
            "muscle_categories": categories,
            "systemic_chart_html": chart_html(
                DB_PATH,
                "systemic",
                title=_chart_title(),
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
    ejercicio: str = Form(...),
    grupo_muscular: str = Form(...),
    categoria: str = Form(...),
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
    nombre: str = Form(...),
    categoria: str = Form(""),
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
    nombre: str = Form(...),
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


@app.get("/alimentacion/exportar/csv", response_class=Response)
def export_nutrition_csv():
    with read_connection(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT fecha, orden, alimento, cantidad_g, kcal, carbohidratos, fibra, "
            "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, origen "
            "FROM diario_alimentacion ORDER BY fecha, orden",
            conn,
        )
    csv = "\ufeff" + df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alimentacion.csv"'},
    )


@app.get("/plantillas", response_class=HTMLResponse)
def plantillas_view(request: Request, editar: int | None = Query(None)):
    return HTMLResponse(content=_plantillas_list_html(request, editing_id=editar))


@app.post("/plantilla/guardar", response_class=HTMLResponse)
def plantilla_guardar(
    request: Request,
    nombre: str = Form(...),
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


@app.get("/semana/primer-entreno", response_class=JSONResponse)
def semana_primer_entreno(
    semana: int = Query(...),
    grupo: str | None = Query(None),
    ejercicio: str | None = Query(None),
):
    fecha = get_first_session_date(DB_PATH, semana, grupo, ejercicio)
    return JSONResponse({"fecha": fecha})


@app.get("/exportar/csv", response_class=Response)
def export_csv():
    with read_connection(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM training_sets ORDER BY fecha, set_orden", conn)
    csv = "\ufeff" + df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entrenamientos.csv"'},
    )


@app.get("/select", response_class=HTMLResponse)
def select_view(request: Request, grupo: str = Query(None), fecha: str = Query(None)):
    if not grupo:
        ejercicios_list, _ = get_filters(DB_PATH)
        chart_html_frag = chart_html(
            DB_PATH,
            "systemic",
            title=_chart_title(),
        )
        exercise_list_html = _render_body(
            templates.TemplateResponse(
                request=request,
                name="exercise_list.html",
                context={
                    "ejercicios_grupo": ejercicios_list,
                    "grupo": "",
                },
            )
        )
        oob_chart = chart_oob_wrapper(chart_html_frag)
        selected = fecha or _today_iso()
        navigator_oob = fragment_oob(
            templates,
            request,
            "date-navigator",
            _navigator_html(request, selected),
            swap="outerHTML",
        )
        return HTMLResponse(content=exercise_list_html + oob_chart + navigator_oob)

    ejercicios_grupo = get_ejercicios_por_grupo(DB_PATH, grupo)
    chart_html_frag = chart_html(
        DB_PATH,
        "muscle_group",
        grupo,
        _chart_title(grupo),
    )
    exercise_list_html = _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_list.html",
            context={
                "ejercicios_grupo": ejercicios_grupo,
                "grupo": grupo,
            },
        )
    )
    oob_chart = chart_oob_wrapper(chart_html_frag)
    selected = fecha or _today_iso()
    navigator_oob = fragment_oob(
        templates,
        request,
        "date-navigator",
        _navigator_html(request, selected, grupo=grupo),
        swap="outerHTML",
    )
    return HTMLResponse(content=exercise_list_html + oob_chart + navigator_oob)


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
            if foco:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios "
                    "WHERE LOWER(grupo_muscular) = LOWER(?) ORDER BY ejercicio",
                    (foco,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT grupo_muscular FROM ejercicios "
                    "WHERE grupo_muscular IS NOT NULL ORDER BY grupo_muscular"
                ).fetchall()
        return [str(r[0]) for r in rows]
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


@app.get("/nivel", response_class=HTMLResponse)
def nivel_view(
    request: Request,
    tipo: str = Query(...),
    foco: str = Query(default=""),
):
    """Cascada: músculos (fila persistente) → ejercicios del músculo → detalle.

    - tipo=musculo sin foco: fila de músculos (no toca la gráfica).
    - tipo=musculo con foco: fila de ejercicios del músculo + gráfica del
      compilado (OOB unified-chart).
    - tipo=ejercicio con foco: detalle tabular en #history-section.
    """
    if tipo == "ejercicio" and foco:
        raw_df = get_exercise_raw_data(DB_PATH, foco)
        session_df = get_exercise_session_summary(DB_PATH, foco)
        body = _render_body(
            templates.TemplateResponse(
                request=request,
                name="exercise_detail.html",
                context={
                    "raw_data": raw_df.to_dict(orient="records") if not raw_df.empty else [],
                    "session_summary": (
                        session_df.to_dict(orient="records") if not session_df.empty else []
                    ),
                    "ejercicio": foco,
                },
            )
        )
        return HTMLResponse(content=body)
    if tipo == "musculo" and foco:
        return HTMLResponse(
            content=_ejercicios_row_html(request, foco, [])
            + chart_oob_wrapper(_chart_selection_html([foco], []))
        )
    if tipo == "global":
        # Estado base: fila de músculos + gráfica sistémica.
        return HTMLResponse(
            content=_cascade_row_html(request, "musculo", "")
            + chart_oob_wrapper(chart_html(DB_PATH, "systemic", title=_chart_title()))
        )
    return HTMLResponse(content=_cascade_row_html(request, tipo, foco))


def _chart_selection_html(musculos: list[str], ejercicios: list[str]) -> str:
    """Fragmento de la gráfica de la selección (1 músculo: compilado + ejercicios;
    2+: global + músculos)."""
    from src.charts import chart_selection

    fig = chart_selection(DB_PATH, musculos, ejercicios)
    if not fig.data:
        return (
            "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>"
            "Sin datos para esta selección</div>"
        )
    from src.dashboard_service import _json_for_inline

    return (
        f'<script id="unified-chart-data" type="application/json">'
        f"{_json_for_inline(fig.to_json())}</script>"
        '<div id="unified-chart-plot" class="plotly-graph-div"></div>'
    )


@app.get("/grafica", response_class=HTMLResponse)
def grafica_view(
    request: Request,
    musculo: list[str] = Query(default=[]),
    ejercicios: list[str] = Query(default=[]),
):
    """Gráfica de la selección: 1 músculo → compilado + ejercicios marcados;
    2+ músculos → global + músculos marcados. La fila de ejercicios solo se
    refresca cuando hay exactamente 1 músculo."""
    chart = _chart_selection_html(musculo, ejercicios)
    content = chart_oob_wrapper(chart)
    if len(musculo) == 1:
        content += fragment_oob(
            templates,
            request,
            "ejercicios-row",
            _ejercicios_row_html(request, musculo[0], ejercicios),
            swap="outerHTML",
        )
    return HTMLResponse(content=content)


@app.get("/grupo/reset", response_class=HTMLResponse)
def reset_grupo(request: Request, grupo: str = Query(...), fecha: str = Query(None)):
    chart_html_frag = chart_html(
        DB_PATH,
        "muscle_group",
        grupo,
        _chart_title(grupo),
    )
    oob_chart = chart_oob_wrapper(chart_html_frag)
    selected = fecha or _today_iso()
    navigator_oob = fragment_oob(
        templates,
        request,
        "date-navigator",
        _navigator_html(request, selected, grupo=grupo),
        swap="outerHTML",
    )
    return HTMLResponse(content="<div></div>" + oob_chart + navigator_oob)


@app.get("/ejercicio", response_class=HTMLResponse)
def get_exercise_history(request: Request, ejercicio: str = Query(...), fecha: str = Query(None)):
    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    raw_data = raw_df.to_dict(orient="records") if not raw_df.empty else []

    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    session_summary = session_df.to_dict(orient="records") if not session_df.empty else []

    chart_html_frag = chart_html(
        DB_PATH,
        "exercise",
        ejercicio,
        _chart_title(ejercicio),
    )
    tables_html = _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_detail.html",
            context={
                "raw_data": raw_data,
                "session_summary": session_summary,
                "ejercicio": ejercicio,
            },
        )
    )
    oob_chart = chart_oob_wrapper(chart_html_frag)
    selected = fecha or _today_iso()
    navigator_oob = fragment_oob(
        templates,
        request,
        "date-navigator",
        _navigator_html(request, selected, ejercicio=ejercicio),
        swap="outerHTML",
    )
    return HTMLResponse(content=tables_html + oob_chart + navigator_oob)


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
