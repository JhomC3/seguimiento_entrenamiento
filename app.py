import os
import sqlite3
from datetime import date, datetime, timedelta

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
    get_categories,
    get_exercises_catalog,
    get_sets_by_fecha,
    insert_exercise,
)
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_to_db,
    parse_cycle_start,
    parse_form_date,
    save_session,
)

def _end_of_next_month(d: date) -> date:
    next_year = d.year + (d.month + 1) // 12
    next_month = (d.month + 1) % 12 + 1
    return date(next_year, next_month, 1) - timedelta(days=1)

app = FastAPI(title="Gym Tracker")
templates = Jinja2Templates(directory="templates")

CICLO_START_DATE = parse_cycle_start(CICLO_START)

def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")

def _muscle_names() -> list[str]:
    return sorted({m for c in MUSCLE_CATEGORIES for m in c["muscles"]})

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

def _fechas_con_datos() -> set[str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT DISTINCT fecha FROM training_sets").fetchall()
    finally:
        conn.close()
    out = set()
    for (f,) in rows:
        try:
            out.add(datetime.strptime(f, "%d/%m/%y").date().strftime("%Y-%m-%d"))
        except ValueError:
            continue
    return out

def _navigator_html(request: Request, fecha_iso: str) -> str:
    selected = parse_form_date(fecha_iso)
    data_dates = _fechas_con_datos()
    dates = []
    d = CICLO_START_DATE
    end = _end_of_next_month(date.today())
    while d <= end:
        iso = d.strftime("%Y-%m-%d")
        dates.append({
            "iso": iso,
            "label": f"{d.day}/{d.month}" if d.day == 1 else str(d.day),
            "has_data": iso in data_dates,
            "selected": d == selected,
        })
        d += timedelta(days=1)
    return templates.TemplateResponse(
        request=request,
        name="date_navigator.html",
        context={
            "dates": dates,
            "selected_iso": selected.strftime("%Y-%m-%d"),
            "today_iso": date.today().strftime("%Y-%m-%d"),
        },
    ).body.decode()

def _editor_html(request: Request, fecha_iso: str, *, rows: list[dict] | None = None, error: str | None = None, success: str | None = None, force_editable: bool = False, force_readonly: bool = False) -> str:
    fecha = parse_form_date(fecha_iso)
    today = date.today()
    readonly = (force_readonly or fecha < today) and not force_editable
    if rows is None:
        rows = [dict(r) for r in get_sets_by_fecha(DB_PATH, fecha_to_db(fecha))]
    data_rows = [
        r for r in rows
        if str(r.get("ejercicio") or "").strip()
        or any(str(r.get(k) or "").strip() for k in ("kg", "reps", "rir"))
    ]
    display_rows = []
    for r in data_rows:
        kg = r.get("kg")
        reps = r.get("reps")
        rir = r.get("rir")
        rm = None
        try:
            if kg not in (None, "") and reps not in (None, ""):
                ri = float(rir) if rir not in (None, "") else 0.0
                rm = round(float(kg) * (1 + 0.0333 * (float(reps) + 1 + ri)), 1)
        except (TypeError, ValueError):
            rm = None
        display_rows.append({
            "ejercicio": r.get("ejercicio", ""),
            "kg": "" if kg is None else kg,
            "reps": "" if reps is None else reps,
            "rir": "" if rir is None else rir,
            "rm": rm,
        })
    if not display_rows and not readonly:
        display_rows = [{"ejercicio": "", "kg": "", "reps": "", "rir": "", "rm": None}]
    semana = calculate_cycle_week(fecha, CICLO_START_DATE)
    dia = day_from_date(fecha)
    return templates.TemplateResponse(
        request=request,
        name="session_editor.html",
        context={
            "fecha_iso": fecha_iso,
            "fecha_db": fecha_to_db(fecha),
            "semana": semana,
            "dia": dia,
            "rows": display_rows,
            "readonly": readonly,
            "error": error,
            "success": success,
            "catalog": get_exercises_catalog(DB_PATH),
        },
    ).body.decode()

def _exercise_form_html(request: Request, *, error: str | None = None, success: str | None = None) -> str:
    return templates.TemplateResponse(
        request=request,
        name="exercise_create_form.html",
        context={"categories": MUSCLE_CATEGORIES, "muscle_names": _muscle_names(), "error": error, "success": success},
    ).body.decode()

def _build_sets_from_form(ejercicios: list[str], kgs: list[str], reps: list[str], rirs: list[str]) -> list[dict]:
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
    ejercicios_list, grupos_list = get_filters()
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
            "systemic_chart_html": _chart_html("systemic", title="Rendimiento Global – Todo el Cuerpo"),
            "navigator_html": _navigator_html(request, fecha),
            "editor_html": _editor_html(request, fecha),
            "exercise_form_html": _exercise_form_html(request),
        }
    )

@app.get("/fecha/editor", response_class=HTMLResponse)
async def fecha_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_editor_html(request, fecha))

@app.post("/entrenamiento/session/save", response_class=HTMLResponse)
async def entrenamiento_session_save(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
):
    sets = _build_sets_from_form(ejercicio, kg, reps, rir)
    try:
        backup_db(DB_PATH)
        save_session(DB_PATH, fecha, sets)
        saved_rows = get_sets_by_fecha(DB_PATH, fecha_to_db(parse_form_date(fecha)))
        return HTMLResponse(
            f'<div id="session-editor" hx-swap-oob="outerHTML">'
            f'{_editor_html(request, fecha, success="Entrenamiento guardado.", force_readonly=len(saved_rows) > 0)}</div>'
        )
    except ValueError as e:
        return HTMLResponse(
            f'<div id="session-editor" hx-swap-oob="outerHTML">'
            f'{_editor_html(request, fecha, rows=sets, error=str(e), force_editable=True)}</div>'
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
        return HTMLResponse(content=_exercise_form_html(request, error=error))
    insert_exercise(DB_PATH, ejercicio, grupo_muscular, categoria)
    return HTMLResponse(content=_exercise_form_html(request, success=f"Ejercicio '{ejercicio}' creado."))

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
