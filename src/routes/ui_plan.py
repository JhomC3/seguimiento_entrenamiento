"""Rutas UI de plantillas, splits, sugerencia y undo (spec 009)."""

import logging

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src import web_context
from src.dashboard_service import (
    translate_error,
)
from src.exercise_service import last_exercise_payload
from src.http_shared import (
    MAX_NAME_LEN,
    MAX_REORDER_IDS,
    MAX_SPLIT_ITEMS,
    TRAINING_API_SCHEMA_VERSION,
    _check_lote,
    _domain_error_response,
)
from src.models import (
    SplitInput,
    TemplateInput,
    ValidationError,
)
from src.mutation_service import (
    delete_split_with_undo_snapshot,
    delete_template_with_undo_snapshot,
    edit_template_with_undo_snapshot,
    reorder_templates_with_undo_snapshot,
    save_split_with_undo_snapshot,
    save_template_with_undo_snapshot,
    set_active_split_with_undo_snapshot,
    undo_last_action,
)
from src.response_fragments import (
    STATIC_MARKERS,
    editor_wrap_oob,
    fragment_oob,
    notice_oob,
    nutrition_editor_wrap_oob,
    undo_result_oob,
)
from src.split_service import get_split_board, split_items_from_form
from src.suggestion_service import resolve_suggestion
from src.template_service import apply_template_rows
from src.ui_fragments import (
    _editor_html,
    _nutrition_editor_html,
    _plantillas_list_html,
    _render_body,
    _split_accordion_item_html,
    _split_page_html,
    _split_section_html,
    _template_count_oob,
)
from src.web_context import templates

router = APIRouter()


@router.get("/plantillas", response_class=HTMLResponse)
def plantillas_view(request: Request, editar: int | None = Query(None)):
    return HTMLResponse(content=_plantillas_list_html(request, editing_id=editar))


@router.post("/plantilla/guardar", response_class=HTMLResponse)
def plantilla_guardar(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        result = save_template_with_undo_snapshot(
            web_context.DB_PATH, TemplateInput(nombre=nombre, ejercicios=ejercicio)
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    msg = "Entreno actualizado." if result.updated else "Entreno guardado."
    return HTMLResponse(
        content=notice_oob(templates, request, target="notice-container", message=msg)
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
        + _template_count_oob(request, "training")
    )


@router.post("/plantilla/editar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_editar(
    request: Request,
    plantilla_id: int,
    nombre: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        edit_template_with_undo_snapshot(
            web_context.DB_PATH, plantilla_id, TemplateInput(nombre=nombre, ejercicios=ejercicio)
        )
    except Exception as e:
        message, status = translate_error(e)
        if status != 400:
            return _domain_error_response(request, e, "notice-container")
        html = _plantillas_list_html(request, editing_id=plantilla_id, error=message)
        return HTMLResponse(
            content=fragment_oob(templates, request, "plantillas-section", html, swap="outerHTML")
        )
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Entreno guardado."
        )
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
        + _template_count_oob(request, "training")
    )


@router.post("/plantilla/eliminar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_eliminar(request: Request, plantilla_id: int):
    try:
        delete_template_with_undo_snapshot(web_context.DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Entreno eliminado."
        )
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
        + _template_count_oob(request, "training")
    )


@router.post("/plantilla/reordenar", response_class=HTMLResponse)
def plantilla_reordenar(request: Request, id: list[int] = Form(default=[])):
    try:
        _check_lote(id, MAX_REORDER_IDS, "orden")
        reorder_templates_with_undo_snapshot(web_context.DB_PATH, id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content="")


@router.get("/plantilla/aplicar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_aplicar(request: Request, plantilla_id: int, fecha: str = Query(...)):
    try:
        rows = apply_template_rows(web_context.DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice")
    editor = _editor_html(request, fecha, rows=rows, force_editable=True)
    notice = notice_oob(templates, request, target="editor-notice", message="Entreno aplicado.")
    return HTMLResponse(
        content=notice
        + editor_wrap_oob(templates, request, editor + STATIC_MARKERS["plantilla_applied"])
    )


@router.get("/sugerencia/banner", response_class=HTMLResponse)
def sugerencia_banner(request: Request, fecha: str = Query(...)):
    """Banner de rutina sugerida del día (solo lectura, nunca rompe la página)."""
    try:
        s = resolve_suggestion(web_context.DB_PATH, fecha)
    except Exception:
        logging.getLogger("dashboard").exception("banner de sugerencia fallido")
        return HTMLResponse(content="")
    if s.tipo == "nada":
        return HTMLResponse(content="")
    return HTMLResponse(
        content=_render_body(
            templates.TemplateResponse(
                request=request,
                name="partials/suggestion_banner.html",
                context={"tipo": s.tipo, "explicacion": s.explicacion},
            )
        )
    )


@router.get("/sugerencia/aplicar", response_class=HTMLResponse)
def sugerencia_aplicar(request: Request, fecha: str = Query(...)):
    """Rellena el editor con la sugerencia, sin guardar (como aplicar entreno)."""
    try:
        s = resolve_suggestion(web_context.DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice")
    if s.tipo != "rutina":
        notice = notice_oob(templates, request, target="editor-notice", message=s.explicacion)
        return HTMLResponse(content=notice)
    rows = [
        {
            "ejercicio": x.ejercicio,
            "kg": x.kg if x.kg is not None else "",
            "reps": x.reps if x.reps is not None else "",
            "rir": x.rir if x.rir is not None else "",
            "descanso_seg": x.descanso_seg if x.descanso_seg is not None else "",
            "velocidad_kmh": x.velocidad_kmh if x.velocidad_kmh is not None else "",
            "dificultad": x.dificultad if x.dificultad is not None else "",
        }
        for x in s.sets
    ]
    editor = _editor_html(request, fecha, rows=rows, force_editable=True)
    notice = notice_oob(templates, request, target="editor-notice", message=s.explicacion)
    return HTMLResponse(
        content=notice
        + editor_wrap_oob(templates, request, editor + STATIC_MARKERS["plantilla_applied"])
    )


@router.get("/ejercicio/ultimo")
def ejercicio_ultimo(
    request: Request,
    ejercicio: str = Query(default=""),
    fecha: str = Query(default=""),
):
    """Últimas series de un ejercicio para autofill (solo lectura, nunca 500 visible).

    Misma fuente que la rueda (`last_exercise_payload`): serie i → última
    serie i. `fecha` opcional excluye ese día y posteriores (evita eco).
    """
    try:
        payload = last_exercise_payload(
            web_context.DB_PATH, (ejercicio or "").strip(), (fecha or "").strip() or None
        )
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("ejercicio ultimo fallido")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse({"schema_version": TRAINING_API_SCHEMA_VERSION, **payload})


@router.get("/splits", response_class=HTMLResponse)
def splits_view(request: Request, abrir: int | None = Query(None)):
    try:
        if abrir is not None:
            get_split_board(web_context.DB_PATH, abrir)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content=_split_page_html(request, abrir_id=abrir))


@router.get("/split/nuevo", response_class=HTMLResponse)
def split_nuevo(request: Request):
    """Fragmento del item de un split nuevo (vacío, en modo edición).

    GET puro sin efectos colaterales: el JS lo inserta al tope de la sección
    y lo persiste solo al pulsar Guardar.
    """
    return HTMLResponse(content=_split_accordion_item_html(request, None))


@router.post("/split/guardar", response_class=HTMLResponse)
def split_guardar(
    request: Request,
    split_id: int | None = Form(None),
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    dia: list[str] = Form(default=[]),
    item_type: list[str] = Form(default=[]),
    ejercicio: list[str] = Form(default=[]),
):
    try:
        _check_lote(dia, MAX_SPLIT_ITEMS, "elementos")
        items = split_items_from_form(dia, item_type, ejercicio)
        result = save_split_with_undo_snapshot(
            web_context.DB_PATH, split_id, SplitInput(nombre=nombre, items=items)
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    msg = "Split actualizado." if result.updated else "Split guardado."
    return HTMLResponse(
        content=notice_oob(templates, request, target="notice-container", message=msg)
        + fragment_oob(
            templates,
            request,
            "splits-section",
            _split_section_html(request),
            swap="outerHTML",
        )
    )


@router.post("/split/eliminar/{split_id}", response_class=HTMLResponse)
def split_eliminar(request: Request, split_id: int):
    try:
        delete_split_with_undo_snapshot(web_context.DB_PATH, split_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Split eliminado."
        )
        + fragment_oob(
            templates,
            request,
            "splits-section",
            _split_section_html(request),
            swap="outerHTML",
        )
    )


@router.post("/split/activar/{split_id}", response_class=HTMLResponse)
def split_activar(request: Request, split_id: int):
    """Marca el split actual (único). Idempotente; re-renderiza la sección."""
    try:
        set_active_split_with_undo_snapshot(web_context.DB_PATH, split_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=notice_oob(
            templates, request, target="notice-container", message="Split actual actualizado."
        )
        + fragment_oob(
            templates,
            request,
            "splits-section",
            _split_section_html(request),
            swap="outerHTML",
        )
    )


@router.post("/undo", response_class=HTMLResponse)
def undo(request: Request, fecha: str = Form("")):
    notice_ok = notice_oob(
        templates, request, target="notice-container", message="Acción deshecha.", dismiss=2500
    )
    notice_empty = notice_oob(
        templates,
        request,
        target="notice-container",
        message="Nada que deshacer.",
        kind="notice-error",
        dismiss=2500,
    )
    try:
        result = undo_last_action(web_context.DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    if result["kind"] == "empty":
        return HTMLResponse(content=notice_empty)
    if result["kind"] == "sesion":
        fecha_iso = result["fecha_iso"]
        marker = undo_result_oob(templates, request, fecha_iso, result["has_data"], "sesion")
        if fecha == fecha_iso:
            outcome_ok = STATIC_MARKERS["outcome_ok"]
            editor = _editor_html(request, fecha_iso)
            return HTMLResponse(
                content=notice_ok
                + outcome_ok
                + marker
                + editor_wrap_oob(templates, request, editor)
            )
        return HTMLResponse(content=notice_ok + marker)
    if result["kind"] == "alimentacion":
        fecha_iso = result["fecha_iso"]
        marker = undo_result_oob(templates, request, fecha_iso, result["has_data"], "alimentacion")
        if fecha == fecha_iso:
            outcome_ok = STATIC_MARKERS["outcome_ok"]
            editor = _nutrition_editor_html(request, fecha_iso)
            return HTMLResponse(
                content=notice_ok
                + outcome_ok
                + marker
                + nutrition_editor_wrap_oob(templates, request, editor)
            )
        return HTMLResponse(content=notice_ok + marker)
    if result["kind"] == "splits":
        return HTMLResponse(
            content=notice_ok
            + fragment_oob(
                templates,
                request,
                "splits-section",
                _split_section_html(request),
                swap="outerHTML",
            )
        )
    return HTMLResponse(
        content=notice_ok
        + fragment_oob(
            templates,
            request,
            "plantillas-section",
            _plantillas_list_html(request),
            swap="outerHTML",
        )
    )
