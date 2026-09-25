"""API v1 de nutricion (spec 009)."""

import json
import logging
import math

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src import health_sync_service, web_context
from src.database import (
    find_plantilla_alimentacion_by_nombre,
    get_alimentos_catalog,
    get_diario_by_fecha,
    get_parametros_diarios,
    get_plantillas_alimentacion,
    get_prev_diary_date,
)
from src.http_shared import (
    MAX_FORM_SETS,
    MAX_NAME_LEN,
    TRAINING_API_SCHEMA_VERSION,
    _api_domain_error,
    _require_training_api_token,
)
from src.models import (
    AlimentoInput,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.mutation_service import (
    delete_diary_with_undo_snapshot,
    save_diary_with_undo_snapshot,
)
from src.nutrition_service import (
    MICRO_DRI_TARGETS,
    NUTRIENT_FIELDS,
    apply_meal_template,
    create_alimento,
    diary_totals,
    entries_from_form,
    objetivos_diarios,
    save_meal_template,
)
from src.training_service import (
    fecha_to_db,
    parse_form_date,
)
from src.ui_fragments import NUTRIENT_FIELD_LABELS

router = APIRouter()


NUTRITION_PARAM_DEFAULTS: dict[str, float] = {
    "peso_kg": 70.0,
    "factor_proteina": 1.5,
    "factor_grasa": 1.1,
    "kcal_objetivo": 2300.0,
    **MICRO_DRI_TARGETS,
}

# Parámetros editables desde el cliente vía API (la web solo envía los 4 de
# macros; los objetivos de micros son fijos DRI en el panel). Claves
# desconocidas se ignoran.
NUTRITION_EDITABLE_PARAMS: tuple[str, ...] = (
    "peso_kg",
    "factor_proteina",
    "factor_grasa",
    "kcal_objetivo",
    "fibra_objetivo",
    "hierro_objetivo",
    "calcio_objetivo",
    "vitamina_c_objetivo",
    "vitamina_a_objetivo",
    "magnesio_objetivo",
    "zinc_objetivo",
    "potasio_objetivo",
    "sodio_objetivo",
    "vitamina_d_objetivo",
    "vitamina_e_objetivo",
    "vitamina_k_objetivo",
    "folato_objetivo",
    "vitamina_b12_objetivo",
    "vitamina_b6_objetivo",
    "yodo_objetivo",
    "selenio_objetivo",
)


def _api_nutrient_row(r: dict) -> dict:
    return {
        "orden": r.get("orden"),
        "alimento": r.get("alimento"),
        "cantidad_g": r.get("cantidad_g"),
        **{field: r.get(field) for field in NUTRIENT_FIELDS},
    }


def _api_diario_payload(fecha_iso: str) -> dict:
    """Lee el día nutricional como el editor web (con prefill heredado)."""
    fecha = parse_form_date(fecha_iso)
    fecha_db = fecha_to_db(fecha)
    db_data = get_diario_by_fecha(web_context.DB_PATH, fecha_db)
    data = db_data
    prefill_source: str | None = None
    if not db_data:
        prefill_source = get_prev_diary_date(web_context.DB_PATH, fecha_db)
        if prefill_source is not None:
            data = get_diario_by_fecha(web_context.DB_PATH, prefill_source)
    params = get_parametros_diarios(web_context.DB_PATH, fecha_db) or {}
    if not params and prefill_source is not None:
        params = get_parametros_diarios(web_context.DB_PATH, prefill_source) or {}
    parametros = {**NUTRITION_PARAM_DEFAULTS, **{k: float(v) for k, v in params.items()}}
    consumido = diary_totals(data)
    consumido["cantidad_g"] = round(
        sum(float(r["cantidad_g"]) for r in data if r["cantidad_g"] is not None), 2
    )
    return {
        "schema_version": TRAINING_API_SCHEMA_VERSION,
        "fecha": fecha_db,
        "has_data": bool(db_data),
        "prefilled": prefill_source is not None,
        "prefill_source": prefill_source,
        "entradas": [_api_nutrient_row(dict(r)) for r in data],
        "consumido": consumido,
        "objetivo": objetivos_diarios(parametros),
        "parametros": parametros,
    }


def _api_nutrition_params(body: dict) -> dict:
    """Extrae y valida los 9 parámetros editables. Lanza ValidationError."""
    params: dict[str, float] = {}
    for key in NUTRITION_EDITABLE_PARAMS:
        if key not in body or body[key] is None or str(body[key]).strip() == "":
            continue
        try:
            value = float(str(body[key]).strip().replace(",", "."))
        except (TypeError, ValueError):
            raise ValidationError(f"El campo {key} debe ser numérico.")
        if not math.isfinite(value) or value < 0 or (key == "peso_kg" and value == 0):
            raise ValidationError(f"El campo {key} no es válido.")
        params[key] = value
    return params


@router.get("/api/v1/diario")
def api_nutrition_get_day(request: Request, fecha: str = Query(default="")):
    """Lee el día nutricional (entradas + consumido + objetivo + parámetros)."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        return JSONResponse(_api_diario_payload(fecha.strip()))
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("API diario GET fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)


@router.post("/api/v1/diario")
async def api_nutrition_save_day(request: Request):
    """Guarda el día nutricional (reemplazo total idempotente + parámetros)."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    fecha = body.get("fecha", "")
    entradas_raw = body.get("entradas", None)
    if not isinstance(fecha, str) or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    if not isinstance(entradas_raw, list) or not entradas_raw:
        return JSONResponse({"detail": "Debes registrar al menos un alimento."}, status_code=400)
    if len(entradas_raw) > MAX_FORM_SETS:
        return JSONResponse(
            {"detail": f"Demasiadas filas del diario (máx. {MAX_FORM_SETS})."},
            status_code=400,
        )
    alimentos: list[str] = []
    cantidades: list[str] = []
    for item in entradas_raw:
        if not isinstance(item, dict):
            return JSONResponse({"detail": "Entrada inválida."}, status_code=400)
        alimentos.append(str(item.get("alimento", "")))
        cantidades.append(str(item.get("cantidad_g", "")))
    try:
        params = _api_nutrition_params(body)
        entries = entries_from_form(alimentos, cantidades)
        if not entries:
            return JSONResponse(
                {"detail": "Debes registrar al menos un alimento."}, status_code=400
            )
        save_diary_with_undo_snapshot(
            web_context.DB_PATH, fecha.strip(), entries, parametros=params or None
        )
    except (ValidationError, NotFoundError, ConflictError) as exc:
        return _api_domain_error(exc, "mutations")
    except Exception:
        logging.getLogger("mutations").exception("API diario POST fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    try:
        payload = _api_diario_payload(fecha.strip())
    except Exception:
        logging.getLogger("dashboard").exception("API diario POST relectura fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    payload["saved_count"] = len(payload["entradas"]) if payload["has_data"] else 0
    return JSONResponse(payload)


@router.delete("/api/v1/diario")
def api_nutrition_delete_day(request: Request, fecha: str = Query(default="")):
    """Elimina el día nutricional (filas; no toca parámetros). Idempotente."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        delete_diary_with_undo_snapshot(web_context.DB_PATH, fecha.strip())
    except (ValidationError, NotFoundError, ConflictError) as exc:
        return _api_domain_error(exc, "mutations")
    except Exception:
        logging.getLogger("mutations").exception("API diario DELETE fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "fecha": fecha.strip(),
            "deleted": True,
        }
    )


@router.get("/api/v1/alimentos")
def api_nutrition_foods(request: Request):
    """Catálogo de alimentos (nutrientes por 100 g) + etiquetas del alta."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        catalog = get_alimentos_catalog(web_context.DB_PATH)
    except Exception:
        logging.getLogger("dashboard").exception("API alimentos fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "count": len(catalog),
            "alimentos": [
                {
                    "nombre": a["nombre"],
                    "categoria": a.get("categoria", ""),
                    **{field: a.get(field) for field in NUTRIENT_FIELDS},
                }
                for a in catalog
            ],
            "meta": {"nutrientes": NUTRIENT_FIELD_LABELS},
        }
    )


@router.post("/api/v1/alimento")
async def api_nutrition_food_create(request: Request):
    """Alta de alimento (por 100 g). 409 si duplicado."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    nombre = body.get("nombre", "")
    if not isinstance(nombre, str) or not nombre.strip():
        return JSONResponse({"detail": "El nombre del alimento es obligatorio."}, status_code=400)
    if len(nombre) > MAX_NAME_LEN:
        return JSONResponse(
            {"detail": f"Nombre demasiado largo (máx. {MAX_NAME_LEN})."}, status_code=400
        )
    categoria = body.get("categoria", "")
    if not isinstance(categoria, str):
        return JSONResponse({"detail": "Categoría inválida."}, status_code=400)
    if len(categoria) > MAX_NAME_LEN:
        return JSONResponse(
            {"detail": f"Categoría demasiado larga (máx. {MAX_NAME_LEN})."}, status_code=400
        )
    try:
        create_alimento(
            web_context.DB_PATH,
            AlimentoInput(
                nombre=nombre,
                categoria=categoria,
                **{field: body.get(field, 0) for field in NUTRIENT_FIELDS},
            ),
        )
    except (ValidationError, ConflictError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API alimento alta fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "alimento": {"nombre": nombre.strip(), "categoria": categoria.strip()},
        }
    )


@router.get("/api/v1/plantillas-comida")
def api_nutrition_templates(request: Request):
    """Lista de plantillas de comida con sus alimentos y cantidades."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        plantillas = get_plantillas_alimentacion(web_context.DB_PATH)
    except Exception:
        logging.getLogger("dashboard").exception("API plantillas comida fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "count": len(plantillas),
            "plantillas": [
                {
                    "id": p["id"],
                    "nombre": p["nombre"],
                    "alimentos": list(p["alimentos"]),
                }
                for p in plantillas
            ],
        }
    )


@router.post("/api/v1/plantilla-comida/aplicar")
async def api_nutrition_template_apply(request: Request):
    """Preview de plantilla de comida: nutrientes recalculados, sin escribir."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    plantilla_id = body.get("plantilla_id", None)
    fecha = body.get("fecha", "")
    if isinstance(plantilla_id, bool) or not isinstance(plantilla_id, int):
        return JSONResponse({"detail": "plantilla_id requerido (entero)."}, status_code=400)
    if not isinstance(fecha, str) or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        parsed = parse_form_date(fecha.strip())
        rows = apply_meal_template(web_context.DB_PATH, plantilla_id)
    except (ValidationError, NotFoundError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API plantilla comida aplicar fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "plantilla_id": plantilla_id,
            "fecha": fecha_to_db(parsed),
            "entradas": [_api_nutrient_row(dict(r)) for r in rows],
        }
    )


@router.post("/api/v1/plantilla-comida/guardar")
async def api_nutrition_template_save(request: Request):
    """Guarda el día como plantilla de comida (upsert por nombre, sin undo)."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
    nombre = body.get("nombre", "")
    entradas_raw = body.get("entradas", None)
    if not isinstance(nombre, str) or not nombre.strip():
        return JSONResponse(
            {"detail": "El nombre de la plantilla no puede estar vacío."}, status_code=400
        )
    if len(nombre) > MAX_NAME_LEN:
        return JSONResponse(
            {"detail": f"Nombre demasiado largo (máx. {MAX_NAME_LEN})."}, status_code=400
        )
    if not isinstance(entradas_raw, list) or not entradas_raw:
        return JSONResponse(
            {"detail": "La plantilla debe tener al menos un alimento."}, status_code=400
        )
    rows: list[dict] = []
    for item in entradas_raw:
        if not isinstance(item, dict):
            return JSONResponse({"detail": "Entrada inválida."}, status_code=400)
        rows.append(
            {"alimento": str(item.get("alimento", "")), "cantidad_g": item.get("cantidad_g", "")}
        )
    try:
        existing = find_plantilla_alimentacion_by_nombre(web_context.DB_PATH, nombre.strip())
        save_meal_template(web_context.DB_PATH, nombre.strip(), rows)
        pid = existing
        if pid is None:
            pid = find_plantilla_alimentacion_by_nombre(web_context.DB_PATH, nombre.strip())
    except (ValidationError, ConflictError, NotFoundError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API plantilla comida guardar fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "plantilla": {"id": pid, "nombre": nombre.strip(), "updated": existing is not None},
        }
    )
