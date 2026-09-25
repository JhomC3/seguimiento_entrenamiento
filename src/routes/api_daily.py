"""API v1 de cardio y fechas del dia (spec 009)."""

import json
import logging
import math

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src import health_sync_service, web_context
from src.cardio_service import (
    CardioAnnotationInput,
    get_day_cardio,
    upsert_cardio_annotation,
)
from src.http_shared import (
    TRAINING_API_SCHEMA_VERSION,
    _api_domain_error,
    _require_training_api_token,
)
from src.models import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.training_service import (
    parse_form_date,
)

router = APIRouter()


def _api_float_or_none(value, field: str) -> float | None:
    """Número finito o None (ausente/vacío). Lanza ValidationError si no numérico."""
    if value is None or str(value).strip() == "":
        return None
    try:
        num = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    if not math.isfinite(num):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    return num


@router.get("/api/v1/cardio")
def api_cardio_day(request: Request, fecha: str = Query(default="")):
    """Sesiones EXERCISE_SESSION del día con su anotación manual."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        parse_form_date(fecha.strip())
        sesiones = get_day_cardio(web_context.DB_PATH, fecha.strip())
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("API cardio GET fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "fecha": fecha.strip(),
            "count": len(sesiones),
            "sesiones": sesiones,
        }
    )


@router.post("/api/v1/cardio/anotacion")
async def api_cardio_annotate(request: Request):
    """Anota velocidad/inclinación/notas (upsert; todo vacío = borrar)."""
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
    hc_id = body.get("hc_id", "")
    if not isinstance(hc_id, str) or not hc_id.strip():
        return JSONResponse({"detail": "El campo hc_id es obligatorio."}, status_code=400)
    notas = body.get("notas", "")
    if notas is None:
        notas = ""
    if not isinstance(notas, str):
        return JSONResponse({"detail": "El campo notas es inválido."}, status_code=400)
    try:
        velocidad = _api_float_or_none(body.get("velocidad_kmh"), "velocidad_kmh")
        inclinacion = _api_float_or_none(body.get("inclinacion_pct"), "inclinacion_pct")
        upsert_cardio_annotation(
            web_context.DB_PATH,
            CardioAnnotationInput(
                hc_id=hc_id.strip(),
                velocidad_kmh=velocidad,
                inclinacion_pct=inclinacion,
                notas=notas,
            ),
        )
    except (ValidationError, NotFoundError, ConflictError) as exc:
        return _api_domain_error(exc, "dashboard")
    except Exception:
        logging.getLogger("dashboard").exception("API cardio POST fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    deleted = velocidad is None and inclinacion is None and not notas.strip()
    return JSONResponse(
        {"schema_version": TRAINING_API_SCHEMA_VERSION, "hc_id": hc_id.strip(), "deleted": deleted}
    )


@router.get("/api/v1/fechas")
def api_day_dates(request: Request, vista: str = Query(default="entrenamiento")):
    """Fechas con datos para los puntos del carrusel (por pestaña)."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if vista not in ("entrenamiento", "alimentacion", "todas"):
        return JSONResponse(
            {"detail": "Vista inválida (entrenamiento|alimentacion|todas)."},
            status_code=400,
        )
    try:
        from src.database import get_daily_data_dates

        if vista == "todas":
            fechas = sorted(
                get_daily_data_dates(web_context.DB_PATH, "entrenamiento")
                | get_daily_data_dates(web_context.DB_PATH, "alimentacion")
            )
        else:
            fechas = sorted(get_daily_data_dates(web_context.DB_PATH, vista))
    except Exception:
        logging.getLogger("dashboard").exception("API fechas fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {"schema_version": TRAINING_API_SCHEMA_VERSION, "vista": vista, "fechas": fechas}
    )
