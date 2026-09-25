"""Rutas UI de cascada, nivel y grafica (spec 009)."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src import web_context
from src.charts import (
    chart_metrics_index,
    chart_pfr_timeline,
    get_exercise_cohort_summary,
    get_exercise_raw_data,
    get_exercise_session_summary,
)
from src.dashboard_service import (
    get_first_session_date,
)
from src.database import (
    get_dashboard_catalog,
)
from src.http_shared import (
    _validate_granularity,
    _validate_window,
)
from src.response_fragments import (
    chart_data_oob,
    chart_empty_oob,
    chart_header_oob,
    fragment_oob,
    nutrition_trend_data_oob,
    nutrition_trend_empty_oob,
    nutrition_trend_header_oob,
    render_fragment,
    summary_oob,
)
from src.ui_fragments import (
    _cascade_items,
    _cascade_row_html,
    _render_body,
)
from src.web_context import templates

router = APIRouter()


@router.get("/semana/primer-entreno", response_class=JSONResponse)
def semana_primer_entreno(
    semana: int = Query(...),
    grupo: str | None = Query(None),
    ejercicio: str | None = Query(None),
):
    fecha = get_first_session_date(web_context.DB_PATH, semana, grupo, ejercicio)
    return JSONResponse({"fecha": fecha})


def _ejercicios_row_html(request: Request, musculo: str, seleccionados: list[str]) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="ejercicios_row.html",
            context={
                "items": _cascade_items("musculo", musculo),
                "padre": musculo,
                "seleccionados": seleccionados,
            },
        )
    )


def _exercise_detail_html(request, ejercicio):

    raw_df = get_exercise_raw_data(web_context.DB_PATH, ejercicio)
    session_df = get_exercise_session_summary(web_context.DB_PATH, ejercicio)
    cohort_df = get_exercise_cohort_summary(raw_df)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_detail.html",
            context={
                "raw_data": raw_df.to_dict(orient="records") if not raw_df.empty else [],
                "session_summary": (
                    session_df.to_dict(orient="records") if not session_df.empty else []
                ),
                "cohort_summary": (
                    cohort_df.to_dict(orient="records") if not cohort_df.empty else []
                ),
                "ejercicio": ejercicio,
            },
        )
    )


@router.get("/nivel", response_class=HTMLResponse)
def nivel_view(
    request: Request,
    tipo: str = Query(...),
    foco: str = Query(default=""),
    ejercicios: list[str] = Query(default=[]),
    gran: str = Query(default="day"),
):
    """Cascada: músculos (fila persistente) → ejercicios del músculo → detalle.

    - tipo=musculo sin foco: fila de músculos (no toca la gráfica).
    - tipo=musculo con foco: fila de ejercicios del músculo con aria-pressed.
    - tipo=ejercicio con foco: detalle tabular en #history-section.
    - tipo=ejercicio sin foco: placeholder de detalle.
    - tipo=global: fila de músculos únicamente (sin OOB de gráfica).
    """
    _validate_granularity(gran)
    if tipo == "ejercicio":
        if foco:
            body = _exercise_detail_html(request, foco)
        else:
            body = _render_body(
                templates.TemplateResponse(
                    request=request,
                    name="exercise_detail.html",
                    context={"raw_data": [], "session_summary": [], "ejercicio": ""},
                )
            )
        return HTMLResponse(content=body)
    if tipo == "musculo" and foco:
        selected = []
        if ejercicios and len(ejercicios) == 1:
            selected = [s.strip() for s in ejercicios[0].split(",") if s.strip()]
        elif ejercicios:
            selected = [s.strip() for s in ejercicios if s.strip()]
        return HTMLResponse(content=_ejercicios_row_html(request, foco, selected))
    if tipo == "global":
        return HTMLResponse(content=_cascade_row_html(request, "musculo", ""))
    return HTMLResponse(content=_cascade_row_html(request, tipo, foco))


@router.get("/grafica", response_class=HTMLResponse)
def grafica_view(
    request: Request,
    musculos: list[str] = Query(default=[]),
    ejercicios: list[str] = Query(default=[]),
    gran: str = Query(default="day"),
    ventana: int = Query(default=8),
    metricas: str | None = Query(default=None),
):
    """Gráfica + panel de resumen + métricas en UNA sola respuesta.

    Targets OOB exclusivos: unified-chart-header/data/empty +
    nutrition-trend-header/data/empty + period-summary-wrap.
    Gráfica y panel comparten exactamente la misma selección y granularidad;
    las métricas comparten la granularidad e ignoran la
    selección muscular (índice global 0–100 con todas las series). La ventana del panel es
    propia (4|8 semanas, default 8) e independiente de las ventanas visuales.
    """
    from src.charts import chart_selection
    from src.summary_service import build_period_summary

    granularity = _validate_granularity(gran)
    semanas = _validate_window(ventana)

    if not musculos:
        fig = chart_pfr_timeline(web_context.DB_PATH, "systemic", "", "", granularity)
    else:
        fig = chart_selection(web_context.DB_PATH, musculos, ejercicios, granularity)

    has_data = hasattr(fig, "data") and fig.data
    if has_data:
        from src.dashboard_service import _json_for_inline

        data_json = _json_for_inline(fig.to_json())
        content = (
            chart_header_oob("Rendimiento") + chart_data_oob(data_json) + chart_empty_oob(False)
        )
    else:
        empty_text = "Sin datos para esta selección" if musculos else "Sin datos"
        content = (
            chart_header_oob("Rendimiento")
            + chart_data_oob("{}")
            + chart_empty_oob(True, empty_text)
        )

    # Métricas globales (misma granularidad, sin filtros musculares).
    from src.health_panels import build_metrics_index, parse_metrics_param

    _metrics_selection = parse_metrics_param(metricas)
    try:
        metrics_fig = chart_metrics_index(
            build_metrics_index(web_context.DB_PATH, granularity), granularity, _metrics_selection
        )
    except Exception:
        import logging as _logging

        _logging.getLogger("dashboard").exception("gráfica de métricas fallida")
        metrics_fig = None
    if metrics_fig is not None and hasattr(metrics_fig, "data") and metrics_fig.data:
        from src.dashboard_service import _json_for_inline as _inline

        content += (
            nutrition_trend_header_oob("Métricas")
            + nutrition_trend_data_oob(_inline(metrics_fig.to_json()))
            + nutrition_trend_empty_oob(False)
        )
    else:
        content += (
            nutrition_trend_header_oob("Métricas")
            + nutrition_trend_data_oob("{}")
            + nutrition_trend_empty_oob(True, "Sin datos de métricas")
        )

    # El panel viaja en la MISMA respuesta: una petición actualiza ambos y el
    # abort existente (cancelPending('/grafica')) protege gráfica+panel juntos.
    summary = build_period_summary(web_context.DB_PATH, musculos, ejercicios, granularity, semanas)
    summary_html = render_fragment(
        templates,
        request,
        "partials/period_summary_panel.html",
        summary=summary,
        oob=True,
    )
    content += summary_oob(summary_html)
    # Catálogo con orden dinámico compartido (misma ventana que el resumen)
    from src.summary_service import db_window

    window = db_window(web_context.DB_PATH, semanas)
    if window is not None:
        catalog = get_dashboard_catalog(
            web_context.DB_PATH, window.start.isoformat(), window.end.isoformat()
        )
    else:
        catalog = get_dashboard_catalog(web_context.DB_PATH)
    catalog_html = render_fragment(
        templates, request, "partials/dashboard_catalog.html", dashboard_catalog=catalog
    )
    content += fragment_oob(templates, request, "dashboard-catalog-list", catalog_html)

    return HTMLResponse(content=content)
