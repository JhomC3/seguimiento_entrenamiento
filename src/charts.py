import pandas as pd
import plotly.graph_objects as go

from config import CICLO_NUMERO
from src.db_connection import read_connection
from src.design_tokens import color, palette
from src.metrics_engine import RM_FACTOR, calculate_pfr_timeline, rm_ajustado
from src.summary_service import (
    _PeriodTotals,
    aggregate_sets,
    day_label,
    month_label,
    totals_by_period,
    week_label,
)

# Hovertemplate canónico de Fase 2: Δ + métricas del periodo,
# peso corporal, sueño, fallos ni fecha duplicada. El nombre viaja en <extra>.
HOVERTEMPLATE = (
    "%{customdata[0]}<br>Δ %{customdata[1]}"
    "<br>Series %{customdata[2]} · Reps %{customdata[3]}"
    "<br>Peso %{customdata[4]} kg · RIR %{customdata[5]}"
    "<br>RM aj. %{customdata[6]}"
    "<br>Cobertura %{customdata[7]}"
    "<extra>%{customdata[8]}</extra>"
)


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
    """Etiqueta compacta de mes: 'ene 26' desde '2026-01' o '2026-01-15'."""
    try:
        s = str(periodo).strip()
        # acepta 'YYYY-MM' o 'YYYY-MM-DD' o 'YYYY-MM' con separador '-'
        parts = s.split("-")
        y = int(parts[0])
        m = int(parts[1])
        mes = _MESES_CORTO[m - 1] if 1 <= m <= 12 else parts[1]
        return f"{mes} {str(y)[2:]}"
    except Exception:  # noqa: BLE001
        return str(periodo)


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


def _hover_rows(df: pd.DataFrame, name: str) -> list[list[str]]:
    """Construye las 9 posiciones canónicas del customdata por punto.

    1 etiqueta · 2 Δ · 3 series · 4 reps · 5 peso · 6 RIR · 7 RM aj. ·
    8 cobertura · 9 nombre.
    """
    rows: list[list[str]] = []
    for _, r in df.iterrows():
        series_val = r.get("h_series")
        rows.append(
            [
                str(r.get("hlabel", "—")),
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


def _pfr_trace(
    df: pd.DataFrame,
    name: str,
    color: str,
    *,
    alpha: float = 1.0,
    width: float = 2.5,
    marker_size: int = 3,
    granularity: str = "week",
) -> go.Scatter:
    # Eje X y etiqueta de periodo según granularidad: la serie semanal conserva
    # `semana`; day y month usan `periodo` (fecha/label cronológico real).
    x_col = "semana" if granularity == "week" else "periodo"

    line_color = color if alpha >= 1.0 else _hex_to_rgba(color, alpha)
    customdata = _hover_rows(df, name)
    hovertemplate = HOVERTEMPLATE
    return go.Scatter(
        x=df[x_col],
        y=df["crecimiento"],
        mode="lines+markers",
        name=name,
        line={"color": line_color, "width": width},
        # Los puntos comparten la transparencia de su línea.
        marker={"size": marker_size, "color": line_color},
        customdata=customdata,
        hovertemplate=hovertemplate,
    )


def chart_selection(
    db_path: str,
    musculos: list[str],
    ejercicios: list[str],
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de la selección actual:

    - 0 músculos: línea sistémica global ("Crecimiento").
    - 1 músculo, 0 ejercicios: Global + nombre del músculo.
    - 1 músculo, N ejercicios válidos: Compilado (guía) + ejercicios.
      (Global se oculta en estado ejercicio — decisión D2.)
    - 2+ músculos: Global + músculos. Los ejercicios no aplican.

    Los ejercicios que no pertenecen al músculo se descartan.
    """
    traces: list[go.Scatter] = []
    title = "Rendimiento – Cuerpo entero"
    # The systemic series provides a stable vertical reference. Selection
    # changes may add traces outside this window, but must never resize or
    # vertically reposition the chart shell.
    reference_df = _pfr_df(db_path, "systemic", None, granularity)

    if len(musculos) == 0:
        # Estado global: línea sistémica (D3).
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df, "Crecimiento", chart_color("primary"), granularity=granularity
                )
            )
    elif len(musculos) == 1:
        musculo = musculos[0]
        title = f"Rendimiento – {musculo}"

        if ejercicios:
            # Estado ejercicio: Compilado guía + ejercicios (sin global — D2).
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                traces.append(
                    _pfr_trace(
                        compiled, "Compilado", chart_color("primary"), granularity=granularity
                    )
                )

            with read_connection(db_path) as conn:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                    (musculo,),
                ).fetchall()
            valid = {str(r[0]).lower() for r in rows}
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
                    )
                )
        else:
            # Estado muscular: misma jerarquía que 2+ músculos:
            # Global sólido + músculo identificado y translúcido.
            global_df = _pfr_df(db_path, "systemic", None, granularity)
            if not global_df.empty:
                traces.append(
                    _pfr_trace(global_df, "Global", chart_color("primary"), granularity=granularity)
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
                    )
                )
    elif len(musculos) >= 2:
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(global_df, "Global", chart_color("primary"), granularity=granularity)
            )
        for idx, musculo in enumerate(musculos):
            df = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            traces.append(
                _pfr_trace(
                    df, musculo, color, alpha=0.4, width=3.5, marker_size=3, granularity=granularity
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
    x_title = {"week": "Semana", "day": "Fecha", "month": "Mes"}[granularity]
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

    # Eje X: tickmode array con subconjunto para no apiñar (day: máx 8 etiquetas)
    if granularity == "day":
        all_periods = sorted({str(v) for v in all_x})
        tickvals, ticktext = _day_tick_subset(all_periods, max_ticks=8)
    elif all_x and isinstance(all_x[0], int):
        tickvals = sorted(set(all_x))
        ticktext = [str(v) for v in tickvals]
    else:
        tickvals = sorted({str(v) for v in all_x})
        ticktext = [str(v) for v in tickvals]

    xaxis_cfg: dict = {
        "title": x_title,
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
            "title": "Crecimiento (%)",
            "range": [y_bottom, y_top],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=450,
        # Reserve a fixed top band for the horizontal legend so adding or
        # removing traces never changes the chart shell or plot width.
        margin={"l": 60, "r": 20, "t": 48, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        # La leyenda SIEMPRE visible (también con 1 traza): vive en la banda
        # superior reservada, así que el área de trazado no cambia de tamaño
        # al pasar de modo global a selección y viceversa.
        showlegend=True,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.08,
            "xanchor": "left",
            "yanchor": "bottom",
            "entrywidth": 100,
            "entrywidthmode": "pixels",
            "font": {"color": chart_color("axes"), "size": 11},
            "bgcolor": chart_color("background"),
        },
        dragmode="pan",
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

    # Eje X
    x_col = "periodo" if "periodo" in periodic.columns else "semana"
    x_title = {"week": "Semana", "day": "Fecha", "month": "Mes"}[granularity]

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

    if granularity == "day":
        periods = [str(v) for v in periodic[x_col].tolist()]
        tickvals, ticktext = _day_tick_subset(periods, max_ticks=8)
        customdata_vals = _hover_rows(periodic, "Crecimiento")
        x_tickvals = tickvals
        x_ticktext = ticktext
    else:
        x_tickvals = periodic[x_col].tolist()
        x_ticktext = [str(v) for v in periodic[x_col]]
        customdata_vals = _hover_rows(periodic, "Crecimiento")

    fig.add_trace(
        go.Scatter(
            x=periodic[x_col],
            y=periodic["crecimiento"],
            mode="lines+markers",
            name="Crecimiento",
            line={"color": chart_color("primary"), "width": 2.5},
            marker={"size": 8, "color": chart_color("primary")},
            customdata=customdata_vals,
            hovertemplate=HOVERTEMPLATE,
        )
    )

    xaxis_cfg: dict = {
        "title": x_title,
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
            "title": "Crecimiento (%)",
            "range": [y_bottom, y_top],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=450,
        margin={"l": 60, "r": 20, "t": 48, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        # La leyenda SIEMPRE visible (también con 1 traza): vive en la banda
        # superior reservada, así que el área de trazado no cambia de tamaño
        # al pasar de modo global a selección y viceversa.
        showlegend=True,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.08,
            "xanchor": "left",
            "yanchor": "bottom",
            "entrywidth": 100,
            "entrywidthmode": "pixels",
            "font": {"color": chart_color("axes"), "size": 11},
            "bgcolor": chart_color("background"),
        },
        dragmode="pan",
    )

    return fig


def get_exercise_session_summary(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Resumen por sesión con rendimiento y caída intraejercicio."""
    df = get_exercise_raw_data(db_path, ejercicio)
    if df.empty:
        return df

    session_df = (
        df.groupby(["semana", "sesion", "fecha", "dia"])
        .agg(
            total_sets=("set_orden", "count"),
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
    session_df["caida_pct"] = (
        (1 - session_df["rm_ultima"] / session_df["rm_primera"]) * 100
    ).round(1)
    session_df["rm_primera"] = session_df["rm_primera"].round(1)
    session_df["rm_ultima"] = session_df["rm_ultima"].round(1)
    session_df = session_df.sort_values(["semana", "sesion"]).reset_index(drop=True)
    return session_df
