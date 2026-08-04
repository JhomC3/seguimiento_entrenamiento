import os
import sqlite3
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from config import CICLO_START, DB_PATH, MUSCLE_CATEGORIES
from src.charts import (
    chart_pfr_timeline,
    get_exercise_raw_data,
    get_exercise_session_summary,
)
from src.database import (
    backup_db,
    delete_session,
    get_categories,
    get_exercises_catalog,
    get_session_sets,
    init_db,
    insert_exercise,
)
from src.training_service import (
    fecha_from_db,
    get_session_detail,
    get_sessions_page,
    insert_manual_session,
    parse_cycle_start,
    update_session,
)

SESSIONS_PER_PAGE = 20

app = FastAPI(title="Gym Tracker")
templates = Jinja2Templates(directory="templates")

CICLO_START_ISO = parse_cycle_start(CICLO_START).strftime("%Y-%m-%d")

def get_db_status():
    if not os.path.exists(DB_PATH):
        return {"has_data": False, "count": 0, "weeks": 0}
    try:
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
        weeks = conn.execute("SELECT MAX(semana) FROM training_sets").fetchone()[0]
        conn.close()
        return {"has_data": count > 0, "count": count, "weeks": weeks or 0}
    except Exception:
        return {"has_data": False, "count": 0, "weeks": 0}

def get_filters():
    if not os.path.exists(DB_PATH):
        return [], []
    conn = sqlite3.connect(DB_PATH)
    try:
        ejercicios = [r[0] for r in conn.execute(
            "SELECT DISTINCT ejercicio FROM training_sets ORDER BY ejercicio"
        ).fetchall()]
        grupos = [r[0] for r in conn.execute(
            "SELECT DISTINCT grupo_muscular FROM ejercicios ORDER BY grupo_muscular"
        ).fetchall()]
    except Exception:
        ejercicios, grupos = [], []
    finally:
        conn.close()
    return ejercicios, grupos

def get_ejercicios_por_grupo(grupo: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        result = [r[0] for r in conn.execute(
            "SELECT DISTINCT t.ejercicio FROM training_sets t "
            "JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio) "
            "WHERE LOWER(e.grupo_muscular) = LOWER(?) ORDER BY t.ejercicio",
            (grupo,)
        ).fetchall()]
    except Exception:
        result = []
    finally:
        conn.close()
    return result

def _chart_html(filter_type: str, filter_value: str | None = None, title: str = ""):
    fig = chart_pfr_timeline(DB_PATH, filter_type, filter_value, title)
    if fig.data:
        return fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False})
    return "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"

def _sessions_list_html(request: Request, page: int = 1):
    sessions, total, page = get_sessions_page(DB_PATH, page, SESSIONS_PER_PAGE)
    total_pages = max(1, -(-total // SESSIONS_PER_PAGE))
    return templates.TemplateResponse(
        request=request,
        name="sessions_list.html",
        context={"sessions": sessions, "page": page, "total_pages": total_pages, "total": total},
    ).body.decode()

def _form_context(*, form_sets=None, form_fecha=None, error=None, success=None, edit=None):
    return {
        "catalog": get_exercises_catalog(DB_PATH),
        "categories": MUSCLE_CATEGORIES,
        "ciclo_start_iso": CICLO_START_ISO,
        "muscle_names": sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]}),
        "form_sets": form_sets or [{"ejercicio": "", "kg": "", "reps": "", "rir": ""}],
        "form_fecha": form_fecha,
        "error": error,
        "success": success,
        "edit": edit,
    }

def _form_html(request: Request, **kwargs):
    return templates.TemplateResponse(
        request=request,
        name="training_form.html",
        context=_form_context(**kwargs),
    ).body.decode()

def _build_sets_from_form(ejercicios: list[str], kgs: list[str], reps: list[str], rirs: list[str]):
    sets = []
    for i, ejercicio in enumerate(ejercicios):
        sets.append({
            "ejercicio": ejercicio,
            "kg": kgs[i] if i < len(kgs) else "",
            "reps": reps[i] if i < len(reps) else "",
            "rir": rirs[i] if i < len(rirs) else "",
        })
    return sets

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    status = get_db_status()
    ejercicios_list, grupos_list = get_filters()
    categories = get_categories(DB_PATH) or MUSCLE_CATEGORIES
    chart_html = _chart_html("systemic", title="Rendimiento Global – Todo el Cuerpo") if status["has_data"] else ""
    sessions_html = _sessions_list_html(request, 1)
    form_html = _form_html(request)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "has_data": status["has_data"],
            "count": status["count"],
            "weeks": status["weeks"],
            "grupos_list": grupos_list,
            "ejercicios_list": ejercicios_list,
            "ejercicios_grupo": ejercicios_list,
            "muscle_categories": categories,
            "systemic_chart_html": chart_html,
            "form_html": form_html,
            "sessions_html": sessions_html,
        }
    )

@app.post("/entrenamiento", response_class=HTMLResponse)
async def create_entrenamiento(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
):
    sets = _build_sets_from_form(ejercicio, kg, reps, rir)
    try:
        insert_manual_session(DB_PATH, fecha, sets)
        form_html = _form_html(request, success="Entrenamiento guardado correctamente.")
        oob = f'<div id="sessions-list" hx-swap-oob="innerHTML">{_sessions_list_html(request, 1)}</div>'
        return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>{oob}')
    except ValueError as e:
        form_html = _form_html(request, form_sets=sets, form_fecha=fecha, error=str(e))
        return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>')

@app.get("/entrenamiento/form", response_class=HTMLResponse)
async def entrenamiento_form(request: Request):
    return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{_form_html(request)}</div>')

@app.get("/entrenamientos", response_class=HTMLResponse)
async def entrenamientos_list(request: Request, pagina: int = Query(1)):
    return HTMLResponse(content=_sessions_list_html(request, pagina))

@app.get("/entrenamiento/session", response_class=HTMLResponse)
async def entrenamiento_session(request: Request, semana: int = Query(...), dia: str = Query(...), fecha: str = Query(...)):
    sets = get_session_detail(DB_PATH, semana, dia, fecha)
    return templates.TemplateResponse(
        request=request,
        name="session_detail.html",
        context={"sets": sets, "semana": semana, "dia": dia, "fecha": fecha},
    )

@app.get("/entrenamiento/session/edit", response_class=HTMLResponse)
async def entrenamiento_session_edit(request: Request, semana: int = Query(...), dia: str = Query(...), fecha: str = Query(...)):
    rows = get_session_sets(DB_PATH, semana, dia, fecha)
    form_sets = [
        {"ejercicio": r["ejercicio"], "kg": r["kg"], "reps": r["reps"], "rir": r["rir"]}
        for r in rows
    ]
    form_html = _form_html(
        request,
        form_sets=form_sets,
        form_fecha=fecha_from_db(fecha).strftime("%Y-%m-%d"),
        edit={"semana": semana, "dia": dia, "fecha": fecha},
    )
    return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>')

@app.post("/entrenamiento/session/update", response_class=HTMLResponse)
async def entrenamiento_session_update(
    request: Request,
    old_semana: int = Form(...),
    old_dia: str = Form(...),
    old_fecha: str = Form(...),
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
):
    sets = _build_sets_from_form(ejercicio, kg, reps, rir)
    try:
        backup_db(DB_PATH)
        update_session(DB_PATH, old_semana, old_dia, old_fecha, fecha, sets)
        form_html = _form_html(request, success="Entrenamiento actualizado correctamente.")
        oob = f'<div id="sessions-list" hx-swap-oob="innerHTML">{_sessions_list_html(request, 1)}</div>'
        return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>{oob}')
    except ValueError as e:
        form_html = _form_html(
            request, form_sets=sets, form_fecha=fecha,
            edit={"semana": old_semana, "dia": old_dia, "fecha": old_fecha},
            error=str(e),
        )
        return HTMLResponse(content=f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>')

@app.post("/entrenamiento/session/delete", response_class=HTMLResponse)
async def entrenamiento_session_delete(
    request: Request,
    semana: int = Query(...),
    dia: str = Query(...),
    fecha: str = Query(...),
):
    backup_db(DB_PATH)
    delete_session(DB_PATH, semana, dia, fecha)
    oob_sessions = f'<div id="sessions-list" hx-swap-oob="innerHTML">{_sessions_list_html(request, 1)}</div>'
    oob_detail = ('<div id="session-detail" hx-swap-oob="innerHTML">'
                  '<div class="rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-xs px-3 py-2">'
                  'Entrenamiento eliminado.</div></div>')
    return HTMLResponse(content=oob_sessions + oob_detail)

@app.get("/ejercicio/nuevo/form", response_class=HTMLResponse)
async def ejercicio_nuevo_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="exercise_create_form.html",
        context={"categories": MUSCLE_CATEGORIES, "muscle_names": sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]})},
    )

@app.post("/ejercicio/nuevo", response_class=HTMLResponse)
async def ejercicio_nuevo(
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
        return templates.TemplateResponse(
            request=request,
            name="exercise_create_form.html",
            context={
                "categories": MUSCLE_CATEGORIES,
                "muscle_names": sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]}),
                "error": error,
            },
        )
    insert_exercise(DB_PATH, ejercicio, grupo_muscular, categoria)
    form_html = _form_html(request, success=f"Ejercicio '{ejercicio}' creado.")
    oob = (
        f'<div id="exercise-create-container" hx-swap-oob="innerHTML"></div>'
        f'<div id="training-form" hx-swap-oob="outerHTML">{form_html}</div>'
    )
    return HTMLResponse(content=oob)

@app.get("/exportar/csv", response_class=Response)
async def export_csv():
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query("SELECT * FROM training_sets ORDER BY fecha, set_orden", conn)
    finally:
        conn.close()
    csv = df.to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entrenamientos.csv"'},
    )

@app.get("/select", response_class=HTMLResponse)
async def select_view(request: Request, grupo: str = Query(None)):
    if not grupo:
        ejercicios_list, _ = get_filters()
        chart_html = _chart_html("systemic", title="Rendimiento Global – Todo el Cuerpo")

        exercise_list_html = templates.TemplateResponse(
            request=request,
            name="exercise_list.html",
            context={
                "ejercicios_grupo": ejercicios_list,
                "grupo": "",
            }
        ).body.decode()

        oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'
        return HTMLResponse(content=exercise_list_html + oob_chart)

    ejercicios_grupo = get_ejercicios_por_grupo(grupo)
    chart_html = _chart_html("muscle_group", grupo, f"Rendimiento – {grupo}")

    exercise_list_html = templates.TemplateResponse(
        request=request,
        name="exercise_list.html",
        context={
            "ejercicios_grupo": ejercicios_grupo,
            "grupo": grupo,
        }
    ).body.decode()

    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'
    return HTMLResponse(content=exercise_list_html + oob_chart)


@app.get("/grupo/reset", response_class=HTMLResponse)
async def reset_grupo(request: Request, grupo: str = Query(...)):
    chart_html = _chart_html("muscle_group", grupo, f"Rendimiento – {grupo}")

    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'
    return HTMLResponse(content='<div></div>' + oob_chart)

@app.get("/ejercicio", response_class=HTMLResponse)
async def get_exercise_history(request: Request, ejercicio: str = Query(...)):
    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    raw_data = raw_df.to_dict(orient="records") if not raw_df.empty else []

    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    session_summary = session_df.to_dict(orient="records") if not session_df.empty else []

    chart_html = _chart_html("exercise", ejercicio, f"Rendimiento – {ejercicio}")

    tables_html = templates.TemplateResponse(
        request=request,
        name="exercise_detail.html",
        context={
            "raw_data": raw_data,
            "session_summary": session_summary,
            "ejercicio": ejercicio,
        }
    ).body.decode()

    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'

    return HTMLResponse(content=tables_html + oob_chart)
