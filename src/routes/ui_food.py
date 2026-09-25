"""Rutas UI de entreno y alimentacion (spec 009)."""

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from src import web_context
from src.database import (
    get_sets_by_fecha,
)
from src.exercise_service import create_exercise
from src.http_shared import (
    MAX_FORM_SETS,
    MAX_NAME_LEN,
    MAX_REORDER_IDS,
    _check_lote,
    _domain_error_response,
    _today_iso,
)
from src.models import (
    AlimentoInput,
)
from src.mutation_service import (
    delete_diary_with_undo_snapshot,
    delete_session,
    save_diary_with_undo_snapshot,
    save_session_with_undo_snapshot,
)
from src.nutrition_service import (
    apply_meal_template,
    create_alimento,
    entries_from_form,
    save_meal_template,
)
from src.response_fragments import (
    STATIC_MARKERS,
    app_config_oob,
    editor_state_oob,
    editor_wrap_oob,
    fragment_oob,
    notice_oob,
    nutrition_editor_wrap_oob,
)
from src.training_service import (
    fecha_to_db,
    parse_form_date,
    sets_from_form,
)
from src.ui_fragments import (
    _alimento_form_html,
    _daily_app_config,
    _editor_html,
    _exercise_form_html,
    _nutrition_app_config,
    _nutrition_editor_html,
    _plantillas_alimentacion_list_html,
    _split_catalog_html,
    _template_count_oob,
)
from src.web_context import templates

router = APIRouter()


@router.post("/entrenamiento/session/save", response_class=HTMLResponse)
def entrenamiento_session_save(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
    descanso: list[str] = Form(default=[]),
    velocidad: list[str] = Form(default=[]),
    dificultad: list[str] = Form(default=[]),
):
    _check_lote(ejercicio, MAX_FORM_SETS, "series")
    sets = sets_from_form(
        ejercicio, kg, reps, rir, descansos=descanso, velocidades=velocidad, dificultades=dificultad
    )
    notice_success = notice_oob(
        templates, request, target="editor-notice", message="Entrenamiento guardado."
    )
    outcome_ok = STATIC_MARKERS["outcome_ok"]
    outcome_fail = STATIC_MARKERS["outcome_fail"]
    try:
        save_session_with_undo_snapshot(web_context.DB_PATH, fecha, sets)
        saved_rows = get_sets_by_fecha(web_context.DB_PATH, fecha_to_db(parse_form_date(fecha)))
        if saved_rows:
            return HTMLResponse(
                content=notice_success + outcome_ok + editor_state_oob(templates, request)
            )
        editor = _editor_html(request, fecha)
        return HTMLResponse(
            content=notice_success + outcome_ok + editor_wrap_oob(templates, request, editor)
        )
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice", extra=outcome_fail)


@router.post("/entrenamiento/session/eliminar", response_class=HTMLResponse)
def entrenamiento_session_eliminar(request: Request, fecha: str = Form(...)):
    notice = notice_oob(templates, request, target="editor-notice", message="Entreno eliminado.")
    outcome_ok = STATIC_MARKERS["outcome_ok"]
    outcome_fail = STATIC_MARKERS["outcome_fail"]
    try:
        delete_session(web_context.DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(request, e, "editor-notice", extra=outcome_fail)
    editor = _editor_html(request, fecha)
    return HTMLResponse(content=notice + outcome_ok + editor_wrap_oob(templates, request, editor))


@router.post("/ejercicio/nuevo", response_class=HTMLResponse)
def ejercicio_nuevo(
    request: Request,
    ejercicio: str = Form(..., max_length=MAX_NAME_LEN),
    grupo_muscular: str = Form(..., max_length=MAX_NAME_LEN),
    categoria: str | None = Form(None, max_length=MAX_NAME_LEN),
):
    try:
        create_exercise(web_context.DB_PATH, ejercicio, grupo_muscular, categoria)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice_success = notice_oob(
        templates,
        request,
        target="notice-container",
        message=f"Ejercicio '{ejercicio.strip()}' creado.",
    )
    form_html = _exercise_form_html(request)
    extra = ""
    if "/splits" in (request.headers.get("hx-current-url", "") or ""):
        # Alta desde el panel de splits: refresca su catálogo (server-side,
        # no se re-renderiza solo) para que el chip nuevo exista al instante.
        extra = fragment_oob(templates, request, "splits-catalog", _split_catalog_html(request))
    return HTMLResponse(
        content=notice_success
        + app_config_oob(_daily_app_config())
        + fragment_oob(templates, request, "exercise-create", form_html, swap="outerHTML")
        + extra
    )


@router.get("/alimentacion/editor", response_class=HTMLResponse)
def alimentacion_editor(request: Request, fecha: str = Query(...)):
    return HTMLResponse(content=_nutrition_editor_html(request, fecha))


@router.post("/alimentacion/save", response_class=HTMLResponse)
def alimentacion_save(
    request: Request,
    fecha: str = Form(...),
    alimento: list[str] = Form(default=[]),
    cantidad: list[str] = Form(default=[]),
    peso_kg: float | None = Form(None),
    factor_proteina: float | None = Form(None),
    factor_grasa: float | None = Form(None),
    kcal_objetivo: float | None = Form(None),
):
    notice = notice_oob(templates, request, target="notice-container", message="Día guardado.")
    parametros = {
        "peso_kg": peso_kg,
        "factor_proteina": factor_proteina,
        "factor_grasa": factor_grasa,
        "kcal_objetivo": kcal_objetivo,
    }
    parametros = {k: v for k, v in parametros.items() if v is not None}
    try:
        entries = entries_from_form(alimento, cantidad)
        save_diary_with_undo_snapshot(
            web_context.DB_PATH, fecha, entries, parametros=parametros or None
        )
    except Exception as e:
        return _domain_error_response(
            request, e, "notice-container", extra=STATIC_MARKERS["outcome_fail"]
        )
    editor = _nutrition_editor_html(request, fecha)
    return HTMLResponse(
        content=notice
        + STATIC_MARKERS["outcome_ok"]
        + nutrition_editor_wrap_oob(templates, request, editor)
    )


@router.post("/alimentacion/eliminar", response_class=HTMLResponse)
def alimentacion_eliminar(request: Request, fecha: str = Form(...)):
    notice = notice_oob(templates, request, target="notice-container", message="Día eliminado.")
    try:
        delete_diary_with_undo_snapshot(web_context.DB_PATH, fecha)
    except Exception as e:
        return _domain_error_response(
            request, e, "notice-container", extra=STATIC_MARKERS["outcome_fail"]
        )
    editor = _nutrition_editor_html(request, fecha)
    return HTMLResponse(
        content=notice
        + STATIC_MARKERS["outcome_ok"]
        + nutrition_editor_wrap_oob(templates, request, editor)
    )


@router.post("/alimento/nuevo", response_class=HTMLResponse)
def alimento_nuevo(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    categoria: str = Form("", max_length=MAX_NAME_LEN),
    kcal: float = Form(0),
    carbohidratos: float = Form(0),
    fibra: float = Form(0),
    proteina: float = Form(0),
    grasa: float = Form(0),
    hierro: float = Form(0),
    calcio: float = Form(0),
    vitamina_c: float = Form(0),
    vitamina_a: float = Form(0),
    magnesio: float = Form(0),
    zinc: float = Form(0),
    potasio: float = Form(0),
    sodio: float = Form(0),
    vitamina_d: float = Form(0),
    vitamina_e: float = Form(0),
    vitamina_k: float = Form(0),
    folato: float = Form(0),
    vitamina_b12: float = Form(0),
    vitamina_b6: float = Form(0),
    yodo: float = Form(0),
    selenio: float = Form(0),
):
    try:
        create_alimento(
            web_context.DB_PATH,
            AlimentoInput(
                nombre=nombre,
                categoria=categoria,
                kcal=kcal,
                carbohidratos=carbohidratos,
                fibra=fibra,
                proteina=proteina,
                grasa=grasa,
                hierro=hierro,
                calcio=calcio,
                vitamina_c=vitamina_c,
                vitamina_a=vitamina_a,
                magnesio=magnesio,
                zinc=zinc,
                potasio=potasio,
                sodio=sodio,
                vitamina_d=vitamina_d,
                vitamina_e=vitamina_e,
                vitamina_k=vitamina_k,
                folato=folato,
                vitamina_b12=vitamina_b12,
                vitamina_b6=vitamina_b6,
                yodo=yodo,
                selenio=selenio,
            ),
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates,
        request,
        target="notice-container",
        message=f"Alimento '{nombre.strip()}' creado.",
    )
    form_html = _alimento_form_html(request)
    return HTMLResponse(
        content=notice
        + app_config_oob(_nutrition_app_config())
        + fragment_oob(templates, request, "alimento-create", form_html, swap="outerHTML")
    )


@router.post("/alimentacion/plantilla/guardar", response_class=HTMLResponse)
def plantilla_alimentacion_guardar(
    request: Request,
    nombre: str = Form(..., max_length=MAX_NAME_LEN),
    alimento: list[str] = Form(default=[]),
    cantidad: list[str] = Form(default=[]),
):
    try:
        entries = entries_from_form(alimento, cantidad)
        rows = [{"alimento": e.alimento, "cantidad_g": float(e.cantidad_g)} for e in entries]
        save_meal_template(web_context.DB_PATH, nombre, rows)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    notice = notice_oob(
        templates, request, target="notice-container", message="Plantilla guardada."
    )
    return HTMLResponse(
        content=notice
        + fragment_oob(
            templates,
            request,
            "nutrition-templates-section",
            _plantillas_alimentacion_list_html(request, _today_iso()),
            swap="outerHTML",
        )
        + _template_count_oob(request, "food")
    )


@router.post("/alimentacion/plantilla/eliminar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_alimentacion_eliminar(request: Request, plantilla_id: int):
    from src.database import delete_plantilla_alimentacion

    try:
        delete_plantilla_alimentacion(web_context.DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(
        content=fragment_oob(
            templates,
            request,
            "nutrition-templates-section",
            _plantillas_alimentacion_list_html(request, _today_iso()),
            swap="outerHTML",
        )
        + _template_count_oob(request, "food")
    )


@router.post("/alimentacion/plantilla/reordenar", response_class=HTMLResponse)
def plantilla_alimentacion_reordenar(request: Request, id: list[int] = Form(default=[])):
    from src.database import reorder_plantillas_alimentacion

    try:
        _check_lote(id, MAX_REORDER_IDS, "orden")
        reorder_plantillas_alimentacion(web_context.DB_PATH, id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content="")


@router.get("/alimentacion/plantilla/aplicar/{plantilla_id}", response_class=HTMLResponse)
def plantilla_alimentacion_aplicar(request: Request, plantilla_id: int, fecha: str = Query(...)):
    try:
        rows = apply_meal_template(web_context.DB_PATH, plantilla_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    editor = _nutrition_editor_html(request, fecha, rows=rows, force_editable=True)
    notice = notice_oob(
        templates, request, target="notice-container", message="Plantilla aplicada."
    )
    return HTMLResponse(content=notice + nutrition_editor_wrap_oob(templates, request, editor))
