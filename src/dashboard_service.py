"""Dashboard orchestration: DB-backed view building and safe error translation.

Pure orchestration: no HTTP, no template rendering. Handlers stay thin.
"""

import logging
import sqlite3
from datetime import date, timedelta

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


def chart_shell_html(title: str, fig, *, empty_text: str = "Sin datos") -> str:
    """Persistent chart shell: header + data div + plot div + empty div.

    Always outputs all four children (CLS 0): exactly one of plot/empty is
    visible (the other carries ``hidden``); the data div is always hidden.
    The client toggles visibility based on the JSON content.
    """
    header = (
        '<div id="unified-chart-header" class="flex items-baseline gap-2 min-w-0 pl-3 mb-3">'
        '<h2 class="text-sm font-black tracking-[0.2em] text-burgundy-400 uppercase neon-title truncate">Rendimiento</h2>'
        "</div>"
    )
    has_data = hasattr(fig, "data") and fig.data
    if has_data:
        data = _json_for_inline(fig.to_json())
        data_el = f'<div id="unified-chart-data" hidden>{data}</div>'
        plot_el = '<div id="unified-chart-plot" class="plotly-graph-div"></div>'
        empty_el = f'<div id="unified-chart-empty" class="chart-empty" hidden>{empty_text}</div>'
    else:
        data_el = '<div id="unified-chart-data" hidden>{}</div>'
        plot_el = '<div id="unified-chart-plot" class="plotly-graph-div" hidden></div>'
        empty_el = f'<div id="unified-chart-empty" class="chart-empty">{empty_text}</div>'
    return header + data_el + plot_el + empty_el


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
    granularity: str = "day",
    variant: str = "dashboard",
) -> DateNavigatorViewModel:
    """Navigator with a bounded 31-day window centered on the selection.

    La ventana se recorta a [ciclo_start, fin del mes siguiente a hoy]; el
    salto preciso (input date) y las flechas navegan el centro de la ventana.

    ``variant``: ``"dashboard"`` conserva el formato UX-3 (semana + fecha
    explícita con ``granularity``); ``"daily"`` usa etiquetas compactas
    (día, ``día/mes`` el primero de mes; aria ``dd/mm/aa``) sin la palabra
    "Semana", para la página independiente del Diario.
    """
    selected = parse_form_date(fecha_iso)
    data_dates = fechas_con_datos(db_path, grupo, ejercicio)
    end = _end_of_next_month(today)
    start = max(ciclo_start, selected - timedelta(days=15))
    limit_end = min(end, selected + timedelta(days=15))
    MONTHS_ES = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    dates = []
    d = start
    while d <= limit_end:
        iso = d.strftime("%Y-%m-%d")
        if variant == "daily":
            label = f"{d.day}/{d.month}" if d.day == 1 else str(d.day)
            aria_label = f"{d.day:02d}/{d.month:02d}/{d.year % 100:02d}"
        elif granularity == "day":
            semana = calculate_cycle_week(d, ciclo_start)
            label_visible = f"S{semana} \u00b7 {d.day:02d}-{d.month:02d}-{str(d.year)[2:]}"
            label_aria = f"Semana {semana} \u00b7 {d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"
            label = label_visible
            aria_label = label_aria
        else:
            label = f"{d.day}/{d.month}" if d.day == 1 else str(d.day)
            aria_label = label
        dates.append(
            DateDay(
                iso=iso,
                label=label,
                has_data=iso in data_dates,
                selected=d == selected,
                aria_label=aria_label,
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
