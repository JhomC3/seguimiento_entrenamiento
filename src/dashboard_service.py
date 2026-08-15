"""Dashboard orchestration: DB-backed view building and safe error translation.

Pure orchestration: no HTTP, no template rendering. Handlers stay thin.
"""

import html
import logging
import sqlite3
from datetime import date, timedelta

from config import CICLO_NUMERO
from src.charts import chart_pfr_timeline
from src.database import (
    get_alimentos_catalog,
    get_diario_by_fecha,
    get_exercises_catalog,
    get_parametros_diarios,
    get_prev_diary_date,
    get_sets_by_fecha,
)
from src.db_connection import read_connection
from src.metrics_engine import rm_ajustado
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
    DateDay,
    DateNavigatorViewModel,
    EditorRow,
    NutritionEditorViewModel,
    NutritionEntryRow,
    SessionEditorViewModel,
)

logger = logging.getLogger("dashboard")

DOMAIN_ERRORS = (ValidationError, NotFoundError, ConflictError)


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


def _chart_header_html(title: str) -> str:
    """Header del panel de gráfica (título + ciclo). Compartido por chart_html
    y la selección de cascada para que ambos estados ocupen el mismo shell."""
    return (
        '<div class="flex items-baseline gap-2 min-w-0 pl-3 mb-3">'
        f'<h3 class="text-sm font-black tracking-[0.2em] text-burgundy-400 uppercase neon-title truncate">{html.escape(title)}</h3>'
        f'<span class="text-xs text-neutral-400 flex-none">Ciclo {CICLO_NUMERO}</span>'
        "</div>"
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
    header = _chart_header_html(title)
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
        + "<div class='flex items-center justify-center chart-empty text-neutral-400 text-xs'>Sin datos</div>"
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
        descanso = _as_float(r.get("descanso_seg"))
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
                descanso_seg=descanso,
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
