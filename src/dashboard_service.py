"""Dashboard orchestration: DB-backed view building and safe error translation.

Pure orchestration: no HTTP, no template rendering. Handlers stay thin.
"""

import html
import logging
import sqlite3
from datetime import date, timedelta

import pandas as pd

from config import CICLO_NUMERO
from src.analysis_data import daily_sleep_hours, daily_volume, daily_weight
from src.charts import build_analysis_chart, chart_pfr_timeline
from src.database import (
    get_alimentos_catalog,
    get_diario_by_fecha,
    get_exercises_catalog,
    get_parametros_diarios,
    get_prev_diary_date,
    get_sets_by_fecha,
)
from src.db_connection import read_connection
from src.metrics_engine import calculate_pfr_timeline, rm_ajustado
from src.models import ConflictError, NotFoundError, ValidationError
from src.nutrition_service import diary_totals, objetivos_diarios
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_display,
    fecha_to_db,
    parse_form_date,
)
from src.view_models import (
    AnalysisKpis,
    AnalysisViewModel,
    DateDay,
    DateNavigatorViewModel,
    DayDetailCardio,
    DayDetailSet,
    DayDetailViewModel,
    EditorRow,
    NutritionEditorViewModel,
    NutritionEntryRow,
    SessionEditorViewModel,
)

logger = logging.getLogger("dashboard")

DOMAIN_ERRORS = (ValidationError, NotFoundError, ConflictError)


def get_recent_sessions(db_path: str, limit: int = 10) -> list[dict]:
    """Latest sessions (ISO sorted by SQL), each with a display date."""
    from src.database import get_training_sessions

    sessions = get_training_sessions(db_path)[:limit]
    for s in sessions:
        try:
            s["fecha_display"] = fecha_display(s["fecha"])
        except ValueError:
            s["fecha_display"] = s["fecha"]
    return sessions


def get_filters(db_path: str) -> tuple[list[str], list[str]]:
    """All distinct exercises and muscle groups. Safe empty result on error."""
    try:
        with read_connection(db_path) as conn:
            ejercicios = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT ejercicio FROM training_sets ORDER BY ejercicio"
                ).fetchall()
            ]
            grupos = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT grupo_muscular FROM ejercicios ORDER BY grupo_muscular"
                ).fetchall()
            ]
        return ejercicios, grupos
    except (sqlite3.Error, OSError):
        logger.exception("No se pudieron cargar los filtros de la DB")
        return [], []


def get_ejercicios_por_grupo(db_path: str, grupo: str) -> list[str]:
    try:
        with read_connection(db_path) as conn:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT t.ejercicio FROM training_sets t "
                    "JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio) "
                    "WHERE LOWER(e.grupo_muscular) = LOWER(?) ORDER BY t.ejercicio",
                    (grupo,),
                ).fetchall()
            ]
    except (sqlite3.Error, OSError):
        logger.exception("No se pudieron cargar los ejercicios del grupo %s", grupo)
        return []


def fechas_con_datos(
    db_path: str, grupo: str | None = None, ejercicio: str | None = None
) -> set[str]:
    with read_connection(db_path) as conn:
        sql = (
            "SELECT DISTINCT t.fecha FROM training_sets t "
            "JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio) "
            "WHERE 1 = 1"
        )
        params: list = []
        if grupo:
            sql += " AND LOWER(e.grupo_muscular) = LOWER(?)"
            params.append(grupo)
        if ejercicio:
            sql += " AND LOWER(t.ejercicio) = LOWER(?)"
            params.append(ejercicio)
        rows = conn.execute(sql, params).fetchall()
    return {f for (f,) in rows if f}


def get_first_session_date(
    db_path: str,
    semana: int,
    grupo: str | None = None,
    ejercicio: str | None = None,
) -> str | None:
    """ISO de la primera sesión de una semana del ciclo, opcionalmente filtrada."""
    with read_connection(db_path) as conn:
        sql = (
            "SELECT t.fecha FROM training_sets t "
            "JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio) "
            "WHERE t.semana = ?"
        )
        params: list = [semana]
        if grupo:
            sql += " AND LOWER(e.grupo_muscular) = LOWER(?)"
            params.append(grupo)
        if ejercicio:
            sql += " AND LOWER(t.ejercicio) = LOWER(?)"
            params.append(ejercicio)
        fechas = [r[0] for r in conn.execute(sql, params).fetchall()]
    return min(fechas) if fechas else None


def _json_for_inline(serialized: str) -> str:
    """Escapa JSON serializado para incrustarlo en <script type="application/json">.

    Mismo escape que Jinja `tojson` (<, >, &, ' -> \\uXXXX): un valor hostil
    (p.ej. un nombre de ejercicio) no puede cerrar el elemento script.
    """
    return (
        serialized.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


def chart_html(
    db_path: str,
    filter_type: str,
    filter_value: str | None = None,
    title: str = "",
) -> str:
    """Plotly chart fragment: panel header + figure JSON + render target div.

    La figura viaja como JSON dentro de un <script type="application/json">
    (elemento inerte, mismo patrón que #app-config) y la renderiza el módulo
    cliente static/js/chart-interaction.js con Plotly.newPlot. Así no hay
    scripts ejecutables inline: la CSP no necesita nonce y los swaps de htmx
    no dependen del manejo de scripts.
    """
    header = (
        '<div class="flex items-baseline gap-2 min-w-0 pl-3 mb-3">'
        f'<h3 class="text-sm font-black tracking-[0.2em] text-burgundy-400 uppercase neon-title truncate">{html.escape(title)}</h3>'
        f'<span class="text-[11px] text-neutral-500 flex-none">Ciclo {CICLO_NUMERO}</span>'
        "</div>"
    )
    fig = chart_pfr_timeline(db_path, filter_type, filter_value, "")
    if fig.data:
        data = _json_for_inline(fig.to_json())
        return (
            header
            + f'<script id="unified-chart-data" type="application/json">{data}</script>'
            + '<div id="unified-chart-plot" class="plotly-graph-div"></div>'
        )
    return (
        header
        + "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"
    )


def _end_of_next_month(d: date) -> date:
    next_year = d.year + (d.month + 1) // 12
    next_month = (d.month + 1) % 12 + 1
    return date(next_year, next_month, 1) - timedelta(days=1)


def build_date_navigator(
    db_path: str,
    fecha_iso: str,
    ciclo_start: date,
    today: date,
    grupo: str | None = None,
    ejercicio: str | None = None,
) -> DateNavigatorViewModel:
    selected = parse_form_date(fecha_iso)
    data_dates = fechas_con_datos(db_path, grupo, ejercicio)
    dates = []
    d = ciclo_start
    end = _end_of_next_month(today)
    while d <= end:
        iso = d.strftime("%Y-%m-%d")
        dates.append(
            DateDay(
                iso=iso,
                label=f"{d.day}/{d.month}" if d.day == 1 else str(d.day),
                has_data=iso in data_dates,
                selected=d == selected,
            )
        )
        d += timedelta(days=1)
    return DateNavigatorViewModel(
        dates=dates,
        selected_iso=selected.strftime("%Y-%m-%d"),
        today_iso=today.strftime("%Y-%m-%d"),
    )


def _row_has_values(r: dict) -> bool:
    return bool(str(r.get("ejercicio") or "").strip()) or any(
        str(r.get(k) or "").strip() for k in ("kg", "reps", "rir")
    )


def _as_float(value) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _editor_rows(rows: list[dict]) -> list[EditorRow]:
    data_rows = [r for r in rows if _row_has_values(r)]
    display = []
    for r in data_rows:
        kg = _as_float(r.get("kg"))
        reps = _as_float(r.get("reps"))
        rir = _as_float(r.get("rir"))
        rm = None
        try:
            if kg is not None and reps is not None:
                rm = round(rm_ajustado(kg, reps, rir or 0.0), 1)
        except (TypeError, ValueError):
            rm = None
        display.append(
            EditorRow(
                ejercicio=str(r.get("ejercicio", "")),
                kg=kg,
                reps=reps,
                rir=rir,
                rm=rm,
            )
        )
    if not display:
        display = [EditorRow(ejercicio="", kg=None, reps=None, rir=None, rm=None)]
    return display


def build_session_editor(
    db_path: str,
    fecha_iso: str,
    ciclo_start: date,
    rows: list[dict] | None = None,
    *,
    error: str | None = None,
    success: str | None = None,
    force_editable: bool = False,
    force_readonly: bool = False,
) -> SessionEditorViewModel:
    fecha = parse_form_date(fecha_iso)
    today = date.today()
    if rows is None:
        rows = [dict(r) for r in get_sets_by_fecha(db_path, fecha_to_db(fecha))]
    else:
        rows = [
            {"ejercicio": r.ejercicio, "kg": r.kg, "reps": r.reps, "rir": r.rir}
            if not isinstance(r, dict)
            else r
            for r in rows
        ]
    has_saved = any(_row_has_values(r) for r in rows)
    readonly = (force_readonly or has_saved or fecha < today) and not force_editable
    return SessionEditorViewModel(
        fecha_iso=fecha_iso,
        fecha_display=fecha_display(fecha_iso),
        semana=calculate_cycle_week(fecha, ciclo_start),
        dia=day_from_date(fecha),
        rows=_editor_rows(rows),
        readonly=readonly,
        has_data=any(_row_has_values(r) for r in rows),
        error=error,
        success=success,
        catalog=get_exercises_catalog(db_path),
    )


def translate_error(error: Exception) -> tuple[str, int]:
    """Maps exceptions to (user-facing message, safe HTTP status).

    Domain errors expose their safe, user-facing message; anything else is
    logged server-side and replaced with a generic message.
    """
    if isinstance(error, DOMAIN_ERRORS):
        return str(error), 400
    logger.exception("Error inesperado en el dashboard")
    return "Ocurrió un error inesperado.", 500


def _nutrition_fecha_display(fecha: date) -> str:
    return f"{fecha.day}/{fecha.month}/{fecha.year}"


def build_nutrition_editor(
    db_path: str,
    fecha_iso: str,
    *,
    rows: list[dict] | None = None,
    force_editable: bool = False,
    error: str | None = None,
    success: str | None = None,
) -> NutritionEditorViewModel:
    """Editor de un día del diario nutricional; toda fecha es editable."""
    fecha = parse_form_date(fecha_iso)
    fecha_iso = fecha.strftime("%Y-%m-%d")
    db_data = get_diario_by_fecha(db_path, fecha_iso)
    data = rows if rows is not None else db_data
    prefill_source: str | None = None
    if rows is None and not db_data:
        # Día vacío: precargar los últimos datos guardados (día previo más cercano).
        prefill_source = get_prev_diary_date(db_path, fecha_iso)
        if prefill_source is not None:
            data = get_diario_by_fecha(db_path, prefill_source)
    entry_rows = [
        NutritionEntryRow(
            orden=r["orden"],
            alimento=r["alimento"],
            cantidad_g=r["cantidad_g"],
            kcal=float(r["kcal"]),
            carbohidratos=float(r["carbohidratos"]),
            fibra=float(r["fibra"]),
            proteina=float(r["proteina"]),
            grasa=float(r["grasa"]),
            hierro=float(r["hierro"]),
            calcio=float(r["calcio"]),
            vitamina_c=float(r["vitamina_c"]),
            vitamina_a=float(r["vitamina_a"]),
        )
        for r in data
    ]
    params = get_parametros_diarios(db_path, fecha_iso) or {}
    if not params and prefill_source is not None:
        params = get_parametros_diarios(db_path, prefill_source) or {}
    defaults = {
        "peso_kg": 70.0,
        "factor_proteina": 1.5,
        "factor_grasa": 1.1,
        "kcal_objetivo": 2300.0,
        "fibra_objetivo": 0.0,
        "hierro_objetivo": 0.0,
        "calcio_objetivo": 0.0,
        "vitamina_c_objetivo": 0.0,
        "vitamina_a_objetivo": 0.0,
    }
    parametros = {**defaults, **{k: float(v) for k, v in params.items()}}
    objetivo = objetivos_diarios(parametros)
    consumido = diary_totals(data)
    consumido["cantidad_g"] = round(
        sum(float(r["cantidad_g"]) for r in data if r["cantidad_g"] is not None), 2
    )
    return NutritionEditorViewModel(
        fecha_iso=fecha_iso,
        fecha_display=_nutrition_fecha_display(fecha),
        rows=entry_rows,
        totals=consumido,
        catalog=[a["nombre"] for a in get_alimentos_catalog(db_path)],
        has_data=bool(db_data),
        readonly=(bool(db_data) or fecha < date.today()) and not force_editable,
        error=error,
        success=success,
        objetivo=objetivo,
        consumido=consumido,
        parametros=parametros,
        prefilled=prefill_source is not None,
        prefill_source=prefill_source,
    )


# ---------------------------------------------------------------------------
# Vista de análisis: KPIs + figura de paneles apilados
# ---------------------------------------------------------------------------

DEFAULT_LAYERS = ("pfr", "volumen", "peso")


def _kpi_pfr(db_path: str, nivel: str, focus: str | None) -> tuple[float | None, float | None]:
    """(PFR actual, variación % vs baseline) con la última fecha del timeline."""
    timeline = calculate_pfr_timeline(db_path, _filter_type(nivel), focus)
    if timeline.empty:
        return None, None
    last = timeline["rendimiento"].dropna()
    if last.empty:
        return None, None
    actual = float(last.iloc[-1])
    return actual, round(actual - 100.0, 1)


def _filter_type(nivel: str) -> str:
    from src.charts import NIVEL_FILTER_TYPE

    return NIVEL_FILTER_TYPE.get(nivel, "systemic")


def _kpi_volumen_semana(db_path: str) -> float | None:
    df = daily_volume(db_path)
    if df.empty:
        return None
    cutoff = df["fecha_dt"].max() - timedelta(days=6)
    week = df[df["fecha_dt"] >= cutoff]
    return round(float(week["valor"].sum()), 1) if not week.empty else None


def _kpi_peso_actual(db_path: str) -> float | None:
    df = daily_weight(db_path)
    if df.empty:
        return None
    return round(float(df["valor"].iloc[-1]), 1)


def _kpi_sueno_anoche(db_path: str) -> float | None:
    df = daily_sleep_hours(db_path)
    if df.empty:
        return None
    return round(float(df["valor"].iloc[-1]), 1)


def _kpi_fallos_semana(db_path: str, nivel: str, focus: str | None) -> int:
    timeline = calculate_pfr_timeline(db_path, _filter_type(nivel), focus)
    if timeline.empty or "sets_fallo" not in timeline.columns:
        return 0
    cutoff = timeline["fecha_dt"].max() - timedelta(days=6)
    week = timeline[timeline["fecha_dt"] >= cutoff]
    return int(week["sets_fallo"].sum()) if not week.empty else 0


def build_analysis_kpis(db_path: str, nivel: str, focus: str | None) -> AnalysisKpis:
    pfr_actual, pfr_variacion = _kpi_pfr(db_path, nivel, focus)
    return AnalysisKpis(
        pfr_actual=pfr_actual,
        pfr_variacion=pfr_variacion,
        volumen_semana=_kpi_volumen_semana(db_path),
        sets_fallo_semana=_kpi_fallos_semana(db_path, nivel, focus),
        peso_actual=_kpi_peso_actual(db_path),
        sueno_anoche=_kpi_sueno_anoche(db_path),
    )


def build_analysis_viewmodel(
    db_path: str,
    nivel: str,
    focus: str | None,
    layers: list[str] | None = None,
    rango: int | None = 8,
) -> AnalysisViewModel:
    """View model completo: KPIs + figura serializada para el cliente."""
    active = tuple(layers or DEFAULT_LAYERS)
    fig = build_analysis_chart(db_path, nivel, focus, list(active), rango)
    has_data = bool(fig.data)
    chart_json = _json_for_inline(fig.to_json()) if has_data else ""
    return AnalysisViewModel(
        kpis=build_analysis_kpis(db_path, nivel, focus),
        chart_json=chart_json,
        nivel=nivel,
        focus=focus,
        active_layers=active,
        rango=rango,
        has_data=has_data,
    )


def analysis_chart_html(vm: AnalysisViewModel) -> str:
    """Fragmento de la gráfica de análisis: JSON inerte + div de render."""
    if not vm.has_data:
        return (
            "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>"
            "Sin datos para esta selección</div>"
        )
    return (
        f'<script id="analysis-chart-data" type="application/json">{vm.chart_json}</script>'
        '<div id="analysis-chart-plot" class="plotly-graph-div"></div>'
    )


# ---------------------------------------------------------------------------
# Panel "¿Qué pasó el [fecha]"
# ---------------------------------------------------------------------------


def _day_health_row(
    db_path: str, fecha_iso: str, record_type: str, value_path: str
) -> float | None:
    """Valor diario de una métrica de salud para una fecha concreta."""
    with read_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT {value_path} AS valor
            FROM health_records
            WHERE record_type = ?
              AND date(start_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND deleted_at IS NULL
            ORDER BY start_epoch_ms DESC
            LIMIT 1
            """,
            (record_type, fecha_iso),
        ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _day_sleep_prev_night(db_path: str, fecha_iso: str) -> float | None:
    """Horas de sueño de la noche anterior (sesión que termina el día)."""
    with read_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT SUM(end_epoch_ms - start_epoch_ms) / 3600000.0
            FROM health_records
            WHERE record_type = 'SLEEP_SESSION'
              AND date(end_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND deleted_at IS NULL
            """,
            (fecha_iso,),
        ).fetchone()
    return round(float(row[0]), 1) if row and row[0] is not None else None


def _day_fc_media(db_path: str, fecha_iso: str) -> float | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT AVG(json_extract(s.value, '$.bpm'))
            FROM health_records h, json_each(h.value_json, '$.samples') s
            WHERE h.record_type = 'HEART_RATE_5MIN'
              AND date(h.start_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND h.deleted_at IS NULL
            """,
            (fecha_iso,),
        ).fetchone()
    return round(float(row[0])) if row and row[0] is not None else None


def _day_cardio(db_path: str, fecha_iso: str) -> list[DayDetailCardio]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT h.hc_id,
                   json_extract(h.value_json, '$.title') AS titulo,
                   (h.end_epoch_ms - h.start_epoch_ms) / 60000.0 AS duracion_min,
                   a.velocidad_kmh,
                   a.inclinacion_pct,
                   COALESCE(a.notas, '')
            FROM health_records h
            LEFT JOIN cardio_annotations a ON a.hc_id = h.hc_id
            WHERE h.record_type = 'EXERCISE_SESSION'
              AND date(h.start_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND h.deleted_at IS NULL
            ORDER BY h.start_epoch_ms
            """,
            (fecha_iso,),
        ).fetchall()
    return [
        DayDetailCardio(
            hc_id=r[0],
            titulo=r[1] or "Sesión de ejercicio",
            duracion_min=round(float(r[2]), 1),
            velocidad_kmh=float(r[3]) if r[3] is not None else None,
            inclinacion_pct=float(r[4]) if r[4] is not None else None,
            notas=str(r[5] or ""),
        )
        for r in rows
    ]


def _day_nutrition(db_path: str, fecha_iso: str) -> dict[str, float]:
    rows = get_diario_by_fecha(db_path, fecha_iso)
    totals = diary_totals(rows)
    params = get_parametros_diarios(db_path, fecha_iso) or {}
    defaults = {
        "peso_kg": 70.0,
        "factor_proteina": 1.5,
        "factor_grasa": 1.1,
        "kcal_objetivo": 2300.0,
        "fibra_objetivo": 0.0,
        "hierro_objetivo": 0.0,
        "calcio_objetivo": 0.0,
        "vitamina_c_objetivo": 0.0,
        "vitamina_a_objetivo": 0.0,
    }
    objetivo = objetivos_diarios({**defaults, **{k: float(v) for k, v in params.items()}})
    consumido = {k: round(float(totals.get(k, 0.0) or 0.0), 1) for k in objetivo}
    return {
        "kcal_consumido": consumido.get("kcal", 0.0),
        "kcal_objetivo": round(float(objetivo.get("kcal", 0.0)), 1),
        "proteina_consumido": consumido.get("proteina", 0.0),
        "proteina_objetivo": round(float(objetivo.get("proteina", 0.0)), 1),
        "grasa_consumido": consumido.get("grasa", 0.0),
        "grasa_objetivo": round(float(objetivo.get("grasa", 0.0)), 1),
        "carbohidratos_consumido": consumido.get("carbohidratos", 0.0),
        "carbohidratos_objetivo": round(float(objetivo.get("carbohidratos", 0.0)), 1),
        "fibra_consumido": consumido.get("fibra", 0.0),
        "fibra_objetivo": round(float(objetivo.get("fibra", 0.0)), 1),
    }


def build_day_detail(
    db_path: str, fecha_iso: str, nivel: str, focus: str | None
) -> DayDetailViewModel:
    """Panel '¿qué pasó': entreno del día (filtrado por nivel), nutrición y
    recuperación (sueño anoche, FC media, HRV, cardio + anotaciones)."""
    fecha_db = fecha_to_db(parse_form_date(fecha_iso))
    sets_rows = get_sets_by_fecha(db_path, fecha_db)

    # Filtro por nivel para el bloque de entrenamiento.
    if focus and nivel in ("grupo", "musculo"):
        with read_connection(db_path) as conn:
            if nivel == "grupo":
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(categoria) = LOWER(?)",
                    (focus,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                    (focus,),
                ).fetchall()
        targets = {str(r[0]).lower() for r in rows}
        sets_rows = [r for r in sets_rows if str(r["ejercicio"]).lower() in targets]
    elif focus and nivel == "ejercicio":
        sets_rows = [r for r in sets_rows if str(r["ejercicio"]).lower() == focus.lower()]

    sets = [
        DayDetailSet(
            ejercicio=r["ejercicio"],
            kg=float(r["kg"]) if r["kg"] is not None else None,
            reps=float(r["reps"]) if r["reps"] is not None else None,
            rir=float(r["rir"]) if r["rir"] is not None else None,
            descanso_seg=float(r["descanso_seg"]) if r["descanso_seg"] is not None else None,
            rm_ajustado=(
                round(rm_ajustado(float(r["kg"]), float(r["reps"]), float(r["rir"]) or 0.0), 1)
                if r["kg"] is not None and r["reps"] is not None
                else None
            ),
            fallo=(
                (float(r["rir"]) <= 0 if r["rir"] is not None else False)
                or (float(r["reps"]) % 1 != 0 if r["reps"] is not None else False)
            ),
            forzada=bool(r["rir"] is not None and float(r["rir"]) < 0),
        )
        for r in sets_rows
    ]

    timeline = calculate_pfr_timeline(db_path, _filter_type(nivel), focus)
    pfr = None
    volumen = None
    sets_fallo = 0
    if not timeline.empty:
        day = timeline[timeline["fecha_dt"] == fecha_iso]
        if not day.empty:
            row = day.iloc[0]
            pfr = round(float(row["rendimiento"]), 1) if pd.notna(row["rendimiento"]) else None
            if "sets_fallo" in row:
                sets_fallo = int(row["sets_fallo"]) if pd.notna(row["sets_fallo"]) else 0
    volume_df = daily_volume(db_path)
    if not volume_df.empty:
        vol = volume_df[volume_df["fecha_dt"] == fecha_iso]
        if not vol.empty:
            volumen = round(float(vol.iloc[0]["valor"]), 1)

    params = get_parametros_diarios(db_path, fecha_iso) or {}
    peso = float(params["peso_kg"]) if params.get("peso_kg") else None

    return DayDetailViewModel(
        fecha_iso=fecha_iso,
        nivel=nivel,
        focus=focus,
        sets=sets,
        has_entreno=bool(sets),
        pfr=pfr,
        volumen=volumen,
        sets_fallo=sets_fallo,
        nutrientes=_day_nutrition(db_path, fecha_iso),
        peso=peso,
        sueno=_day_sleep_prev_night(db_path, fecha_iso),
        fc_media=_day_fc_media(db_path, fecha_iso),
        hrv=_day_health_row(
            db_path,
            fecha_iso,
            "HEART_RATE_VARIABILITY_RMSSD",
            "AVG(json_extract(value_json, '$.rmssd_ms'))",
        ),
        cardio=_day_cardio(db_path, fecha_iso),
    )
