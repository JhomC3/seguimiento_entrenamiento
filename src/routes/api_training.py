"""API v1 de entrenamiento (spec 009)."""

import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from config import MUSCLE_CATEGORIES
from src import health_sync_service, web_context
from src.database import (
    get_plantillas,
    get_split_catalog,
)
from src.exercise_service import categoria_for_grupo, create_exercise, last_exercise_payload
from src.http_shared import (
    MAX_NAME_LEN,
    TRAINING_API_SCHEMA_VERSION,
    _api_domain_error,
    _api_num,
    _require_training_api_token,
)
from src.metrics_engine import rm_ajustado
from src.models import (
    ConflictError,
    NotFoundError,
    TemplateInput,
    ValidationError,
)
from src.mutation_service import (
    peek_undo,
    save_template_with_undo_snapshot,
    undo_last_action,
)
from src.suggestion_service import resolve_suggestion
from src.template_service import apply_template_rows
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_to_db,
    parse_form_date,
)
from src.web_context import CICLO_START_DATE

router = APIRouter()


@router.get("/api/v1/ejercicios")
def api_training_exercises(request: Request):
    """Catálogo de ejercicios para el editor móvil. Requiere X-Sync-Token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        catalog = get_split_catalog(web_context.DB_PATH)
    except Exception:
        logging.getLogger("dashboard").exception("API ejercicios fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "count": len(catalog),
            "ejercicios": catalog,
            # meta aditiva (v1.1, sin bump): lo que el alta web ofrece en sus
            # selects (categorías canónicas + músculos). El cliente ignora lo
            # desconocido; los APK viejos siguen funcionando.
            "meta": {"categorias": MUSCLE_CATEGORIES},
        }
    )


def _api_preview_row(
    ejercicio: str, kg, reps, rir, descanso_seg, orden: int, velocidad_kmh=None, dificultad=None
) -> dict:
    kg_n, reps_n, rir_n, desc_n = (_api_num(v) for v in (kg, reps, rir, descanso_seg))
    vel_n, dif_n = (_api_num(v) for v in (velocidad_kmh, dificultad))
    rm: float | None = None
    try:
        if kg_n is not None and reps_n is not None:
            rm = round(rm_ajustado(kg_n, reps_n, rir_n or 0.0), 1)
    except (TypeError, ValueError):
        rm = None
    return {
        "set_orden": orden,
        "ejercicio": ejercicio,
        "kg": kg_n,
        "reps": reps_n,
        "rir": rir_n,
        "descanso_seg": desc_n,
        "rm": rm,
        "velocidad_kmh": vel_n,
        "dificultad": dif_n,
    }


@router.get("/api/v1/plantillas")
def api_training_templates(request: Request):
    """Lista de entrenos (plantillas) con sus ejercicios. Requiere token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        plantillas = get_plantillas(web_context.DB_PATH)
    except Exception:
        logging.getLogger("dashboard").exception("API plantillas fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "count": len(plantillas),
            "plantillas": [
                {
                    "id": p["id"],
                    "nombre": p["nombre"],
                    "clasificacion": p["clasificacion"],
                    "ejercicios": list(p["ejercicios"]),
                }
                for p in plantillas
            ],
        }
    )


@router.post("/api/v1/plantilla/aplicar")
async def api_training_template_apply(request: Request):
    """Preview de un entreno sobre una fecha, sin escribir (como la web).

    El móvil muestra el preview en el editor; el guardado posterior es el
    POST /api/v1/sesion normal. Requiere X-Sync-Token.
    """
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
        rows = apply_template_rows(web_context.DB_PATH, plantilla_id)
    except (ValidationError, NotFoundError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API plantilla aplicar fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "plantilla_id": plantilla_id,
            "fecha": fecha_to_db(parsed),
            "semana": calculate_cycle_week(parsed, CICLO_START_DATE),
            "dia": day_from_date(parsed),
            "sets": [
                _api_preview_row(
                    r.ejercicio,
                    r.kg,
                    r.reps,
                    r.rir,
                    r.descanso_seg,
                    idx,
                    r.velocidad_kmh,
                    r.dificultad,
                )
                for idx, r in enumerate(rows, start=1)
            ],
        }
    )


@router.post("/api/v1/plantilla/guardar")
async def api_training_template_save(request: Request):
    """Guarda el día como entreno (upsert por nombre, como la web)."""
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
    ejercicios = body.get("ejercicios", None)
    if not isinstance(nombre, str) or not nombre.strip():
        return JSONResponse({"detail": "Debes ponerle nombre al entreno."}, status_code=400)
    if not isinstance(ejercicios, list) or not ejercicios:
        return JSONResponse(
            {"detail": "El entreno debe tener al menos un ejercicio."}, status_code=400
        )
    if len(nombre) > MAX_NAME_LEN:
        return JSONResponse(
            {"detail": f"Nombre demasiado largo (máx. {MAX_NAME_LEN})."}, status_code=400
        )
    try:
        result = save_template_with_undo_snapshot(
            web_context.DB_PATH,
            TemplateInput(nombre=nombre, ejercicios=[str(e) for e in ejercicios]),
        )
    except (ValidationError, ConflictError) as exc:
        return _api_domain_error(exc, "mutations")
    except Exception:
        logging.getLogger("mutations").exception("API plantilla guardar fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "plantilla": {
                "id": result.id,
                "nombre": result.nombre,
                "clasificacion": result.clasificacion,
                "ejercicios": list(result.ejercicios),
                "updated": result.updated,
            },
        }
    )


@router.post("/api/v1/ejercicio")
async def api_training_exercise_create(request: Request):
    """Alta de ejercicio en el catálogo (origen manual). 409 si duplicado.

    La categoría se deriva del grupo muscular en el servidor (el campo
    ``categoria`` se acepta por compatibilidad pero se ignora).
    """
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
    for field in ("ejercicio", "grupo_muscular"):
        value = body.get(field, "")
        if not isinstance(value, str) or not value.strip():
            return JSONResponse({"detail": f"El campo {field} es obligatorio."}, status_code=400)
        if len(value) > MAX_NAME_LEN:
            return JSONResponse(
                {"detail": f"El campo {field} es demasiado largo (máx. {MAX_NAME_LEN})."},
                status_code=400,
            )
    categoria_raw = body.get("categoria", "")
    categoria = categoria_raw.strip() if isinstance(categoria_raw, str) else ""
    try:
        create_exercise(
            web_context.DB_PATH,
            str(body["ejercicio"]),
            str(body["grupo_muscular"]),
            categoria or None,
        )
    except (ValidationError, ConflictError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API ejercicio alta fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "ejercicio": {
                "ejercicio": str(body["ejercicio"]).strip(),
                "grupo_muscular": str(body["grupo_muscular"]).strip(),
                "categoria": categoria_for_grupo(str(body["grupo_muscular"])),
            },
        }
    )


@router.get("/api/v1/undo/peek")
def api_undo_peek(request: Request):
    """Describe la entrada deshacer-able sin consumirla. Requiere token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        entry = peek_undo(web_context.DB_PATH)
    except Exception:
        logging.getLogger("mutations").exception("API undo peek fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    payload: dict = {"schema_version": TRAINING_API_SCHEMA_VERSION, "kind": entry["kind"]}
    if "fecha_iso" in entry:
        payload["fecha_iso"] = entry["fecha_iso"]
    return JSONResponse(payload)


@router.post("/api/v1/undo")
async def api_undo(request: Request):
    """Deshace la última acción (consume 1 entrada). kind empty = nada."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    fecha = ""
    if raw_body.strip():
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"detail": "Cuerpo JSON inválido."}, status_code=400)
        raw_fecha = body.get("fecha", "")
        if raw_fecha is None:
            raw_fecha = ""
        if not isinstance(raw_fecha, str):
            return JSONResponse({"detail": "Fecha inválida."}, status_code=400)
        fecha = raw_fecha.strip()
    try:
        result = undo_last_action(web_context.DB_PATH, fecha)
    except (ValidationError, NotFoundError, ConflictError) as exc:
        return _api_domain_error(exc, "mutations")
    except Exception:
        logging.getLogger("mutations").exception("API undo fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    payload = {"schema_version": TRAINING_API_SCHEMA_VERSION, "kind": result["kind"]}
    if "fecha_iso" in result:
        payload["fecha_iso"] = result["fecha_iso"]
    if "has_data" in result:
        payload["has_data"] = result["has_data"] == "1"
    return JSONResponse(payload)


@router.get("/api/v1/sugerencia")
def api_training_suggestion(request: Request, fecha: str = Query(default="")):
    """Rutina sugerida del día (split + historial, sin escribir)."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        s = resolve_suggestion(web_context.DB_PATH, fecha.strip())
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("API sugerencia fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "fecha": s.fecha,
            "tipo": s.tipo,
            "explicacion": s.explicacion,
            "split_id": s.split_id,
            "slot_dia": s.slot_dia,
            "pendiente_desde": s.pendiente_desde,
            "ejercicios": list(s.ejercicios),
            "sets": [
                {
                    "ejercicio": x.ejercicio,
                    "kg": x.kg,
                    "reps": x.reps,
                    "rir": x.rir,
                    "descanso_seg": x.descanso_seg,
                    "fuente_fecha": x.fuente_fecha,
                    "velocidad_kmh": x.velocidad_kmh,
                    "dificultad": x.dificultad,
                }
                for x in s.sets
            ],
        }
    )


@router.get("/api/v1/ejercicio/ultimo")
def api_exercise_last(
    request: Request,
    ejercicio: str = Query(default=""),
    fecha: str = Query(default=""),
):
    """Últimas series de un ejercicio (autofill móvil, paridad con web).

    Misma fuente que la rueda. Requiere X-Sync-Token. `fecha` opcional
    excluye ese día y posteriores.
    """
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    try:
        payload = last_exercise_payload(
            web_context.DB_PATH, (ejercicio or "").strip(), (fecha or "").strip() or None
        )
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("API ejercicio ultimo fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse({"schema_version": TRAINING_API_SCHEMA_VERSION, **payload})
