from contextlib import asynccontextmanager
from datetime import date

import pandas as pd
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import CICLO_START, DB_PATH, MUSCLE_CATEGORIES
from src.charts import get_exercise_raw_data, get_exercise_session_summary
from src.dashboard_service import (
    build_date_navigator,
    build_session_editor,
    chart_html,
    get_ejercicios_por_grupo,
    get_filters,
    translate_error,
)
from src.database import (
    get_categories,
    get_ejercicio_categoria,
    get_exercises_catalog,
    get_plantillas,
    get_sets_by_fecha,
    init_db,
    insert_exercise,
)
from src.db_connection import read_connection
from src.models import TemplateInput
from src.mutation_service import (
    delete_session,
    delete_template_with_undo_snapshot,
    edit_template_with_undo_snapshot,
    reorder_templates_with_undo_snapshot,
    save_session_with_undo_snapshot,
    save_template_with_undo_snapshot,
    undo_last_action,
)
from src.response_fragments import (
    STATIC_MARKERS,
    chart_oob_wrapper,
    editor_state_oob,
    editor_wrap_oob,
    fragment_oob,
    notice_oob,
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
    fecha_to_db,
    parse_cycle_start,
    parse_form_date,
    sets_from_form,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(DB_PATH)
    yield


app = FastAPI(title="Gym Tracker", lifespan=lifespan)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

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


def _navigator_html(request: Request, fecha_iso: str) -> str:
    vm = build_date_navigator(DB_PATH, fecha_iso, CICLO_START_DATE, date.today())
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
                "fecha_db": vm.fecha_db,
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
    ejercicios_list, grupos_list = get_filters(DB_PATH)
    categories = get_categories(DB_PATH) or MUSCLE_CATEGORIES
    fecha = _today_iso()
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
                nonce=getattr(request.state, "csp_nonce", None),
            ),
            "navigator_html": _navigator_html(request, fecha),
            "editor_html": _editor_html(request, fecha),
            "exercise_form_html": _exercise_form_html(request),
            "plantillas_html": _plantillas_list_html(request),
            "app_config_json": {
                "categoria_map": get_ejercicio_categoria(DB_PATH),
                "csrf_token": make_csrf_token(get_csrf_secret()),
            },
        },
    )


@app.get("/fecha/editor", response_class=HTMLResponse)
def fecha_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_editor_html(request, fecha))


@app.post("/entrenamiento/session/save", response_class=HTMLResponse)
def entrenamiento_session_save(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
):
    sets = sets_from_form(ejercicio, kg, reps, rir)
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
    ejercicio = ejercicio.strip()
    grupo_muscular = grupo_muscular.strip()
    error = None
    if not ejercicio:
        error = "El nombre del ejercicio es obligatorio."
    elif not grupo_muscular:
        error = "El grupo muscular es obligatorio."
    elif categoria not in {c["name"] for c in MUSCLE_CATEGORIES}:
        error = "Categoría inválida."
    elif any(e.lower() == ejercicio.lower() for e in get_exercises_catalog(DB_PATH)):
        error = f"El ejercicio '{ejercicio}' ya existe en el catálogo."
    if error:
        return HTMLResponse(
            content=notice_oob(
                templates,
                request,
                target="notice-container",
                message=error,
                kind="notice-error",
                dismiss=4500,
            )
        )
    insert_exercise(DB_PATH, ejercicio, grupo_muscular, categoria)
    notice_success = notice_oob(
        templates, request, target="notice-container", message=f"Ejercicio '{ejercicio}' creado."
    )
    form_html = _exercise_form_html(request)
    return HTMLResponse(
        content=notice_success
        + fragment_oob(templates, request, "exercise-create", form_html, swap="outerHTML")
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


@app.get("/exportar/csv", response_class=Response)
def export_csv():
    with read_connection(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM training_sets ORDER BY fecha, set_orden", conn)
    csv = df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entrenamientos.csv"'},
    )


@app.get("/select", response_class=HTMLResponse)
def select_view(request: Request, grupo: str = Query(None)):
    if not grupo:
        ejercicios_list, _ = get_filters(DB_PATH)
        chart_html_frag = chart_html(
            DB_PATH,
            "systemic",
            title=_chart_title(),
            nonce=getattr(request.state, "csp_nonce", None),
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
        return HTMLResponse(content=exercise_list_html + oob_chart)

    ejercicios_grupo = get_ejercicios_por_grupo(DB_PATH, grupo)
    chart_html_frag = chart_html(
        DB_PATH,
        "muscle_group",
        grupo,
        _chart_title(grupo),
        nonce=getattr(request.state, "csp_nonce", None),
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
    return HTMLResponse(content=exercise_list_html + oob_chart)


@app.get("/grupo/reset", response_class=HTMLResponse)
def reset_grupo(request: Request, grupo: str = Query(...)):
    chart_html_frag = chart_html(
        DB_PATH,
        "muscle_group",
        grupo,
        _chart_title(grupo),
        nonce=getattr(request.state, "csp_nonce", None),
    )
    oob_chart = chart_oob_wrapper(chart_html_frag)
    return HTMLResponse(content="<div></div>" + oob_chart)


@app.get("/ejercicio", response_class=HTMLResponse)
def get_exercise_history(request: Request, ejercicio: str = Query(...)):
    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    raw_data = raw_df.to_dict(orient="records") if not raw_df.empty else []

    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    session_summary = session_df.to_dict(orient="records") if not session_df.empty else []

    chart_html_frag = chart_html(
        DB_PATH,
        "exercise",
        ejercicio,
        _chart_title(ejercicio),
        nonce=getattr(request.state, "csp_nonce", None),
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
    return HTMLResponse(content=tables_html + oob_chart)
