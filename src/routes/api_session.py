"""API de sesion, respiracion y health-sync (spec 009)."""

import hmac
import json
import logging
import uuid

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src import health_sync_service, http_shared, web_context
from src.breathing_service import validate_session_payload
from src.database import (
    get_breathing_sessions_by_fecha,
    get_sets_by_fecha,
)
from src.health_sync_service import ingest_health_records, parse_payload
from src.http_shared import (
    MAX_FORM_SETS,
    TRAINING_API_SCHEMA_VERSION,
    _require_training_api_token,
)
from src.metrics_engine import rm_ajustado
from src.models import (
    TrainingSetInput,
    ValidationError,
)
from src.mutation_service import (
    delete_breathing_session,
    delete_session,
    save_breathing_session,
    save_session_with_undo_snapshot,
)
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_to_db,
    parse_form_date,
)
from src.web_context import CICLO_START_DATE

router = APIRouter()


@router.post("/sync/health-connect")
async def health_sync_ingest(request: Request):
    """API ingestion endpoint (JSON, not htmx): CSRF-exempt by exact path in
    src/security.py; authenticated with X-Sync-Token (HC_SYNC_TOKEN env)."""
    if not http_shared.HC_SYNC_TOKEN:
        return JSONResponse({"detail": "Endpoint no configurado (HC_SYNC_TOKEN)"}, status_code=503)
    token = request.headers.get("X-Sync-Token", "")
    if not token or not hmac.compare_digest(token, http_shared.HC_SYNC_TOKEN):
        return JSONResponse({"detail": "Token inválido"}, status_code=401)
    raw_body = await request.body()
    if len(raw_body) > health_sync_service.MAX_BODY_BYTES:
        return JSONResponse({"detail": "Lote excesivo"}, status_code=413)
    try:
        payload = parse_payload(json.loads(raw_body))
    except (json.JSONDecodeError, ValidationError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    try:
        result = ingest_health_records(web_context.DB_PATH, payload)
    except Exception:
        logging.getLogger("health_sync").exception("ingesta fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": 1,
            "received": result.received,
            "accepted_count": result.accepted_count,
            "accepted": [{"hc_id": a.hc_id, "revision": a.revision} for a in result.accepted],
            "rejected": [
                {"hc_id": r.hc_id, "revision": r.revision, "reason": r.reason}
                for r in result.rejected
            ],
        }
    )


def _api_set_row(row: dict) -> dict:
    """Fila de training_sets → objeto JSON de la API (con RM recalculado)."""
    kg = row.get("kg")
    reps = row.get("reps")
    rir = row.get("rir")
    rm: float | None = None
    try:
        if kg is not None and reps is not None:
            rm = round(rm_ajustado(float(kg), float(reps), float(rir or 0.0)), 1)
    except (TypeError, ValueError):
        rm = None
    return {
        "set_orden": row.get("set_orden"),
        "ejercicio": row.get("ejercicio"),
        "kg": kg,
        "reps": reps,
        "rir": rir,
        "descanso_seg": row.get("descanso_seg"),
        "rm": rm,
        "velocidad_kmh": row.get("velocidad_kmh"),
        "dificultad": row.get("dificultad"),
    }


def _api_session_payload(fecha_iso: str) -> dict:
    """Lee el día y lo serializa. Lanza ValidationError con fecha inválida."""
    fecha = parse_form_date(fecha_iso)
    fecha_db = fecha_to_db(fecha)
    rows = get_sets_by_fecha(web_context.DB_PATH, fecha_db)
    return {
        "schema_version": TRAINING_API_SCHEMA_VERSION,
        "fecha": fecha_db,
        "semana": calculate_cycle_week(fecha, CICLO_START_DATE),
        "dia": day_from_date(fecha),
        "has_data": bool(rows),
        "sets": [_api_set_row(dict(r)) for r in rows],
    }


@router.get("/api/v1/sesion")
def api_training_get_sesion(request: Request, fecha: str = Query(default="")):
    """Lee la sesión de un día (ver diario). Requiere X-Sync-Token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        return JSONResponse(_api_session_payload(fecha.strip()))
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("dashboard").exception("API sesion GET fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)


@router.post("/api/v1/sesion")
async def api_training_save_sesion(request: Request):
    """Guarda (reemplazo total del día) la sesión. Requiere X-Sync-Token.

    POST repetido con el mismo cuerpo es idempotente por construcción
    (DELETE + INSERT ordenado). Toda fecha ISO válida es editable: no se
    aplica el gating readonly del editor web (UX, no seguridad); el
    last-write-wins está documentado en training-api-contract.md §5.
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
    fecha = body.get("fecha", "")
    sets_raw = body.get("sets", None)
    if not isinstance(fecha, str) or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    if not isinstance(sets_raw, list) or not sets_raw:
        return JSONResponse({"detail": "Debes registrar al menos una serie."}, status_code=400)
    if len(sets_raw) > MAX_FORM_SETS:
        return JSONResponse(
            {"detail": f"Demasiadas filas de sesión (máx. {MAX_FORM_SETS})."},
            status_code=400,
        )
    inputs: list[TrainingSetInput] = []
    for item in sets_raw:
        if not isinstance(item, dict):
            return JSONResponse({"detail": "Serie inválida."}, status_code=400)
        inputs.append(
            TrainingSetInput(
                ejercicio=item.get("ejercicio", ""),
                kg=item.get("kg", ""),
                reps=item.get("reps", ""),
                rir=item.get("rir", ""),
                descanso_seg=item.get("descanso_seg", ""),
                velocidad_kmh=item.get("velocidad_kmh", ""),
                dificultad=item.get("dificultad", ""),
            )
        )
    try:
        result = save_session_with_undo_snapshot(web_context.DB_PATH, fecha.strip(), inputs)
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("mutations").exception("API sesion POST fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    try:
        payload = _api_session_payload(result.fecha)
    except Exception:
        logging.getLogger("dashboard").exception("API sesion POST relectura fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    payload["saved_count"] = len(payload["sets"])
    return JSONResponse(payload)


@router.delete("/api/v1/sesion")
def api_training_delete_sesion(request: Request, fecha: str = Query(default="")):
    """Elimina el día completo. Idempotente: día ya vacío → 200. Requiere token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        delete_session(web_context.DB_PATH, fecha.strip())
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        logging.getLogger("mutations").exception("API sesion DELETE fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "fecha": fecha.strip(),
            "deleted": True,
        }
    )


def _api_breathing_row(row: dict) -> dict:
    """Fila de breathing_sessions → objeto JSON de la API (métricas de servidor)."""
    return {
        "client_session_id": row.get("client_session_id"),
        "fecha": row.get("fecha"),
        "start_epoch_ms": row.get("start_epoch_ms"),
        "end_epoch_ms": row.get("end_epoch_ms"),
        "time_zone_offset_minutes": row.get("time_zone_offset_minutes"),
        "duracion_planeada_sec": row.get("duracion_planeada_sec"),
        "duracion_real_sec": row.get("duracion_real_sec"),
        "patron": {
            "inhale_s": row.get("inhale_s"),
            "hold_in_s": row.get("hold_in_s"),
            "exhale_s": row.get("exhale_s"),
            "hold_out_s": row.get("hold_out_s"),
            "ramp_sec": row.get("ramp_sec"),
            "end_inhale_s": row.get("end_inhale_s"),
            "end_hold_in_s": row.get("end_hold_in_s"),
            "end_exhale_s": row.get("end_exhale_s"),
            "end_hold_out_s": row.get("end_hold_out_s"),
        },
        "ciclos_completados": row.get("ciclos_completados"),
        "bpm_medio": row.get("bpm_medio"),
        "completada": bool(row.get("completada")),
    }


@router.post("/api/v1/respiracion/sesion")
async def api_breathing_save_sesion(request: Request):
    """Guarda una sesión de respiración (B5.0). Requiere X-Sync-Token.

    Append-only idempotente por `client_session_id`: el re-POST del mismo
    cuerpo devuelve los mismos valores con `saved: false` (el móvil puede
    reintentar sin miedo a duplicar). Ciclos/BPM/fecha se recalculan en
    servidor; lo que envíe el cliente se valida pero nunca se almacena.
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
    try:
        session_input = validate_session_payload(body)
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    try:
        result = save_breathing_session(web_context.DB_PATH, session_input)
    except Exception:
        logging.getLogger("mutations").exception("API respiracion POST fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    row = result["row"]
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "client_session_id": row["client_session_id"],
            "fecha": row["fecha"],
            "ciclos_completados": row["ciclos_completados"],
            "bpm_medio": row["bpm_medio"],
            "duracion_real_sec": row["duracion_real_sec"],
            "saved": result["saved"],
        }
    )


@router.get("/api/v1/respiracion/sesiones")
def api_breathing_day(request: Request, fecha: str = Query(default="")):
    """Sesiones de respiración de un día (ver historial). Requiere X-Sync-Token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not fecha or not fecha.strip():
        return JSONResponse({"detail": "Fecha requerida (YYYY-MM-DD)."}, status_code=400)
    try:
        fecha_db = fecha_to_db(parse_form_date(fecha.strip()))
    except ValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    try:
        rows = get_breathing_sessions_by_fecha(web_context.DB_PATH, fecha_db)
    except Exception:
        logging.getLogger("dashboard").exception("API respiracion GET fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    sesiones = [_api_breathing_row(dict(r)) for r in rows]
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "fecha": fecha_db,
            "count": len(sesiones),
            "sesiones": sesiones,
            "minutos_totales": round(sum(s["duracion_real_sec"] for s in sesiones) / 60, 1),
            "ciclos_totales": sum(s["ciclos_completados"] for s in sesiones),
        }
    )


@router.delete("/api/v1/respiracion/sesion")
def api_breathing_delete_sesion(request: Request, client_session_id: str = Query(default="")):
    """Elimina una sesión por su UUID. Idempotente. Requiere X-Sync-Token."""
    auth_error = _require_training_api_token(request)
    if auth_error is not None:
        return auth_error
    if not client_session_id or not client_session_id.strip():
        return JSONResponse({"detail": "client_session_id requerido."}, status_code=400)
    try:
        session_uuid = str(uuid.UUID(client_session_id.strip()))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse(
            {"detail": "El campo client_session_id debe ser un UUID."}, status_code=400
        )
    try:
        deleted = delete_breathing_session(web_context.DB_PATH, session_uuid)
    except Exception:
        logging.getLogger("mutations").exception("API respiracion DELETE fallida")
        return JSONResponse({"detail": "Error interno"}, status_code=500)
    return JSONResponse(
        {
            "schema_version": TRAINING_API_SCHEMA_VERSION,
            "client_session_id": session_uuid,
            "deleted": deleted,
        }
    )
