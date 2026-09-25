"""Fragmentos HTML server-side (spec 009)."""

import uuid
from datetime import date

from fastapi import Request

from config import MUSCLE_CATEGORIES
from src import web_context
from src.dashboard_service import (
    build_date_navigator,
    build_nutrition_editor,
    build_session_editor,
)
from src.database import (
    get_active_split_id,
    get_alimentos_catalog,
    get_categories,
    get_ejercicio_categoria,
    get_exercises_catalog,
    get_plantillas,
    get_plantillas_alimentacion,
    get_split_catalog,
    get_splits_summary,
)
from src.db_connection import read_connection
from src.http_shared import MAX_SPLIT_ITEMS
from src.models import (
    SPLIT_DAYS,
    Split,
    SplitMetrics,
)
from src.nutrition_service import (
    NUTRIENT_FIELDS,
)
from src.security import (
    get_csrf_secret,
    make_csrf_token,
)
from src.split_service import compute_split_metrics, get_split_board
from src.web_context import CICLO_START_DATE, templates


def _render_body(response) -> str:
    return bytes(response.body).decode()


def _navigator_html(
    request: Request,
    fecha_iso: str,
    grupo: str | None = None,
    ejercicio: str | None = None,
    granularity: str = "day",
    variant: str = "dashboard",
    vista: str = "entrenamiento",
) -> str:
    vm = build_date_navigator(
        web_context.DB_PATH,
        fecha_iso,
        CICLO_START_DATE,
        date.today(),
        grupo=grupo,
        ejercicio=ejercicio,
        granularity=granularity,
        variant=variant,
        vista=vista,
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="date_navigator.html",
            context={
                "dates": vm.dates,
                "selected_iso": vm.selected_iso,
                "today_iso": vm.today_iso,
            },
        )
    )


def _daily_app_config() -> dict[str, object]:
    """Shared config for the standalone daily page and its editors."""
    return {
        "categoria_map": get_ejercicio_categoria(web_context.DB_PATH),
        "alimento_map": _alimento_preview_map(),
        "ciclo_start": CICLO_START_DATE.isoformat(),
        "csrf_token": make_csrf_token(get_csrf_secret()),
    }


def _editor_html(
    request: Request,
    fecha_iso: str,
    *,
    rows=None,
    error: str | None = None,
    success: str | None = None,
    force_editable: bool = False,
    force_readonly: bool = False,
) -> str:
    vm = build_session_editor(
        web_context.DB_PATH,
        fecha_iso,
        CICLO_START_DATE,
        rows=rows,
        error=error,
        success=success,
        force_editable=force_editable,
        force_readonly=force_readonly,
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="session_editor.html",
            context={
                "fecha_iso": vm.fecha_iso,
                "fecha_display": vm.fecha_display,
                "semana": vm.semana,
                "dia": vm.dia,
                "rows": vm.rows,
                "readonly": vm.readonly,
                "has_data": vm.has_data,
                "error": vm.error,
                "success": vm.success,
                "catalog": vm.catalog,
                "is_hiit_session": vm.is_hiit_session,
                "is_mixed_session": vm.is_mixed_session,
            },
        )
    )


def _grupo_options() -> list[dict[str, str]]:
    """Opciones del combo de grupo muscular (orden del catálogo)."""
    out: list[dict[str, str]] = []
    for cat in MUSCLE_CATEGORIES:
        muscles = cat.get("muscles")
        if not isinstance(muscles, list):
            continue
        for m in muscles:
            out.append({"nombre": str(m).strip(), "categoria": str(cat["name"])})
    return out


def _exercise_form_html(
    request: Request, *, error: str | None = None, success: str | None = None
) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="exercise_create_form.html",
            context={
                "grupo_options": _grupo_options(),
                "error": error,
                "success": success,
            },
        )
    )


def _template_count_oob(request: Request, kind: str) -> str:
    """OOB del contador de plantillas del Diario (span dentro del botón).

    Solo alimentación conserva su botón con conteo; el de entrenamiento se
    retiró del Diario (las plantillas se aplican desde API/diálogos), así que
    su rama devuelve vacío para no emitir OOB a un target inexistente.
    ``inner`` es un entero del servidor (nunca datos de usuario): se construye
    el span directamente, sin pasar por la allow-list de fragmentos.
    """
    if kind == "training":
        return ""
    count = len(get_plantillas_alimentacion(web_context.DB_PATH))
    target = "daily-food-template-count"
    inner = f" · {count}" if count else ""
    return f'<span id="{target}" hx-swap-oob="outerHTML">{inner}</span>'


def _plantillas_list_html(
    request: Request, *, editing_id: int | None = None, error: str | None = None
) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="plantillas_list.html",
            context={
                "plantillas": get_plantillas(web_context.DB_PATH),
                "catalog": get_exercises_catalog(web_context.DB_PATH),
                "editing_id": editing_id,
                "error": error,
            },
        )
    )


def _split_accordion_item_html(
    request: Request,
    split_id: int | None,
    *,
    open_: bool = False,
    max_items: int = MAX_SPLIT_ITEMS,
) -> str:
    """Fragmento de un item del acordeón de splits (cabecera + board semanal).

    `split_id=None` renderiza un split nuevo vacío (sin persistir) en modo
    edición, para el flujo "Crear nuevo split" (GET /split/nuevo).
    """
    split: Split | None = None
    metrics: SplitMetrics = compute_split_metrics([])
    is_active = False
    if split_id is not None:
        board = get_split_board(web_context.DB_PATH, split_id)
        split = board["split"]
        metrics = board["metrics"]
        item_uid: str = str(split.id)
        is_active = bool(getattr(split, "activo", 0))
    else:
        # Fragmento "nuevo" sin persistir: uid único por request para que dos
        # splits nuevos no dupliquen ids (split-nombre-*, sz-*-g*).
        item_uid = f"nuevo-{uuid.uuid4().hex[:8]}"
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="partials/split_accordion_item.html",
            context={
                "days": SPLIT_DAYS,
                "split": split,
                "metrics": metrics,
                "editmode": "0" if split else "1",
                "max_items": max_items,
                "open": open_,
                "item_uid": item_uid,
                "is_active": is_active,
            },
        )
    )


def _split_section_html(request: Request, abrir_id: int | None = None) -> str:
    """Contenido de #splits-section: estado vacío o items del acordeón.

    Orden server-authoritative: el split actual primero (ver
    ``get_splits_summary``). Sin ``?abrir``, el actual se renderiza abierto.
    """
    active_id = get_active_split_id(web_context.DB_PATH)
    items_html = ""
    for s in get_splits_summary(web_context.DB_PATH):
        if abrir_id is not None:
            open_item = abrir_id == s["id"]
        else:
            open_item = active_id is not None and active_id == s["id"]
        items_html += _split_accordion_item_html(request, s["id"], open_=open_item)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="partials/split_accordion.html",
            context={"splits_html": items_html},
        )
    )


def _split_page_html(request: Request, abrir_id: int | None = None) -> str:
    """Página completa del gestor de splits (base.html + fragmentos)."""
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="splits.html",
            context={
                "catalog": get_split_catalog(web_context.DB_PATH),
                "splits_html": _split_section_html(request, abrir_id=abrir_id),
                "exercise_form_html": _exercise_form_html(request),
                "app_config_json": {"csrf_token": make_csrf_token(get_csrf_secret())},
            },
        )
    )


def _split_catalog_html(request: Request) -> str:
    """Grupos del catálogo de splits (para el OOB `#splits-catalog`)."""
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="partials/split_catalog_groups.html",
            context={"catalog": get_split_catalog(web_context.DB_PATH)},
        )
    )


NUTRIENT_FIELD_LABELS: list[dict[str, str]] = [
    {"name": "kcal", "label": "kcal"},
    {"name": "carbohidratos", "label": "Carb (g)"},
    {"name": "fibra", "label": "Fibra (g)"},
    {"name": "proteina", "label": "Prot (g)"},
    {"name": "grasa", "label": "Grasa (g)"},
    {"name": "hierro", "label": "Hierro (mg)"},
    {"name": "calcio", "label": "Calcio (mg)"},
    {"name": "vitamina_c", "label": "Vit C (mg)"},
    {"name": "vitamina_a", "label": "Vit A (µg)"},
    {"name": "magnesio", "label": "Mg (mg)"},
    {"name": "zinc", "label": "Zinc (mg)"},
    {"name": "potasio", "label": "K (mg)"},
    {"name": "sodio", "label": "Na (mg)"},
    {"name": "vitamina_d", "label": "Vit D (µg)"},
    {"name": "vitamina_e", "label": "Vit E (mg)"},
    {"name": "vitamina_k", "label": "Vit K (µg)"},
    {"name": "folato", "label": "Folato (µg)"},
    {"name": "vitamina_b12", "label": "B12 (µg)"},
    {"name": "vitamina_b6", "label": "B6 (mg)"},
    {"name": "yodo", "label": "Yodo (µg)"},
    {"name": "selenio", "label": "Selenio (µg)"},
]


def _alimento_preview_map() -> dict[str, dict[str, float]]:
    """Mapa compacto nombre -> nutrientes por 100 g para previsualización client."""
    return {
        a["nombre"]: {k: a[k] for k in NUTRIENT_FIELDS}
        for a in get_alimentos_catalog(web_context.DB_PATH)
    }


def _nutrition_app_config() -> dict:
    return _daily_app_config()


def _nutrition_fecha_display(fecha_iso: str) -> str:
    from datetime import date as _date

    d = _date.fromisoformat(fecha_iso)
    return f"{d.day}/{d.month}/{d.year}"


def _plantillas_alimentacion_list_html(request: Request, fecha_iso: str) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="plantillas_alimentacion_list.html",
            context={
                "plantillas": get_plantillas_alimentacion(web_context.DB_PATH),
                "selected_iso": fecha_iso,
            },
        )
    )


def _nutrition_editor_html(
    request: Request,
    fecha_iso: str,
    *,
    rows: list[dict] | None = None,
    force_editable: bool = False,
    error: str | None = None,
    success: str | None = None,
) -> str:
    vm = build_nutrition_editor(
        web_context.DB_PATH,
        fecha_iso,
        rows=rows,
        force_editable=force_editable,
        error=error,
        success=success,
    )
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="nutrition_editor.html",
            context={
                "fecha_iso": vm.fecha_iso,
                "rows": vm.rows,
                "totals": vm.consumido,
                "objetivo": vm.objetivo,
                "consumido": vm.consumido,
                "parametros": vm.parametros,
                "catalog": vm.catalog,
                "has_data": vm.has_data,
                "readonly": vm.readonly,
                "prefilled": vm.prefilled,
                "prefill_source": vm.prefill_source,
                "error": vm.error,
                "success": vm.success,
            },
        )
    )


def _alimento_form_html(request: Request) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="alimento_create_form.html",
            context={"nutrient_fields": NUTRIENT_FIELD_LABELS},
        )
    )


def _cascade_items(nivel: str, foco: str) -> list[str]:
    """Siguiente fila de la cascada: categorías → músculos → ejercicios."""
    if nivel == "grupo" and not foco:
        return [str(c["name"]) for c in get_categories(web_context.DB_PATH) or MUSCLE_CATEGORIES]
    if nivel == "grupo":
        with read_connection(web_context.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo_muscular FROM ejercicios "
                "WHERE LOWER(categoria) = LOWER(?) AND grupo_muscular IS NOT NULL "
                "ORDER BY grupo_muscular",
                (foco,),
            ).fetchall()
        return [str(r[0]) for r in rows]
    if nivel == "musculo":
        with read_connection(web_context.DB_PATH) as conn:
            if foco and foco.lower() != "cardio":
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios "
                    "WHERE LOWER(grupo_muscular) = LOWER(?) ORDER BY ejercicio",
                    (foco,),
                ).fetchall()
                return [str(r[0]) for r in rows]
            if not foco:
                rows = conn.execute(
                    "SELECT DISTINCT grupo_muscular FROM ejercicios "
                    "WHERE grupo_muscular IS NOT NULL ORDER BY grupo_muscular"
                ).fetchall()
                items = [str(r[0]) for r in rows]
                items.append("Cardio")
                return items
        return []
    if nivel == "ejercicio":
        with read_connection(web_context.DB_PATH) as conn:
            rows = conn.execute("SELECT ejercicio FROM ejercicios ORDER BY ejercicio").fetchall()
        return [str(r[0]) for r in rows]
    return []


def _cascade_chip_tipo(nivel: str, foco: str) -> str:
    """Tipo de la fila desplegada: mismo nivel si es selección directa, o el
    siguiente nivel cuando un foco avanza la cascada (grupo→músculo→ejercicio)."""
    if foco:
        return {"grupo": "musculo", "musculo": "ejercicio"}.get(nivel, "")
    return nivel


def _cascade_row_html(request: Request, nivel: str, foco: str) -> str:
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="cascade_row.html",
            context={
                "items": _cascade_items(nivel, foco),
                "tipo": _cascade_chip_tipo(nivel, foco),
            },
        )
    )
