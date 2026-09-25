from datetime import date as _date

import pandas as pd
import plotly.graph_objects as go

from config import CICLO_NUMERO
from src.db_connection import read_connection
from src.design_tokens import color, palette
from src.metrics_engine import RM_FACTOR, calculate_pfr_timeline, rm_ajustado
from src.models import ValidationError
from src.summary_service import (
    _PeriodTotals,
    aggregate_sets,
    day_label,
    month_label,
    totals_by_period,
    week_label,
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


def _hover_totals_for(
    db_path: str, filter_type: str, filter_value: str | None, granularity: str
) -> dict[int, _PeriodTotals]:
    """Totales por periodo desde el camino compartido (summary_service).

    Reutiliza aggregate_sets + totals_by_period: cero SQL ni agregación
    duplicada. Devuelve {sort_key: _PeriodTotals}.
    """
    if filter_type == "muscle_group" and filter_value:
        muscles: tuple[str, ...] = (filter_value,)
        exercises: tuple[str, ...] = ()
    elif filter_type == "exercise" and filter_value:
        muscles = ()
        exercises = (filter_value,)
    else:
        muscles = ()
        exercises = ()
    aggs = aggregate_sets(db_path, muscles, exercises, granularity, None, None)
    return totals_by_period(aggs)


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


def get_exercise_raw_data(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna datos del ejercicio con contexto de posición y serie.

    La posición se deriva del orden de la primera serie de cada ejercicio en
    la sesión, de modo que ejercicios hechos en distinto estado de fatiga no
    se mezclen en la misma cohorte comparativa.
    """
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg
            FROM training_sets
            WHERE kg IS NOT NULL AND reps IS NOT NULL
            ORDER BY semana, fecha, set_orden
        """,
            conn,
        )

    if df.empty:
        return df

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    session_keys = ["semana", "fecha"]
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    first_order = df.groupby(session_keys + ["ejercicio"], as_index=False)["set_orden"].min()
    first_order["posicion_ejercicio"] = (
        first_order.groupby(session_keys)["set_orden"]
        .rank(method="dense", ascending=True)
        .astype(int)
    )
    df = df.merge(
        first_order.drop(columns=["set_orden"]),
        on=session_keys + ["ejercicio"],
        how="left",
    )
    df["serie"] = df.groupby(["semana", "fecha", "ejercicio"]).cumcount() + 1
    df = df[df["ejercicio"].str.lower() == ejercicio.lower()].copy()
    if df.empty:
        return df

    rir_safe = df["rir"].fillna(0)
    df["rm"] = (df["kg"] * (1 + RM_FACTOR * df["reps"])).round(1)
    # RM ajustado centralizado (única fuente: metrics_engine.rm_ajustado);
    # RIR ausente cuenta como 0 (semántica vigente del dominio).
    df["rm_ajustado"] = df.apply(
        lambda r: round(
            rm_ajustado(float(r["kg"]), float(r["reps"]), float(rir_safe.loc[r.name])), 1
        ),
        axis=1,
    )

    df = df.sort_values(["semana", "fecha_dt", "serie"]).reset_index(drop=True)
    return df[
        [
            "semana",
            "sesion",
            "serie",
            "fecha",
            "fecha_dt",
            "dia",
            "set_orden",
            "posicion_ejercicio",
            "kg",
            "reps",
            "rir",
            "descanso_seg",
            "rm",
            "rm_ajustado",
        ]
    ]


def get_exercise_cohort_summary(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Resume cohortes homogéneas: posición del ejercicio y serie ordinal.

    El baseline de cada cohorte es su primera observación cronológica. La
    mediana describe el nivel típico y reduce el efecto de una sesión atípica.
    """
    if raw_df.empty:
        return raw_df
    work = raw_df.sort_values(["fecha_dt", "serie"]).copy()
    rows: list[dict[str, object]] = []
    for (position, series), group in work.groupby(["posicion_ejercicio", "serie"], sort=True):
        group = group.sort_values("fecha_dt")
        baseline = float(group.iloc[0]["rm_ajustado"])
        current = float(group.iloc[-1]["rm_ajustado"])
        median = float(group["rm_ajustado"].median())
        rows.append(
            {
                "posicion_ejercicio": int(position),  # type: ignore[call-overload]
                "serie": int(series),  # type: ignore[call-overload]
                "observaciones": len(group),
                "baseline_rm": round(baseline, 1),
                "rm_mediana": round(median, 1),
                "rm_ultima": round(current, 1),
                "crecimiento_pct": round((current / baseline - 1) * 100, 1) if baseline else None,
                "ultima_fecha": group.iloc[-1]["fecha"],
            }
        )
    return pd.DataFrame(rows)


def _pfr_df(
    db_path: str, filter_type: str, filter_value: str | None, granularity: str = "week"
) -> pd.DataFrame:
    """DataFrame de rendimiento por periodo con columnas de hover.

    X/Y provienen de calculate_pfr_timeline (intacto). Las métricas del hover
    (series, reps/peso/RIR medios y RM máximo del periodo) vienen del camino
    ÚNICO de agregación en summary_service (aggregate_sets → totals_by_period).

    Columnas de hover: hlabel (etiqueta centralizada), h_series (int|None),
    h_reps/h_peso/h_rir/h_rm (float|None). None → '—' al renderizar.

    granularity: 'day' | 'week' | 'month'
    """
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return pd.DataFrame()

    totals = _hover_totals_for(db_path, filter_type, filter_value, granularity)

    def _key_for(row) -> int:
        if granularity == "day":
            return row["fecha_dt"].date().toordinal()
        if granularity == "month":
            return int(str(row["periodo"]).replace("-", "")[:6])
        return int(row["semana"])

    def _label_for(row) -> str:
        if granularity == "day":
            return day_label(row["fecha_dt"].date())
        if granularity == "month":
            iso = str(row["periodo"])
            return month_label(int(iso[:4]), int(iso[5:7]))
        return week_label(int(row["semana"]))

    def _totals_cols(row):
        t = totals.get(_key_for(row))
        if t is None or getattr(t, "series", 0) == 0:
            return pd.Series(
                {
                    "hlabel": _label_for(row),
                    "h_series": None,
                    "h_reps": None,
                    "h_peso": None,
                    "h_rir": None,
                    "h_rm": None,
                    "h_cobertura": None,
                }
            )
        return pd.Series(
            {
                "hlabel": t.label,
                "h_series": float(t.series),
                "h_reps": t.reps_media,
                "h_peso": t.peso_medio,
                "h_rir": t.rir_medio,
                "h_rm": t.rm_max,
                "h_cobertura": row.get("cobertura"),
            }
        )

    if granularity == "day":
        # calculate_pfr_timeline devuelve una cronología continua con los días de
        # descanso rellenados (rendimiento ffill, sets_totales=0). Solo mostramos
        # días con entrenamiento real: sin inventar puntos de descanso (req. 2-3).
        result = df[df["sets_totales"] > 0][
            ["fecha_dt", "rendimiento", "sets_totales", "cobertura"]
        ].copy()
        result = result.rename(columns={"sets_totales": "series"})
        result["periodo"] = result["fecha_dt"].dt.strftime("%Y-%m-%d")
        result = result.sort_values("periodo")
        result["crecimiento"] = result["rendimiento"] - 100
        result = pd.concat([result, result.apply(_totals_cols, axis=1)], axis=1)
        return result

    if granularity == "month":
        df["periodo"] = df["fecha_dt"].dt.to_period("M").astype(str)
        grouped = (
            df.groupby("periodo")
            .agg(
                rendimiento=("rendimiento", "mean"),
                series=("sets_totales", "sum"),
                cobertura=("cobertura", "mean"),
            )
            .reset_index()
            .sort_values("periodo")
        )
        grouped["crecimiento"] = grouped["rendimiento"] - 100
        grouped = pd.concat([grouped, grouped.apply(_totals_cols, axis=1)], axis=1)
        return grouped

    # Default: week (comportamiento original)
    weekly = (
        df.groupby("semana")
        .agg(
            rendimiento=("rendimiento", "mean"),
            series=("sets_totales", "sum"),
            cobertura=("cobertura", "mean"),
        )
        .reset_index()
        .dropna(subset=["semana"])
    )
    weekly["semana"] = weekly["semana"].astype(int)
    weekly = weekly.sort_values("semana")
    weekly["crecimiento"] = weekly["rendimiento"] - 100
    weekly["periodo"] = weekly["semana"].astype(str)
    weekly = pd.concat([weekly, weekly.apply(_totals_cols, axis=1)], axis=1)
    return weekly


# Legacy alias
def _weekly_pfr_df(db_path: str, filter_type: str, filter_value: str | None) -> pd.DataFrame:
    return _pfr_df(db_path, filter_type, filter_value, granularity="week")


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


def _compact_day_labels(periods: list[str]) -> list[str]:
    """Etiquetas compactas para gran=day.

    - Mismo mes: DD
    - Primer día de nuevo mes: DD/MM
    - Cambio de año: DD/MM/YY
    El valor interno sigue siendo YYYY-MM-DD; solo cambia ticktext.
    """
    labels: list[str] = []
    prev_y: str | None = None
    prev_m: str | None = None
    for p in periods:
        y, m, d = p.split("-")
        if prev_y is None:
            labels.append(d)
        elif y != prev_y:
            labels.append(f"{d}/{m}/{y[2:]}")
        elif m != prev_m:
            labels.append(f"{d}/{m}")
        else:
            labels.append(d)
        prev_y, prev_m = y, m
    return labels


def _day_tick_subset(periods: list[str], max_ticks: int = 8) -> tuple[list[str], list[str]]:
    """Subconjunto de ticks para no mostrar una etiqueta por punto.

    Usa tickmode array pero con un subconjunto espaciado; mantiene compactas.
    Si hay ≤ max_ticks puntos, muestra todos; si no, muestrea.
    """
    if len(periods) <= max_ticks:
        return periods, _compact_day_labels(periods)
    step = (len(periods) + max_ticks - 1) // max_ticks
    tickvals = periods[::step]
    # Asegurar que el último punto siempre esté etiquetado.
    if tickvals[-1] != periods[-1]:
        tickvals = [*tickvals[:-1], periods[-1]]
    ticktext = _compact_day_labels(tickvals)
    return tickvals, ticktext


def _x_key(value, granularity: str):
    """Clave de comparación NORMALIZADA por granularidad, compartida entre el
    rango X inicial y el filtro de puntos visibles.

    - day: fecha ISO (str) — lexicográfica == cronológica.
    - week: número de semana (int).
    - month: YYYYMM (int) — sin ambigüedad de string 'YYYY-MM' (cruce de año OK).
    """
    if granularity == "week":
        return int(value)
    if granularity == "month":
        return int(str(value).replace("-", "")[:6])
    return str(value)


def _initial_x_range(x_values: list, granularity: str) -> list | None:
    """Ventana temporal inicial del eje X (solo presentación: los datos completos
    permanecen en la figura y el usuario puede hacer pan/zoom hacia atrás).

    - day: últimos 2 meses naturales disponibles (fin = última fecha con datos).
    - week: últimas 15 semanas disponibles.
    - month: últimos 12 meses disponibles.
    Si los datos cubren menos que la ventana, devuelve None → Plotly muestra todo.

    Valores devueltos: claves NORMALIZADAS por granularidad (ISO str para day,
    int para week, YYYYMM int para month) — compatibles con `_y_visible_in_window`
    y convertibles a la representación del eje por `_range_for_axis`.
    """
    if not x_values or granularity not in ("day", "week", "month"):
        return None

    if granularity == "day":
        xs = sorted({str(v) for v in x_values})
        end = pd.Timestamp(xs[-1])
        # Restar 2 meses de calendario (aritmética año*12+mes, clamp a fin de mes).
        total = end.year * 12 + (end.month - 1) - 2
        y2, m0 = divmod(total, 12)
        m2 = m0 + 1
        try:
            start = pd.Timestamp(year=y2, month=m2, day=end.day)
        except ValueError:
            start = pd.Timestamp(year=y2, month=m2, day=28) + pd.offsets.MonthEnd(0)
        start_iso = start.strftime("%Y-%m-%d")
        if xs[0] >= start_iso:
            return None
        return [start_iso, xs[-1]]

    nums = sorted({_x_key(v, granularity) for v in x_values})
    span = {"week": 15, "month": 12}[granularity]
    if len(nums) <= span:
        return None
    return [nums[-span], nums[-1]]


def _range_for_axis(x_range: list, granularity: str) -> list:
    """Convierte las claves normalizadas de _initial_x_range a la representación
    del eje X en la figura (day: ISO; week: str(posición); month: 'YYYY-MM').

    Solo para day se añade padding visual de ~1 día antes y después para
    separar el primer/último punto del borde del plot; no inventa datos ni
    afecta al cálculo de y_visible.
    """
    if granularity == "day":
        # Padding simétrico de 1 día para day; funciona con 1 punto.
        try:
            start = (pd.Timestamp(x_range[0]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            end = (pd.Timestamp(x_range[1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            return [start, end]
        except Exception:  # noqa: BLE001
            return list(x_range)
    if granularity == "week":
        return [str(v) for v in x_range]
    return [f"{v // 100}-{v % 100:02d}" for v in x_range]


def _y_visible_in_window(
    x_values: list, y_values: list, x_range: list | None, granularity: str
) -> list:
    """Devuelve los valores Y de puntos cuyo X cae dentro de la ventana inicial.

    - Sin ventana (None) → todos los Y (datos insuficientes o ventana completa).
    - Comparación NORMALIZADA por granularidad mediante _x_key (ISO para day,
      int para week, YYYYMM int para month) — el rango y el filtro comparten la
      misma representación, sin ambigüedad de strings.
    - Los puntos fuera de la ventana NO influyen en el rango Y inicial, pero la
      traza conserva todos sus puntos para pan/zoom hacia atrás.
    """
    if x_range is None or not y_values:
        return [v for v in y_values if v is not None]
    lo = _x_key(x_range[0], granularity)
    hi = _x_key(x_range[1], granularity)
    out: list[float] = []
    for x, y in zip(x_values, y_values):
        if y is None:
            continue
        k = _x_key(x, granularity)
        if lo <= k <= hi:
            out.append(y)
    return out


def _multi_year_flag(df: pd.DataFrame, granularity: str) -> bool:
    """True si el conjunto de periodos abarca más de un año (solo day).

    Se calcula a nivel de FIGURA (todas las trazas comparten el mismo flag)
    para que la etiqueta de un mismo x sea idéntica en cualquier traza.
    """
    if granularity != "day" or df.empty or "periodo" not in df.columns:
        return False
    years = {str(v)[:4] for v in df["periodo"]}
    return len(years) > 1


def _pfr_trace(
    df: pd.DataFrame,
    name: str,
    color: str,
    *,
    alpha: float = 1.0,
    width: float = 2.5,
    marker_size: int = 3,
    granularity: str = "week",
    multi_year: bool = False,
) -> go.Scatter:
    # Eje X y etiqueta de periodo según granularidad: la serie semanal conserva
    # `semana`; day y month usan `periodo` (fecha/label cronológico real).
    x_col = "semana" if granularity == "week" else "periodo"

    line_color = color if alpha >= 1.0 else _hex_to_rgba(color, alpha)
    customdata = _hover_rows(df, name, granularity=granularity, multi_year=multi_year)
    return go.Scatter(
        x=df[x_col],
        y=df["crecimiento"],
        mode="lines",
        name=name,
        line={"color": line_color, "width": width, "dash": "solid"},
        customdata=customdata,
    )


def chart_selection(
    db_path: str,
    musculos: list[str],
    ejercicios: list[str],
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de la selección actual:

    - 0 músculos: línea sistémica global ("Global").
    - 1 músculo, 0 ejercicios: Global + nombre del músculo.
    - 1 músculo, N ejercicios válidos: músculo (guía, UX-2: sin "Compilado")
      + ejercicios. (Global se oculta en estado ejercicio — decisión D2.)
    - 2+ músculos: Global + músculos. Los ejercicios no aplican.

    Los ejercicios que no pertenecen al músculo se descartan.

    En todos los estados se añade la traza "RIR" (RIR medio pooled del ámbito
    seleccionado, eje Y derecho, blanco translúcido discontinuo): existe
    siempre que el ámbito tenga series.
    """
    traces: list[go.Scatter] = []
    title = "Rendimiento – Cuerpo entero"
    # The systemic series provides a stable vertical reference. Selection
    # changes may add traces outside this window, but must never resize or
    # vertically reposition the chart shell.
    reference_df = _pfr_df(db_path, "systemic", None, granularity)
    # Flag de figura (no de traza): todas las trazas etiquetan un mismo x con
    # el mismo formato (año completo en day solo si el dataset abarca >1 año).
    multi_year = _multi_year_flag(reference_df, granularity)
    # Ámbito del RIR: sigue a la selección como las trazas PFR.
    rir_scope: tuple[list[str], list[str]] = ([], [])

    if len(musculos) == 0:
        # Estado global: línea sistémica (D3).
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df,
                    "Global",
                    chart_color("primary"),
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )
    elif len(musculos) == 1:
        musculo = musculos[0]
        title = f"Rendimiento – {musculo}"

        if ejercicios:
            # Estado ejercicio: el músculo guía (UX-2) + ejercicios (sin global — D2).
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                traces.append(
                    _pfr_trace(
                        compiled,
                        musculo,
                        chart_color("primary"),
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )

            with read_connection(db_path) as conn:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                    (musculo,),
                ).fetchall()
            valid = {str(r[0]).lower() for r in rows}
            rir_scope = ([musculo], [e for e in ejercicios if e.lower() in valid])
            for idx, ejercicio in enumerate(ejercicios):
                if ejercicio.lower() not in valid:
                    continue
                df = _pfr_df(db_path, "exercise", ejercicio, granularity)
                if df.empty:
                    continue
                color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
                traces.append(
                    _pfr_trace(
                        df,
                        ejercicio,
                        color,
                        alpha=0.4,
                        width=3.5,
                        marker_size=3,
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
        else:
            # Estado muscular: misma jerarquía que 2+ músculos:
            # Global sólido + músculo identificado y translúcido.
            rir_scope = ([musculo], [])
            global_df = _pfr_df(db_path, "systemic", None, granularity)
            if not global_df.empty:
                traces.append(
                    _pfr_trace(
                        global_df,
                        "Global",
                        chart_color("primary"),
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                color = EXERCISE_PALETTE[0]
                traces.append(
                    _pfr_trace(
                        compiled,
                        musculo,
                        color,
                        alpha=0.4,
                        width=3.5,
                        marker_size=3,
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
    elif len(musculos) >= 2:
        rir_scope = (list(musculos), [])
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df,
                    "Global",
                    chart_color("primary"),
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )
        for idx, musculo in enumerate(musculos):
            df = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            traces.append(
                _pfr_trace(
                    df,
                    musculo,
                    color,
                    alpha=0.4,
                    width=3.5,
                    marker_size=3,
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )

    if not traces:
        return go.Figure()

    fig = go.Figure()
    for t in traces:
        fig.add_trace(t)

    # Eje X primero: la ventana temporal inicial determina qué puntos visibles
    # condicionan el rango Y (los históricos fuera de la ventana permanecen en
    # la traza para pan/zoom, pero no afectan la escala vertical inicial).
    all_x = [v for t in traces for v in t.x]
    initial_range = _initial_x_range(all_x, granularity)

    y_visible: list[float] = []
    for t in traces:
        y_visible.extend(_y_visible_in_window(list(t.x), list(t.y), initial_range, granularity))
    ref_x_col = "semana" if granularity == "week" else "periodo"
    reference_y = _y_visible_in_window(
        list(reference_df[ref_x_col]),
        list(reference_df["crecimiento"]),
        initial_range,
        granularity,
    )
    # El rango Y incluye todas las series visibles en la ventana (Global,
    # músculos y ejercicios) más la línea base 0: ningún punto visible queda cortado.
    scale_vals = y_visible + reference_y + [0.0]
    y_min = min(scale_vals)
    y_max = max(scale_vals)
    # Margen por lado, proporcional a la extensión de cada lado desde 0: así la
    # línea 0 queda visible con un margen pequeño sin inflar huecos (p. ej. un
    # baseline ~0 apenas añade margen superior aunque el mínimo sea muy negativo).
    flat = y_max == y_min
    extent_hi = max(0.0, y_max)
    extent_lo = max(0.0, -y_min)
    y_padding_hi = extent_hi * 0.15 if extent_hi > 0 else (5 if flat else 0)
    y_padding_lo = extent_lo * 0.15 if extent_lo > 0 else (5 if flat else 0)
    y_bottom = min(0.0, y_min) - y_padding_lo
    y_top = max(0.0, y_max) + y_padding_hi

    # RIR medio del ámbito seleccionado: traza única sobre el eje derecho.
    # Fuera de la escala Y principal a propósito (unidades distintas); existe
    # siempre que el ámbito tenga series (ausente = 0, como el hover).
    rir = _rir_trace(_pooled_rir_by_key(db_path, *rir_scope, granularity), granularity, multi_year)
    rir_range: list | None = None
    if rir is not None:
        fig.add_trace(rir)
        rir_range = _tight_range(
            [
                float(v)
                for v in _y_visible_in_window(list(rir.x), list(rir.y), initial_range, granularity)
                if v is not None and not pd.isna(v)
            ],
            0.15,
            0.5,
        )

    # Eje X: tickmode array con subconjunto para no apiñar (day: máx 8 etiquetas)
    if granularity == "day":
        all_periods = sorted({str(v) for v in all_x})
        tickvals, ticktext = _day_tick_subset(all_periods, max_ticks=8)
    elif all_x and isinstance(all_x[0], int):
        tickvals = sorted(set(all_x))
        ticktext = [_month_tick_label(v) for v in tickvals]
    else:
        tickvals = sorted({str(v) for v in all_x})
        ticktext = [str(v) for v in tickvals]

    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": tickvals,
        "ticktext": ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    # Tipo de eje explícito por granularidad: date para day, category para
    # week y month (las claves normalizadas se convierten a la representación
    # del eje con _range_for_axis; sin ambigüedad de tipo).
    xaxis_cfg["type"] = "date" if granularity == "day" else "category"
    if initial_range:
        xaxis_cfg["range"] = _range_for_axis(initial_range, granularity)

    fig.update_layout(
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
        yaxis={
            "range": [y_bottom, y_top],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=450,
        # Sin leyenda ni títulos: el tooltip cristal es el único identificador
        # de traza. La estabilidad del shell entre estados la dan los márgenes
        # y la altura idénticos (ver test_chart_layout_estable_entre_estados).
        # r44 reserva sitio a los ticks del eje RIR derecho.
        margin={"l": 48, "r": 44, "t": 20, "b": 28},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        showlegend=False,
        dragmode="pan",
        **(
            {
                "yaxis2": {
                    "overlaying": "y",
                    "side": "right",
                    "showgrid": False,
                    "zeroline": False,
                    "tickfont": {"color": chart_color("axes")},
                    **({"range": rir_range} if rir_range is not None else {}),
                }
            }
            if rir is not None
            else {}
        ),
    )
    return fig


def chart_pfr_timeline(
    db_path: str,
    filter_type: str,
    filter_value: str | None = None,
    title: str = f"Rendimiento – Ciclo {CICLO_NUMERO}",
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de crecimiento vs baseline (semana 1 = 0).

    El hover resume el periodo: series, sets al fallo, volumen, peso y sueño.
    """
    periodic = _pfr_df(db_path, filter_type, filter_value, granularity)
    if periodic.empty:
        return go.Figure()

    # Eje X (sin título: la granularidad la indica el selector visible)
    x_col = "periodo" if "periodo" in periodic.columns else "semana"

    # Ventana temporal inicial antes del rango Y: solo los puntos dentro de la
    # ventana visible condicionan la escala vertical (los históricos permanecen
    # en la traza para pan/zoom, pero no afectan el rango Y inicial).
    initial_range = _initial_x_range(periodic[x_col].tolist(), granularity)
    y_visible = _y_visible_in_window(
        list(periodic[x_col]),
        list(periodic["crecimiento"]),
        initial_range,
        granularity,
    )
    scale_vals = y_visible + [0.0]
    y_min = min(scale_vals)
    y_max = max(scale_vals)
    # Margen por lado proporcional a la extensión desde 0 (línea base siempre
    # visible con un margen pequeño, sin inflar huecos; fallback 5 solo si plano).
    flat = y_max == y_min
    extent_hi = max(0.0, y_max)
    extent_lo = max(0.0, -y_min)
    y_padding_hi = extent_hi * 0.15 if extent_hi > 0 else (5 if flat else 0)
    y_padding_lo = extent_lo * 0.15 if extent_lo > 0 else (5 if flat else 0)
    y_bottom = min(0.0, y_min) - y_padding_lo
    y_top = max(0.0, y_max) + y_padding_hi

    fig = go.Figure()

    multi_year = _multi_year_flag(periodic, granularity)
    if granularity == "day":
        periods = [str(v) for v in periodic[x_col].tolist()]
        tickvals, ticktext = _day_tick_subset(periods, max_ticks=8)
        customdata_vals = _hover_rows(
            periodic, "Global", granularity=granularity, multi_year=multi_year
        )
        x_tickvals = tickvals
        x_ticktext = ticktext
    else:
        x_tickvals = periodic[x_col].tolist()
        x_ticktext = (
            [_month_tick_label(v) for v in periodic[x_col]]
            if granularity == "month"
            else [str(v) for v in periodic[x_col]]
        )
        customdata_vals = _hover_rows(periodic, "Global", granularity=granularity)

    fig.add_trace(
        go.Scatter(
            x=periodic[x_col],
            y=periodic["crecimiento"],
            mode="lines",
            name="Global",
            line={"color": chart_color("primary"), "width": 2.5, "dash": "solid"},
            customdata=customdata_vals,
        )
    )

    # RIR medio del filtro en el eje derecho (mismo criterio que chart_selection).
    if filter_type == "muscle_group" and filter_value:
        _rir_scope: tuple[list[str], list[str]] = ([filter_value], [])
    elif filter_type == "exercise" and filter_value:
        _rir_scope = ([], [filter_value])
    else:
        _rir_scope = ([], [])
    rir = _rir_trace(_pooled_rir_by_key(db_path, *_rir_scope, granularity), granularity, multi_year)
    rir_range: list | None = None
    if rir is not None:
        fig.add_trace(rir)
        rir_range = _tight_range(
            [
                float(v)
                for v in _y_visible_in_window(list(rir.x), list(rir.y), initial_range, granularity)
                if v is not None and not pd.isna(v)
            ],
            0.15,
            0.5,
        )

    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": x_tickvals,
        "ticktext": x_ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    # Tipo de eje explícito por granularidad (date/category).
    xaxis_cfg["type"] = "date" if granularity == "day" else "category"
    # Ventana temporal inicial (solo presentación; todos los datos quedan en la
    # figura y el usuario puede navegar hacia atrás con pan/zoom).
    if initial_range:
        xaxis_cfg["range"] = _range_for_axis(initial_range, granularity)

    fig.update_layout(
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
        yaxis={
            "range": [y_bottom, y_top],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=450,
        # Sin leyenda ni títulos: el tooltip cristal es el único identificador
        # de traza; la unidad % vive en tooltip e Historial. Estabilidad entre
        # estados por márgenes/altura idénticos (ver test de layout estable).
        # r44 reserva sitio a los ticks del eje RIR derecho.
        margin={"l": 48, "r": 44, "t": 20, "b": 28},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        showlegend=False,
        dragmode="pan",
        **(
            {
                "yaxis2": {
                    "overlaying": "y",
                    "side": "right",
                    "showgrid": False,
                    "zeroline": False,
                    "tickfont": {"color": chart_color("axes")},
                    **({"range": rir_range} if rir_range is not None else {}),
                }
            }
            if rir is not None
            else {}
        ),
    )

    return fig


def _tight_range(values: list[float], rel_pad: float, abs_min_pad: float) -> list | None:
    """Rango Y ajustado a los datos visibles, sin forzar el 0.

    ``rel_pad``: fracción del span como margen por lado; ``abs_min_pad``:
    suelo del margen para rachas planas (span 0). Vacío → None (autoscala).
    """
    if not values:
        return None
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * rel_pad, abs_min_pad)
    return [lo - pad, hi + pad]


def chart_metrics_index(
    df: pd.DataFrame,
    granularity: str = "day",
    selection: tuple[str, ...] = (),
) -> go.Figure:
    """Índice 0–100 de métricas (una traza por serie).

    ``df`` es la salida de ``build_metrics_index`` (valores CRUDOS). Cada serie
    se normaliza con ``normalize_01_100`` (recovery: clip); el tooltip lleva el
    valor real + unidad (customdata 2-pos). ``selection`` marca visibles (el
    resto viaja oculto para toggles instantáneos sin refetch).
    Sin series con datos → ``go.Figure()``.
    """
    from src.health_panels import METRIC_DISPLAY, METRIC_ORDER, SERIES, normalize_01_100

    if df.empty:
        return go.Figure()
    x_col = "fecha" if "fecha" in df.columns else "periodo"
    if x_col not in df.columns:
        return go.Figure()
    keys = [k for k in METRIC_ORDER if k in df.columns and df[k].notna().any()]
    if not keys:
        return go.Figure()
    work = df.dropna(subset=[x_col]).reset_index(drop=True)
    x_values = [str(v) for v in work[x_col].tolist()]
    years = {v[:4] for v in x_values}
    multi_year = len(years) > 1
    label_gran = "day" if granularity in ("day", "week") else "month"

    fig = go.Figure()
    for i, key in enumerate(keys):
        label, unit = METRIC_DISPLAY.get(key, (SERIES[key][0], SERIES[key][1]))
        color = EXERCISE_PALETTE[i % len(EXERCISE_PALETTE)]
        raw = work[key].tolist()
        norm = normalize_01_100(work[key], already_01_100=(key == "recovery"))
        customdata = [
            [
                tooltip_period_label(label_gran, x, multi_year),
                "—" if v is None or pd.isna(v) else f"{float(v):.1f} {unit}",
            ]
            for x, v in zip(x_values, raw)
        ]
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=[None if v is None or pd.isna(v) else float(v) for v in norm.tolist()],
                mode="lines+markers",
                name=label,
                visible=key in selection,
                meta=key,
                line={"color": color, "width": 2},
                marker={"color": color, "size": 4},
                customdata=customdata,
            )
        )
    axis_gran = "month" if granularity == "month" else "day"
    if granularity == "month":
        tickvals = sorted(set(x_values))
        ticktext = [_month_tick_label(v) for v in tickvals]
    else:
        tickvals, ticktext = _day_tick_subset(sorted(set(x_values)), max_ticks=8)
    initial_range = _initial_x_range(x_values, axis_gran)
    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": tickvals,
        "ticktext": ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    xaxis_cfg["type"] = "category" if granularity == "month" else "date"
    if initial_range:
        xaxis_cfg["range"] = _range_for_axis(initial_range, axis_gran)
    fig.update_layout(
        title={"text": "", "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
        yaxis={
            "range": [-5, 105],
            "tickmode": "array",
            "tickvals": [0, 25, 50, 75, 100],
            "showgrid": False,
            "zeroline": False,
            "tickfont": {"size": 10, "color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=250,
        margin={"l": 40, "r": 16, "t": 20, "b": 30},
        hovermode="closest",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        showlegend=False,
        dragmode="pan",
    )
    return fig


def get_exercise_session_summary(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Resumen por sesión con rendimiento y caída intraejercicio."""
    df = get_exercise_raw_data(db_path, ejercicio)
    if df.empty:
        return df

    df["tonelaje"] = df["kg"] * df["reps"]
    session_df = (
        df.groupby(["semana", "sesion", "fecha", "dia"])
        .agg(
            total_sets=("set_orden", "count"),
            total_tonelaje=("tonelaje", "sum"),
            posicion_ejercicio=("posicion_ejercicio", "first"),
            avg_kg=("kg", "mean"),
            avg_reps=("reps", "mean"),
            avg_rm_ajustado=("rm_ajustado", "mean"),
            rm_primera=("rm_ajustado", "first"),
            rm_ultima=("rm_ajustado", "last"),
        )
        .reset_index()
    )

    session_df["avg_kg"] = session_df["avg_kg"].round(1)
    session_df["avg_reps"] = session_df["avg_reps"].round(1)
    session_df["avg_rm_ajustado"] = session_df["avg_rm_ajustado"].round(1)
    session_df["total_tonelaje"] = session_df["total_tonelaje"].round(1)
    session_df["caida_pct"] = (
        (1 - session_df["rm_ultima"] / session_df["rm_primera"]) * 100
    ).round(1)
    session_df["rm_primera"] = session_df["rm_primera"].round(1)
    session_df["rm_ultima"] = session_df["rm_ultima"].round(1)
    session_df = session_df.sort_values(["semana", "sesion"]).reset_index(drop=True)
    return session_df
