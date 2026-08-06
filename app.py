import os
import json
from collections import deque
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
    backup_db,
    delete_session_by_fecha,
    get_categories,
    get_ejercicio_categoria,
    get_exercises_catalog,
    get_plantillas,
    get_sets_by_fecha,
    init_db,
    insert_exercise,
    reorder_plantillas,
    restore_entrenos,
    snapshot_entrenos,
)
from src.db_connection import read_connection
from src.models import TemplateInput
from src.template_service import (
    apply_template_rows,
    delete_plantilla,
    edit_template,
    save_template,
)
from src.training_service import (
    fecha_to_db,
    parse_cycle_start,
    parse_form_date,
    save_session,
    sets_from_form,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(DB_PATH)
    yield

app = FastAPI(title="Gym Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UNDO_STACK: deque = deque(maxlen=10)

def _undo_push_sesion(fecha_iso: str, before: list[dict], after: list[dict]) -> None:
    UNDO_STACK.append({"kind": "sesion", "fecha_iso": fecha_iso, "before": before, "after": after})

def _undo_push_entrenos(before: list, after: list) -> None:
    UNDO_STACK.append({"kind": "entrenos", "before": before, "after": after})

CICLO_START_DATE = parse_cycle_start(CICLO_START)

def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")

def _muscle_names() -> list[str]:
    return sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]})

def _render_body(response) -> str:
    return bytes(response.body).decode()

def _navigator_html(request: Request, fecha_iso: str) -> str:
    vm = build_date_navigator(DB_PATH, fecha_iso, CICLO_START_DATE, date.today())
    return _render_body(templates.TemplateResponse(
        request=request,
        name="date_navigator.html",
        context={
            "dates": vm.dates,
            "selected_iso": vm.selected_iso,
            "today_iso": vm.today_iso,
        },
    ))

def _editor_html(request: Request, fecha_iso: str, *, rows=None, error: str | None = None, success: str | None = None, force_editable: bool = False, force_readonly: bool = False) -> str:
    vm = build_session_editor(
        DB_PATH, fecha_iso, CICLO_START_DATE,
        rows=rows,
        error=error,
        success=success,
        force_editable=force_editable,
        force_readonly=force_readonly,
    )
    return _render_body(templates.TemplateResponse(
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
    ))

def _exercise_form_html(request: Request, *, error: str | None = None, success: str | None = None) -> str:
    return _render_body(templates.TemplateResponse(
        request=request,
        name="exercise_create_form.html",
        context={"categories": MUSCLE_CATEGORIES, "muscle_names": _muscle_names(), "error": error, "success": success},
    ))

def _plantillas_list_html(request: Request, *, editing_id: int | None = None, error: str | None = None) -> str:
    return _render_body(templates.TemplateResponse(
        request=request,
        name="plantillas_list.html",
        context={
            "plantillas": get_plantillas(DB_PATH),
            "catalog": get_exercises_catalog(DB_PATH),
            "editing_id": editing_id,
            "error": error,
        },
    ))

def _plantillas_oob(html: str) -> str:
    return f'<div id="plantillas-section" hx-swap-oob="outerHTML">{html}</div>'

def _notice_oob(target: str, message: str, *, error: bool = False, dismiss: int = 3000) -> str:
    kind = "notice-error" if error else "notice-success"
    return (
        f'<div id="{target}" hx-swap-oob="innerHTML">'
        f'<div class="notice {kind}" data-dismiss="{dismiss}">{message}</div></div>'
    )

def _domain_error_response(error: Exception, target: str, *, extra: str = "") -> HTMLResponse:
    message, status = translate_error(error)
    return HTMLResponse(content=_notice_oob(target, message, error=True, dismiss=4500) + extra, status_code=status)

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
            "systemic_chart_html": chart_html(DB_PATH, "systemic", title="Rendimiento Global – Todo el Cuerpo"),
            "navigator_html": _navigator_html(request, fecha),
            "editor_html": _editor_html(request, fecha),
            "exercise_form_html": _exercise_form_html(request),
            "plantillas_html": _plantillas_list_html(request),
            "app_config_json": {"categoria_map": get_ejercicio_categoria(DB_PATH)},
        }
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
    notice_success = _notice_oob("editor-notice", "Entrenamiento guardado.", dismiss=3000)
    outcome_ok = '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>'
    outcome_fail = '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="0" hidden></div>'
    try:
        backup_db(DB_PATH)
        fecha_db = fecha_to_db(parse_form_date(fecha))
        before_rows = get_sets_by_fecha(DB_PATH, fecha_db)
        save_session(DB_PATH, fecha, sets)
        saved_rows = get_sets_by_fecha(DB_PATH, fecha_db)
        _undo_push_sesion(fecha, before_rows, saved_rows)
        if saved_rows:
            state = ('<div id="editor-state" hx-swap-oob="outerHTML" '
                     f'data-readonly="1" data-has-data="1" hidden></div>')
            return HTMLResponse(content=notice_success + outcome_ok + state)
        editor = _editor_html(request, fecha)
        return HTMLResponse(
            content=notice_success + outcome_ok
            + f'<div id="session-editor-wrap" hx-swap-oob="innerHTML">{editor}</div>'
        )
    except Exception as e:
        return _domain_error_response(e, "editor-notice", extra=outcome_fail)

@app.post("/entrenamiento/session/eliminar", response_class=HTMLResponse)
def entrenamiento_session_eliminar(request: Request, fecha: str = Form(...)):
    notice = _notice_oob("editor-notice", "Entreno eliminado.", dismiss=3000)
    outcome_ok = '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>'
    try:
        backup_db(DB_PATH)
        fecha_db = fecha_to_db(parse_form_date(fecha))
        before_rows = get_sets_by_fecha(DB_PATH, fecha_db)
        delete_session_by_fecha(DB_PATH, fecha_db)
        _undo_push_sesion(fecha, before_rows, [])
    except Exception:
        pass
    editor = _editor_html(request, fecha)
    return HTMLResponse(
        content=notice + outcome_ok
        + f'<div id="session-editor-wrap" hx-swap-oob="innerHTML">{editor}</div>'
    )

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
        return HTMLResponse(content=_notice_oob("notice-container", error, error=True, dismiss=4500))
    insert_exercise(DB_PATH, ejercicio, grupo_muscular, categoria)
    notice_success = _notice_oob("notice-container", f"Ejercicio '{ejercicio}' creado.", dismiss=3000)
    form_html = _exercise_form_html(request)
    return HTMLResponse(
        content=notice_success + f'<div id="exercise-create" hx-swap-oob="outerHTML">{form_html}</div>'
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
        before = snapshot_entrenos(DB_PATH)
        result = save_template(DB_PATH, TemplateInput(nombre=nombre, ejercicios=ejercicio))
        _undo_push_entrenos(before, snapshot_entrenos(DB_PATH))
    except Exception as e:
        return _domain_error_response(e, "notice-container")
    msg = "Entreno actualizado." if result.updated else "Entreno guardado."
    return HTMLResponse(content=_notice_oob("notice-container", msg, dismiss=3000) + _plantillas_oob(_plantillas_list_html(request)))

@app.post("/plantilla/editar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_editar(
    request: Request,
    plantilla_id: int,
    nombre: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        before = snapshot_entrenos(DB_PATH)
        edit_template(DB_PATH, plantilla_id, TemplateInput(nombre=nombre, ejercicios=ejercicio))
        _undo_push_entrenos(before, snapshot_entrenos(DB_PATH))
    except Exception as e:
        html = _plantillas_list_html(request, editing_id=plantilla_id, error=str(e))
        return HTMLResponse(content=_plantillas_oob(html))
    return HTMLResponse(
        content=_notice_oob("notice-container", "Entreno guardado.", dismiss=3000)
        + _plantillas_oob(_plantillas_list_html(request))
    )

@app.post("/plantilla/eliminar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_eliminar(request: Request, plantilla_id: int):
    before = snapshot_entrenos(DB_PATH)
    delete_plantilla(DB_PATH, plantilla_id)
    _undo_push_entrenos(before, snapshot_entrenos(DB_PATH))
    return HTMLResponse(
        content=_notice_oob("notice-container", "Entreno eliminado.", dismiss=3000)
        + _plantillas_oob(_plantillas_list_html(request))
    )

@app.post("/plantilla/reordenar", response_class=HTMLResponse)
def plantilla_reordenar(id: list[int] = Form(default=[])):
    before = snapshot_entrenos(DB_PATH)
    reorder_plantillas(DB_PATH, id)
    _undo_push_entrenos(before, snapshot_entrenos(DB_PATH))
    return HTMLResponse(content="")

@app.get("/plantilla/aplicar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_aplicar(request: Request, plantilla_id: int, fecha: str = Query(...)):
    try:
        rows = apply_template_rows(DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(e, "editor-notice")
    editor = _editor_html(request, fecha, rows=rows, force_editable=True)
    notice = _notice_oob("editor-notice", "Entreno aplicado.", dismiss=3000)
    return HTMLResponse(
        content=notice
        + f'<div id="session-editor-wrap" hx-swap-oob="innerHTML">{editor}<div id="plantilla-applied" hidden></div></div>'
    )

@app.post("/undo", response_class=HTMLResponse)
def undo(request: Request, fecha: str = Form("")):
    notice_ok = _notice_oob("notice-container", "Acción deshecha.", dismiss=2500)
    notice_empty = _notice_oob("notice-container", "Nada que deshacer.", error=True, dismiss=2500)
    if not UNDO_STACK:
        return HTMLResponse(content=notice_empty)
    entry = UNDO_STACK.pop()
    backup_db(DB_PATH)
    if entry["kind"] == "sesion":
        fecha_iso = entry["fecha_iso"]
        save_session(DB_PATH, fecha_iso, entry["before"])
        restored = get_sets_by_fecha(DB_PATH, fecha_to_db(parse_form_date(fecha_iso)))
        has_data = "1" if any(
            str(r.get("ejercicio") or "").strip()
            or any(str(r.get(k) or "").strip() for k in ("kg", "reps", "rir"))
            for r in restored
        ) else "0"
        marker = (
            f'<div id="undo-result" hx-swap-oob="outerHTML" '
            f'data-fecha="{fecha_iso}" data-has-data="{has_data}" hidden></div>'
        )
        if fecha == fecha_iso:
            outcome_ok = '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>'
            editor = _editor_html(request, fecha_iso)
            return HTMLResponse(
                content=notice_ok + outcome_ok + marker
                + f'<div id="session-editor-wrap" hx-swap-oob="innerHTML">{editor}</div>'
            )
        return HTMLResponse(content=notice_ok + marker)
    restore_entrenos(DB_PATH, entry["before"])
    return HTMLResponse(content=notice_ok + _plantillas_oob(_plantillas_list_html(request)))

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
        chart_html_frag = chart_html(DB_PATH, "systemic", title="Rendimiento Global – Todo el Cuerpo")
        exercise_list_html = _render_body(templates.TemplateResponse(
            request=request,
            name="exercise_list.html",
            context={
                "ejercicios_grupo": ejercicios_list,
                "grupo": "",
            }
        ))
        oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html_frag}</div>'
        return HTMLResponse(content=exercise_list_html + oob_chart)

    ejercicios_grupo = get_ejercicios_por_grupo(DB_PATH, grupo)
    chart_html_frag = chart_html(DB_PATH, "muscle_group", grupo, f"Rendimiento – {grupo}")
    exercise_list_html = _render_body(templates.TemplateResponse(
        request=request,
        name="exercise_list.html",
        context={
            "ejercicios_grupo": ejercicios_grupo,
            "grupo": grupo,
        }
    ))
    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html_frag}</div>'
    return HTMLResponse(content=exercise_list_html + oob_chart)

@app.get("/grupo/reset", response_class=HTMLResponse)
def reset_grupo(request: Request, grupo: str = Query(...)):
    chart_html_frag = chart_html(DB_PATH, "muscle_group", grupo, f"Rendimiento – {grupo}")
    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html_frag}</div>'
    return HTMLResponse(content='<div></div>' + oob_chart)

@app.get("/ejercicio", response_class=HTMLResponse)
def get_exercise_history(request: Request, ejercicio: str = Query(...)):
    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    raw_data = raw_df.to_dict(orient="records") if not raw_df.empty else []

    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    session_summary = session_df.to_dict(orient="records") if not session_df.empty else []

    chart_html_frag = chart_html(DB_PATH, "exercise", ejercicio, f"Rendimiento – {ejercicio}")
    tables_html = _render_body(templates.TemplateResponse(
        request=request,
        name="exercise_detail.html",
        context={
            "raw_data": raw_data,
            "session_summary": session_summary,
            "ejercicio": ejercicio,
        }
    ))
    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html_frag}</div>'
    return HTMLResponse(content=tables_html + oob_chart)
