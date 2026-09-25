"""Ejes, ticks y rangos visibles (spec 008)."""

import pandas as pd


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
