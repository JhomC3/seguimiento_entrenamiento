"""Dashboard orchestration: DB-backed view building and safe error translation.

Pure orchestration: no HTTP, no template rendering. Handlers stay thin.
"""

import logging
from datetime import date, datetime, timedelta

from src.charts import chart_pfr_timeline
from src.db_connection import read_connection
from src.models import ConflictError, NotFoundError, ValidationError
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_to_db,
    parse_form_date,
)
from src.view_models import DateDay, DateNavigatorViewModel, EditorRow, SessionEditorViewModel

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
    except Exception:
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
    except Exception:
        logger.exception("No se pudieron cargar los ejercicios del grupo %s", grupo)
        return []


def fechas_con_datos(db_path: str) -> set[str]:
    with read_connection(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT fecha FROM training_sets").fetchall()
    out: set[str] = set()
    for (f,) in rows:
        try:
            out.add(datetime.strptime(f, "%d/%m/%y").date().strftime("%Y-%m-%d"))
        except ValueError:
            continue
    return out


def chart_html(
    db_path: str, filter_type: str, filter_value: str | None = None, title: str = ""
) -> str:
    fig = chart_pfr_timeline(db_path, filter_type, filter_value, title)
    if fig.data:
        return fig.to_html(
            include_plotlyjs=False, full_html=False, config={"displayModeBar": False}
        )
    return "<div class='flex items-center justify-center h-[300px] text-neutral-500 text-xs'>Sin datos</div>"


def _end_of_next_month(d: date) -> date:
    next_year = d.year + (d.month + 1) // 12
    next_month = (d.month + 1) % 12 + 1
    return date(next_year, next_month, 1) - timedelta(days=1)


def build_date_navigator(
    db_path: str, fecha_iso: str, ciclo_start: date, today: date
) -> DateNavigatorViewModel:
    selected = parse_form_date(fecha_iso)
    data_dates = fechas_con_datos(db_path)
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
                rm = round(kg * (1 + 0.0333 * (reps + 1 + (rir or 0.0))), 1)
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
    from src.database import get_exercises_catalog, get_sets_by_fecha

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
        fecha_db=fecha_to_db(fecha),
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
