"""Rutas UI diarias: indice, diario y cardio (spec 009)."""

from datetime import date

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import MUSCLE_CATEGORIES
from src import web_context
from src.cardio_service import (
    CardioAnnotationInput,
    get_day_cardio,
    upsert_cardio_annotation,
)
from src.charts import (
    chart_metrics_index,
    chart_pfr_timeline,
)
from src.dashboard_service import (
    chart_shell_html,
    get_filters,
)
from src.database import (
    get_categories,
    get_dashboard_catalog,
    get_diario_by_fecha,
    get_ejercicio_categoria,
    get_plantillas_alimentacion,
    get_sets_by_fecha,
)
from src.http_shared import (
    _domain_error_response,
    _today_iso,
    _validate_granularity,
)
from src.response_fragments import (
    fragment_oob,
    notice_oob,
)
from src.security import (
    get_csrf_secret,
    make_csrf_token,
)
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_display,
    fecha_to_db,
)
from src.ui_fragments import (
    _alimento_form_html,
    _alimento_preview_map,
    _cascade_row_html,
    _daily_app_config,
    _editor_html,
    _exercise_form_html,
    _navigator_html,
    _nutrition_editor_html,
    _plantillas_alimentacion_list_html,
    _plantillas_list_html,
    _render_body,
)
from src.web_context import CICLO_START_DATE, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def read_index(
    request: Request,
    gran: str = Query(default="day"),
    registro: str = Query(default=""),
    metricas: str | None = Query(default=None),
):
    from datetime import date as _date

    # ``?registro=`` fue la URL del editor emergente anterior. La conservamos
    # como enlace de compatibilidad, pero la experiencia canónica vive en
    # /diario y no debe volver a abrir una segunda interfaz de registro.
    if registro:
        try:
            legacy_date = _date.fromisoformat(registro)
        except ValueError:
            legacy_date = None
        if legacy_date is not None:
            return RedirectResponse(url=f"/diario?fecha={legacy_date.isoformat()}", status_code=303)

    from src.summary_service import build_period_summary

    ejercicios_list, grupos_list = get_filters(web_context.DB_PATH)
    categories = get_categories(web_context.DB_PATH) or MUSCLE_CATEGORIES
    fecha = _today_iso()
    _fecha_date = _date.fromisoformat(fecha)
    granularity = _validate_granularity(gran)
    # Render inicial del panel derecho server-side: sin flash ni layout shift
    # (misma técnica anti-parpadeo de la granularidad). El servicio devuelve
    # estado error/empty controlado; nunca propaga a HTTP.
    period_summary = build_period_summary(web_context.DB_PATH, [], [], granularity, 8)
    from src.health_panels import (
        build_metrics_catalog,
        build_metrics_index,
        parse_metrics_param,
    )

    # La gráfica de nutrición ES la gráfica de métricas (índice 0–100 con
    # todas las series; valores reales en tooltip). Reutiliza slot, ids y
    # canal OOB de nutrition-trend (cero churn de templates/CSS/JS).
    _metrics_selection = parse_metrics_param(metricas)
    _metrics_df = build_metrics_index(web_context.DB_PATH, granularity)
    _metrics_fig = chart_metrics_index(_metrics_df, granularity, _metrics_selection)
    _systemic_fig = chart_pfr_timeline(web_context.DB_PATH, "systemic", "", granularity=granularity)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "grupos_list": grupos_list,
            "ejercicios_list": ejercicios_list,
            "ejercicios_grupo": ejercicios_list,
            "muscle_categories": categories,
            "effective_gran": granularity,
            "period_summary": period_summary,
            "dashboard_catalog": get_dashboard_catalog(web_context.DB_PATH),
            "cascade_row_html": _cascade_row_html(request, "musculo", ""),
            "systemic_chart_html": chart_shell_html(
                "Rendimiento",
                _systemic_fig,
            ),
            "metrics_catalog": build_metrics_catalog(web_context.DB_PATH, _metrics_selection),
            "nutrition_trend_html": chart_shell_html(
                "Métricas",
                _metrics_fig,
                empty_text="Sin datos de métricas",
                prefix="nutrition-trend",
            ),
            "navigator_html": _navigator_html(request, fecha, granularity=granularity),
            "editor_html": _editor_html(request, fecha),
            "dia": day_from_date(_fecha_date),
            "fecha_display": fecha_display(fecha),
            "semana": calculate_cycle_week(_fecha_date, CICLO_START_DATE),
            "exercise_form_html": _exercise_form_html(request),
            "plantillas_html": _plantillas_list_html(request),
            "nutrition_editor_html": _nutrition_editor_html(request, fecha),
            "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
            "alimento_form_html": _alimento_form_html(request),
            "app_config_json": {
                "categoria_map": get_ejercicio_categoria(web_context.DB_PATH),
                "alimento_map": _alimento_preview_map(),
                "ciclo_start": CICLO_START_DATE.isoformat(),
                "csrf_token": make_csrf_token(get_csrf_secret()),
            },
        },
    )


@router.get("/fecha/editor", response_class=HTMLResponse)
def fecha_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_editor_html(request, fecha))


def _cardio_day_html(request: Request, fecha: str) -> str:

    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="cardio_day.html",
            context={"cardio": get_day_cardio(web_context.DB_PATH, fecha), "fecha_iso": fecha},
        )
    )


@router.get("/diario", response_class=HTMLResponse)
def diario_page(
    request: Request,
    fecha: str = Query(default=""),
    vista: str = Query(default="entrenamiento"),
):
    """Standalone daily workspace; ``/registro`` remains a compatibility alias."""
    from datetime import date as _date

    if not fecha:
        fecha = _date.today().isoformat()
    if vista not in {"entrenamiento", "alimentacion"}:
        vista = "entrenamiento"
    fecha_date = _date.fromisoformat(fecha)

    session_has_data = bool(get_sets_by_fecha(web_context.DB_PATH, fecha_to_db(fecha_date)))
    food_has_data = bool(get_diario_by_fecha(web_context.DB_PATH, fecha))
    context = {
        "navigator_html": _navigator_html(request, fecha, variant="daily", vista=vista),
        "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
        "nutrition_editor_html": _nutrition_editor_html(request, fecha),
        "editor_html": _editor_html(request, fecha),
        "cardio_html": _cardio_day_html(request, fecha),
        "exercise_form_html": _exercise_form_html(request),
        "alimento_form_html": _alimento_form_html(request),
        "plantillas_html": _plantillas_list_html(request),
        "dia": day_from_date(fecha_date),
        "fecha_display": fecha_display(fecha),
        "daily_date_title": f"{fecha_date.day:02d}/{fecha_date.month:02d}/{fecha_date.year % 100:02d}",
        "vista": vista,
        "fecha_iso": fecha,
        "session_has_data": session_has_data,
        "food_has_data": food_has_data,
        "food_template_count": len(get_plantillas_alimentacion(web_context.DB_PATH)),
        "app_config_json": _daily_app_config(),
    }
    return HTMLResponse(
        content=_render_body(
            templates.TemplateResponse(request=request, name="diario.html", context=context)
        )
    )


@router.get("/registro", response_class=HTMLResponse)
def registro_legacy(
    fecha: str = Query(default=""),
    vista: str = Query(default="entrenamiento"),
):
    """Redirect the former registro URL to the single canonical Diario page."""
    params = []
    if fecha:
        try:
            fecha = date.fromisoformat(fecha).isoformat()
        except ValueError:
            fecha = ""
    if fecha:
        params.append(f"fecha={fecha}")
    if vista in {"entrenamiento", "alimentacion"}:
        params.append(f"vista={vista}")
    query = "&".join(params)
    return RedirectResponse(url="/diario" + (f"?{query}" if query else ""), status_code=303)


@router.get("/diario/navigator", response_class=HTMLResponse)
def diario_navigator(
    request: Request,
    fecha: str = Query(...),
    vista: str = Query(default="entrenamiento"),
):
    """Fragmento del carrusel de fechas del Diario (variante compacta).

    Los puntos se filtran por ``vista``: entrenamiento o alimentación.
    """
    if vista not in {"entrenamiento", "alimentacion"}:
        vista = "entrenamiento"
    return HTMLResponse(content=_navigator_html(request, fecha, variant="daily", vista=vista))


@router.get("/editor/popup", response_class=HTMLResponse)
def editor_popup(request: Request, fecha: str = Query(...)):
    """Cuerpo de la ventana emergente de registro: navegador + editores + cardio."""
    from datetime import date as _date

    fecha_date = _date.fromisoformat(fecha)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="editor_popup.html",
            context={
                "navigator_html": _navigator_html(request, fecha, granularity="day"),
                "nutrition_templates_html": _plantillas_alimentacion_list_html(request, fecha),
                "nutrition_editor_html": _nutrition_editor_html(request, fecha),
                "editor_html": _editor_html(request, fecha),
                "cardio_html": _cardio_day_html(request, fecha),
                "exercise_form_html": _exercise_form_html(request),
                "alimento_form_html": _alimento_form_html(request),
                "plantillas_html": _plantillas_list_html(request),
                "dia": day_from_date(fecha_date),
                "fecha_display": fecha_display(fecha),
                "semana": calculate_cycle_week(fecha_date, CICLO_START_DATE),
            },
        )
    )


@router.get("/cardio/day", response_class=HTMLResponse)
def cardio_day(request: Request, fecha: str = Query(...)):
    """Fragmento del panel de cardio de una fecha (navegación dentro del popup)."""
    return HTMLResponse(content=_cardio_day_html(request, fecha))


@router.post("/cardio/annotation", response_class=HTMLResponse)
def cardio_annotation_save(
    request: Request,
    hc_id: str = Form(...),
    velocidad_kmh: float | None = Form(None),
    inclinacion_pct: float | None = Form(None),
    notas: str = Form(""),
    fecha: str = Form(""),
):
    """Upsert de velocidad/inclinación sobre una sesión EXERCISE_SESSION."""

    try:
        upsert_cardio_annotation(
            web_context.DB_PATH,
            CardioAnnotationInput(
                hc_id=hc_id,
                velocidad_kmh=velocidad_kmh,
                inclinacion_pct=inclinacion_pct,
                notas=notas,
            ),
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates,
        request,
        target="notice-container",
        message="Anotación de cardio guardada.",
        dismiss=2500,
    )
    if fecha:
        return HTMLResponse(
            content=notice
            + fragment_oob(
                templates,
                request,
                "cardio-day",
                _cardio_day_html(request, fecha),
                swap="outerHTML",
            )
        )
    return HTMLResponse(content=notice)
