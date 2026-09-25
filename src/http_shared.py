"""Validadores, limites y errores HTTP compartidos (spec 009)."""

import hmac
import logging
import math
from datetime import date

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import HC_SYNC_TOKEN
from src.dashboard_service import translate_error
from src.models import ConflictError, NotFoundError, ValidationError
from src.response_fragments import notice_oob
from src.web_context import templates

MAX_FORM_SETS = 100
MAX_DIARY_ROWS = 100
MAX_REORDER_IDS = 500
MAX_NAME_LEN = 200
MAX_SPLIT_ITEMS = 300

GRANULARITY_VALUES = ("day", "week", "month")

TRAINING_API_SCHEMA_VERSION = 1


def _check_lote(rows: list, max_rows: int, campo: str) -> None:
    if len(rows) > max_rows:
        raise ValidationError(f"Demasiadas filas de {campo} (máx. {max_rows}).")


def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")


GRANULARITY_VALUES = ("day", "week", "month")


def _validate_granularity(gran: str) -> str:
    """Valida gran y devuelve el valor canónico. Default: 'day' (contrato B1)."""
    if gran not in GRANULARITY_VALUES:
        raise ValidationError(
            f"Granularidad inválida: {gran!r}. Valores permitidos: day, week, month."
        )
    return gran


def _validate_window(ventana: int) -> int:
    """Valida la ventana del panel: 1–8 semanas (contrato Fase 2)."""
    if ventana not in (1, 2, 3, 4, 5, 6, 7, 8):
        raise ValidationError(
            f"Ventana inválida: {ventana}. Valores permitidos: 1, 2, 3, 4, 5, 6, 7, 8."
        )
    return ventana


def _domain_error_response(
    request: Request, error: Exception, target: str, *, extra: str = ""
) -> HTMLResponse:
    message, status = translate_error(error)
    return HTMLResponse(
        content=notice_oob(
            templates, request, target=target, message=message, kind="notice-error", dismiss=4500
        )
        + extra,
        status_code=status,
    )


def _api_domain_error(exc: Exception, log: str) -> JSONResponse:
    """Mapea errores de dominio a su status (backend-standards §3)."""
    if isinstance(exc, NotFoundError):
        return JSONResponse({"detail": str(exc)}, status_code=404)
    if isinstance(exc, ConflictError):
        return JSONResponse({"detail": str(exc)}, status_code=409)
    if isinstance(exc, ValidationError):
        return JSONResponse({"detail": str(exc)}, status_code=400)
    logging.getLogger(log).exception("API fallida")
    return JSONResponse({"detail": "Error interno"}, status_code=500)


def _api_num(value) -> float | None:
    """Normaliza un valor de serie a número o None (preview de plantilla)."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _require_training_api_token(request: Request) -> JSONResponse | None:
    """Auth compartida de la API v1: mismo X-Sync-Token que Health Connect.

    Devuelve la respuesta de error (503/401) o None si el token es válido.
    Misma semántica que POST /sync/health-connect: sin token configurado el
    endpoint no existe (503, nunca puerta abierta); token ausente o distinto
    es 401 permanente. Decisión documentada en training-api-contract.md §1.
    """
    if not HC_SYNC_TOKEN:
        return JSONResponse({"detail": "Endpoint no configurado (HC_SYNC_TOKEN)"}, status_code=503)
    token = request.headers.get("X-Sync-Token", "")
    if not token or not hmac.compare_digest(token, HC_SYNC_TOKEN):
        return JSONResponse({"detail": "Token inválido"}, status_code=401)
    return None
