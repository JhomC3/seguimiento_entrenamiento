import os
import sqlite3
import pandas as pd
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.fetcher import fetch_sheet_csv
from src.parser import parse_ejercicios, parse_ciclo
from src.database import init_db, load_ejercicios, load_training_data
from src.charts import (
    get_exercise_raw_data,
    get_exercise_session_summary,
    chart_pfr_timeline,
)
from config import DB_PATH

MUSCLE_CATEGORIES = [
    {"name": "EMPUJE", "muscles": ["Pectoral", "Hombro", "Triceps"]},
    {"name": "TIRON", "muscles": ["Espalda", "Biceps"]},
    {"name": "PIERNA", "muscles": ["Cuadriceps", "Isquio", "Gluteo", "Gemelos", "Aductor"]},
    {"name": "CORE", "muscles": ["Abdomen"]},
]

app = FastAPI(title="Gym Tracker")
templates = Jinja2Templates(directory="templates")

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

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    status = get_db_status()
    ejercicios_list, grupos_list = get_filters()
    
    systemic_chart_html = ""
    
    if status["has_data"]:
        fig = chart_pfr_timeline(DB_PATH, "systemic", title="Rendimiento Global – Todo el Cuerpo")
        systemic_chart_html = fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False}) if fig.data else ""
        
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
            "muscle_categories": MUSCLE_CATEGORIES,
            "systemic_chart_html": systemic_chart_html,
        }
    )

@app.post("/sync", response_class=HTMLResponse)
async def sync_data(request: Request):
    try:
        os.makedirs("data", exist_ok=True)
        csv_ejercicios = fetch_sheet_csv("ejercicios")
        df_ejercicios = parse_ejercicios(csv_ejercicios)
        csv_ciclo = fetch_sheet_csv("ciclo_16")
        df_ciclo = parse_ciclo(csv_ciclo)
        
        init_db(DB_PATH)
        load_ejercicios(DB_PATH, df_ejercicios)
        load_training_data(DB_PATH, df_ciclo)
        
        return HTMLResponse(content="<script>window.location.reload();</script>")
    except Exception as e:
        html_response = f"""
        <button 
            id="sync-btn"
            hx-post="/sync"
            hx-target="this"
            hx-swap="outerHTML"
            onclick="startSync()"
            class="w-36 h-10 bg-neutral-900 hover:bg-burgundy-700 hover:text-white hover:border-burgundy-700 text-neutral-400 border border-neutral-700 text-xs rounded transition-all uppercase tracking-widest font-black flex items-center justify-center focus:outline-none"
        >
            <span id="sync-text">Error: Reintentar</span>
        </button>
        """
        return HTMLResponse(content=html_response)

@app.get("/select", response_class=HTMLResponse)
async def select_view(request: Request, grupo: str = Query(None)):
    if not grupo:
        ejercicios_list, _ = get_filters()
        fig = chart_pfr_timeline(DB_PATH, "systemic", title="Rendimiento Global – Todo el Cuerpo")
        chart_html = fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False}) if fig.data else "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"
        
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
    fig = chart_pfr_timeline(DB_PATH, "muscle_group", grupo, f"Rendimiento – {grupo}")
    chart_html = fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False}) if fig.data else "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"

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
    fig = chart_pfr_timeline(DB_PATH, "muscle_group", grupo, f"Rendimiento – {grupo}")
    chart_html = fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False}) if fig.data else "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"

    oob_chart = f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'
    return HTMLResponse(content='<div></div>' + oob_chart)

@app.get("/ejercicio", response_class=HTMLResponse)
async def get_exercise_history(request: Request, ejercicio: str = Query(...)):
    raw_df = get_exercise_raw_data(DB_PATH, ejercicio)
    raw_data = raw_df.to_dict(orient="records") if not raw_df.empty else []

    session_df = get_exercise_session_summary(DB_PATH, ejercicio)
    session_summary = session_df.to_dict(orient="records") if not session_df.empty else []

    fig = chart_pfr_timeline(DB_PATH, "exercise", ejercicio, f"Rendimiento – {ejercicio}")
    chart_html = fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False}) if fig.data else "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"

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