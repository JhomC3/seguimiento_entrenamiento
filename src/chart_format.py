"""Formato, tooltip, hover, RIR y color de graficas (spec 008)."""

from datetime import date as _date

import pandas as pd
import plotly.graph_objects as go

from src.design_tokens import color, palette
from src.models import ValidationError
from src.summary_service import (
    aggregate_sets,
    totals_by_period,
    week_start_date,
)

# UX-2: el tooltip se renderiza en cliente (chart-interaction.js) desde el
# customdata del servidor. La traza no define hovertemplate: se pasa
# hoverinfo='none' en el render cliente para suprimir el tooltip nativo de
# Plotly conservando los eventos plotly_hover/unhover (verificado en spike:
# hoverinfo:'none' solo no basta si un hovertemplate queda activo).
#
# Contrato de customdata (INMUTABLE, 9 posiciones — lo consume también la
# comparación de puntos): 1 etiqueta · 2 Δ · 3 series · 4 reps · 5 peso ·
# 6 RIR · 7 RM aj. · 8 cobertura (viaja, no se muestra) · 9 nombre.


def _fmt_num(value: float | None, decimals: int = 1) -> str:
    """Número redondeado para hover; None/NaN → '—' (ausencia, nunca 0)."""
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    return f"{round(float(value), decimals)}"


def _fmt_delta(pct: float | None) -> str:
    """Δ con signo explícito; 0.0% neutro; None → '—'."""
    if pct is None:
        return "—"
    v = round(float(pct), 1)
    if v > 0:
        return f"+{v}%"
    if v < 0:
        return f"{v}%"
    return "0.0%"


# --- TAREA 3: helpers de comparación compacta (testeables, sin tocar métricas) ---

_MESES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def format_day_short(iso_date: str, all_dates: list[str] | None = None) -> str:
    """Etiqueta compacta de día: '18 jul' o '18 jul 26' si hay >1 año.

    iso_date: 'YYYY-MM-DD'. all_dates: opcional para decidir si añade año corto.
    """
    try:
        y_str, m_str, d_str = str(iso_date).split("-")
        _, m, d = int(y_str), int(m_str), int(d_str)
    except Exception:  # noqa: BLE001
        return str(iso_date)
    mes = _MESES_CORTO[m - 1] if 1 <= m <= 12 else m_str
    base = f"{d} {mes}"
    # Año solo si hay ambigüedad entre años en el conjunto visible.
    if all_dates is not None:
        years = set()
        for v in all_dates:
            try:
                years.add(str(v).split("-")[0])
            except Exception:  # noqa: BLE001, S112
                continue
        if len(years) > 1:
            base += f" {y_str[2:]}"
    return base


def format_week_short(semana: int | str) -> str:
    """Etiqueta compacta de semana: 'S1', 'S14'."""
    try:
        return f"S{int(str(semana).strip())}"
    except Exception:  # noqa: BLE001
        return f"S{semana}"


def format_month_short(periodo: str) -> str:
    """Etiqueta compacta de mes: '01-26' desde '2026-01' o '2026-01-15'."""
    try:
        s = str(periodo).strip()
        # acepta 'YYYY-MM' o 'YYYY-MM-DD' o 'YYYY-MM' con separador '-'
        parts = s.split("-")
        y = int(parts[0])
        m = int(parts[1])
        return f"{m:02d}-{str(y)[2:]}"
    except Exception:  # noqa: BLE001
        return str(periodo)


def _month_tick_label(periodo: object) -> str:
    """Formatea ticks mensuales tanto en clave ``YYYYMM`` como ``YYYY-MM``."""
    value = str(periodo)
    if "-" in value:
        return format_month_short(value)
    if len(value) == 6 and value.isdigit():
        return format_month_short(f"{value[:4]}-{value[4:]}")
    return value


def extract_point_values(customdata: list | tuple | None) -> dict | None:
    """Extrae los valores visibles del customdata canónico (8 u 9 posiciones).

    8 pos. (legado): [etiqueta, Δ, series, reps, peso, rir, rm, trace]
    9 pos. (actual): [etiqueta, Δ, series, reps, peso, rir, rm, cobertura, trace]
    Retorna None si incompleto.
    """
    if not isinstance(customdata, (list, tuple)):
        return None
    if len(customdata) == 8:
        try:
            return {
                "periodo": str(customdata[0]),
                "delta": str(customdata[1]),
                "series": str(customdata[2]),
                "reps": str(customdata[3]),
                "peso": str(customdata[4]),
                "rir": str(customdata[5]),
                "rm": str(customdata[6]),
                "trace": str(customdata[7]),
            }
        except Exception:  # noqa: BLE001
            return None
    if len(customdata) >= 9:
        try:
            return {
                "periodo": str(customdata[0]),
                "delta": str(customdata[1]),
                "series": str(customdata[2]),
                "reps": str(customdata[3]),
                "peso": str(customdata[4]),
                "rir": str(customdata[5]),
                "rm": str(customdata[6]),
                "cobertura": str(customdata[7]),
                "trace": str(customdata[8]),
            }
        except Exception:  # noqa: BLE001
            return None
    return None


def point_comparison_id(granularity: str, periodo: str, trace_name: str) -> str:
    """Identidad única por granularidad+periodo+traza (case-insensitive trace)."""
    return f"{str(granularity).lower()}|{str(periodo)}|{str(trace_name).strip().lower()}"  # noqa: RUF010


# --- UX-2: etiquetas de tooltip (presentación; no tocar las del panel) ---
#
# Día: "26 jul" · "26 jul 2026" si el conjunto visible abarca >1 año (año
#       completo, a diferencia del formato de 2 dígitos de la comparación).
# Semana: lunes de la semana del ciclo con año ("18 jul 2026").
# Mes: "julio 2026" (nombre completo, inequívoco).

_MESES_TOOLTIP = [
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


def _tooltip_day_label(iso_date: str, multi_year: bool) -> str:
    """'26 jul' o '26 jul 2026' desde 'YYYY-MM-DD'."""
    try:
        y_str, m_str, d_str = str(iso_date).split("-")
        m, d = int(m_str), int(d_str)
    except ValueError:
        return str(iso_date)
    mes = _MESES_TOOLTIP[m - 1] if 1 <= m <= 12 else m_str
    return f"{d} {mes} {y_str}" if multi_year else f"{d} {mes}"


def _tooltip_week_label(semana: int) -> str:
    """Lunes de la semana N del ciclo: '18 jul 2026'."""
    start = week_start_date(int(semana))
    mes = _MESES_TOOLTIP[start.month - 1]
    return f"{start.day} {mes} {start.year}"


def _tooltip_month_label(periodo: str) -> str:
    """'julio 2026' desde 'YYYY-MM'."""
    try:
        y_str, m_str = str(periodo).split("-")[:2]
        m = int(m_str)
    except ValueError:
        return str(periodo)
    mes = _MESES_TOOLTIP[m - 1] if 1 <= m <= 12 else m_str
    return f"{mes} {y_str}"


def tooltip_period_label(granularity: str, x_value, multi_year: bool = False) -> str:
    """Etiqueta de cabecera del tooltip UX-2 según granularidad.

    ``x_value`` es el valor crudo del eje X (ISO 'YYYY-MM-DD' en day, número
    de semana en week, 'YYYY-MM' en month). ``multi_year`` añade el año en day
    cuando el conjunto visible de fechas abarca más de un año.
    """
    if granularity == "day":
        return _tooltip_day_label(str(x_value), multi_year)
    if granularity == "week":
        try:
            return _tooltip_week_label(int(str(x_value).strip()))
        except (ValidationError, ValueError):
            return str(x_value)
    if granularity == "month":
        return _tooltip_month_label(str(x_value))
    return str(x_value)


def _hover_rows(
    df: pd.DataFrame,
    name: str,
    *,
    granularity: str = "week",
    multi_year: bool = False,
) -> list[list[str]]:
    """Construye las 9 posiciones canónicas del customdata por punto.

    1 etiqueta (formato tooltip UX-2) · 2 Δ · 3 series · 4 reps · 5 peso ·
    6 RIR · 7 RM aj. · 8 cobertura (viaja; NO se muestra en el tooltip) ·
    9 nombre. La cabecera del tooltip se deriva del periodo común (``pt.x``),
    no de esta etiqueta.
    """
    x_col = "semana" if granularity == "week" else "periodo"
    rows: list[list[str]] = []
    for _, r in df.iterrows():
        series_val = r.get("h_series")
        rows.append(
            [
                tooltip_period_label(granularity, r[x_col], multi_year),
                _fmt_delta(r.get("crecimiento")),
                "—" if series_val is None or pd.isna(series_val) else str(int(series_val)),
                _fmt_num(r.get("h_reps")),
                _fmt_num(r.get("h_peso")),
                _fmt_num(r.get("h_rir")),
                _fmt_num(r.get("h_rm")),
                _fmt_num(r.get("h_cobertura"), 0),
                name,
            ]
        )
    return rows


RIR_TRACE_NAME = "RIR"
RIR_LINE_ALPHA = 0.35


def _pooled_rir_by_key(
    db_path: str, musculos: list[str], ejercicios: list[str], granularity: str
) -> dict[int, float]:
    """RIR medio pooled por periodo para el ámbito seleccionado.

    Reutiliza el camino ÚNICO (aggregate_sets → totals_by_period): misma
    población y misma semántica que el hover (RIR ausente cuenta como 0).
    Claves normalizadas por granularidad (ordinal / nº semana / YYYYMM),
    compatibles con el marco X de las trazas PFR.
    """
    aggs = aggregate_sets(db_path, list(musculos), list(ejercicios), granularity, None, None)
    return {key: totals.rir_medio for key, totals in totals_by_period(aggs).items()}


def _rir_trace(by_key: dict[int, float], granularity: str, multi_year: bool) -> go.Scatter | None:
    """Traza única de RIR medio sobre el eje Y derecho (discreta, al fondo).

    Blanco translúcido discontinuo: legible sin competir con las trazas de
    rendimiento. customdata de 9 pos. (contrato del tooltip cristal) con solo
    el RIR relleno; nombre "RIR". Sin datos → None (no se inventa).
    """
    if not by_key:
        return None
    keys = sorted(by_key)
    if granularity == "day":
        xs: list = [_date.fromordinal(k).isoformat() for k in keys]
    elif granularity == "month":
        xs = [f"{k // 100}-{k % 100:02d}" for k in keys]
    else:
        xs = keys
    ys = [by_key[k] for k in keys]
    labels = [tooltip_period_label(granularity, x, multi_year) for x in xs]
    customdata = [
        [label, "—", "—", "—", "—", _fmt_num(value, 1), "—", "—", RIR_TRACE_NAME]
        for label, value in zip(labels, ys)
    ]
    return go.Scatter(
        x=xs,
        y=ys,
        mode="lines",
        name=RIR_TRACE_NAME,
        yaxis="y2",
        line={
            "color": _hex_to_rgba(chart_color("hover.text"), RIR_LINE_ALPHA),
            "width": 2.5,
            "dash": "dash",
        },
        customdata=customdata,
    )


# Paleta para trazas por ejercicio (canonical: static/design-tokens.json)
EXERCISE_PALETTE = palette("chart.exercise")


def chart_color(path: str) -> str:
    """Color de gráfica desde los tokens canónicos ("chart.axes", "primary", ...)."""
    if path == "primary":
        path = "chart.primary"
    elif not path.startswith("chart."):
        path = f"chart.{path}"
    return color(path)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"
