"""Health Connect ingest: validation, idempotent mirror and per-op acks.

Contract in docs/architecture/health-sync-contract.md. Structural or semantic
validation errors reject the WHOLE batch (400, atomic); policy-level decisions
per operation (stale revision) are acked in `rejected` with a reason.
"""

import json
from datetime import UTC, datetime

from src.db_connection import connect_db
from src.models import (
    HealthRecordInput,
    HealthSyncPayload,
    IngestResult,
    OperationAck,
    RejectedOperation,
    ValidationError,
)

SCHEMA_VERSION = 1
MAX_OPERATIONS = 500
MAX_BODY_BYTES = 1024 * 1024  # 1 MiB, per health-sync-contract.md §2

# Mirror of the Android catalog (RecordTypes.kt typeName values).
ALLOWED_RECORD_TYPES = frozenset(
    {
        "STEPS",
        "HEART_RATE",
        "SLEEP_SESSION",
        "EXERCISE_SESSION",
        "ACTIVE_CALORIES_BURNED",
        "TOTAL_CALORIES_BURNED",
        "RESTING_HEART_RATE",
        "WEIGHT",
        "HEIGHT",
        "BODY_FAT",
        "BONE_MASS",
        "BODY_WATER_MASS",
        "LEAN_BODY_MASS",
        "DISTANCE",
        "ELEVATION_GAINED",
        "SPEED",
        "STEPS_CADENCE",
        "CYCLING_PEDALING_CADENCE",
        "POWER",
        "FLOORS_CLIMBED",
        "WHEELCHAIR_PUSHES",
        "VO2_MAX",
        "HEART_RATE_VARIABILITY_RMSSD",
        "OXYGEN_SATURATION",
        "RESPIRATORY_RATE",
        "SKIN_TEMPERATURE",
        "BODY_TEMPERATURE",
        "BASAL_BODY_TEMPERATURE",
        "BASAL_METABOLIC_RATE",
        "HYDRATION",
        "NUTRITION",
        "BLOOD_PRESSURE",
        "BLOOD_GLUCOSE",
        "CERVICAL_MUCUS",
        "MENSTRUATION_FLOW",
        "MENSTRUATION_PERIOD",
        "INTERMENSTRUAL_BLEEDING",
        "OVULATION_TEST",
        "SEXUAL_ACTIVITY",
    }
)

ALLOWED_OPS = frozenset({"UPSERT", "DELETE"})


def parse_payload(raw: dict) -> HealthSyncPayload:
    """Strict structural validation; raises ValidationError for any issue."""
    if not isinstance(raw, dict):
        raise ValidationError("El cuerpo debe ser un objeto JSON")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"schema_version no soportado: {raw.get('schema_version')}")
    device_id = raw.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValidationError("device_id requerido")
    operations = raw.get("operations")
    if not isinstance(operations, list):
        raise ValidationError("operations debe ser una lista")
    if not operations:
        raise ValidationError("operations vacío")
    if len(operations) > MAX_OPERATIONS:
        raise ValidationError(f"Máximo {MAX_OPERATIONS} operaciones por lote")
    parsed = [_parse_operation(op, index) for index, op in enumerate(operations)]
    return HealthSyncPayload(schema_version=SCHEMA_VERSION, device_id=device_id, operations=parsed)


def _parse_operation(raw, index: int) -> HealthRecordInput:
    if not isinstance(raw, dict):
        raise ValidationError(f"Operación {index} no es un objeto")
    op = raw.get("op")
    if op not in ALLOWED_OPS:
        raise ValidationError(f"Operación {index}: op desconocido '{op}'")
    hc_id = raw.get("hc_id")
    if not isinstance(hc_id, str) or not hc_id.strip():
        raise ValidationError(f"Operación {index}: hc_id requerido")
    record_type = raw.get("record_type")
    if record_type not in ALLOWED_RECORD_TYPES:
        raise ValidationError(f"Operación {index}: record_type desconocido '{record_type}'")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValidationError(f"Operación {index}: revision entero >= 0 requerido")
    if op == "UPSERT":
        start = raw.get("start_epoch_ms")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValidationError(f"Operación {index}: start_epoch_ms entero >= 0 requerido")
        end = raw.get("end_epoch_ms")
        if end is not None:
            if not isinstance(end, int) or isinstance(end, bool):
                raise ValidationError(f"Operación {index}: end_epoch_ms debe ser entero")
            if end < start:
                raise ValidationError(f"Operación {index}: end_epoch_ms < start_epoch_ms")
        value = raw.get("value")
        if not isinstance(value, dict):
            raise ValidationError(f"Operación {index}: value (objeto) requerido en UPSERT")
    return HealthRecordInput(
        op=op,
        hc_id=hc_id,
        record_type=record_type,
        revision=revision,
        start_epoch_ms=raw.get("start_epoch_ms"),
        end_epoch_ms=raw.get("end_epoch_ms"),
        data_origin_package=raw.get("data_origin_package"),
        time_zone_offset_minutes=raw.get("time_zone_offset_minutes"),
        payload_schema_version=raw.get("payload_schema_version", 1),
        value=raw.get("value", {}),
    )


def ingest_health_records(db_path: str, payload: HealthSyncPayload) -> IngestResult:
    """Applies one batch atomically. Returns exact per-operation acks."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    accepted: list[OperationAck] = []
    rejected: list[RejectedOperation] = []
    conn = connect_db(db_path)
    try:
        with conn:
            for op in payload.operations:
                if op.op == "UPSERT":
                    _apply_upsert(conn, op, payload.device_id, now, accepted, rejected)
                else:
                    _apply_delete(conn, op, now, accepted, rejected)
    finally:
        conn.close()
    return IngestResult(received=len(payload.operations), accepted=accepted, rejected=rejected)


def _apply_upsert(conn, op: HealthRecordInput, device_id: str, now: str, accepted, rejected) -> None:
    cursor = conn.execute(
        """
        INSERT INTO health_records (
            hc_id, record_type, start_epoch_ms, end_epoch_ms,
            last_modified_epoch_ms, data_origin_package, payload_schema_version,
            value_json, device_id, received_at, updated_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(hc_id) DO UPDATE SET
            record_type = excluded.record_type,
            start_epoch_ms = excluded.start_epoch_ms,
            end_epoch_ms = excluded.end_epoch_ms,
            last_modified_epoch_ms = excluded.last_modified_epoch_ms,
            data_origin_package = excluded.data_origin_package,
            payload_schema_version = excluded.payload_schema_version,
            value_json = excluded.value_json,
            device_id = excluded.device_id,
            updated_at = excluded.updated_at,
            deleted_at = NULL
        WHERE excluded.last_modified_epoch_ms > health_records.last_modified_epoch_ms
           OR health_records.deleted_at IS NOT NULL
        """,
        (
            op.hc_id,
            op.record_type,
            op.start_epoch_ms,
            op.end_epoch_ms,
            op.revision,
            op.data_origin_package,
            op.payload_schema_version,
            json.dumps(op.value, separators=(",", ":")),
            device_id,
            now,
            now,
        ),
    )
    if cursor.rowcount == 1 or _is_up_to_date(conn, op):
        accepted.append(OperationAck(hc_id=op.hc_id, revision=op.revision))
    else:
        rejected.append(
            RejectedOperation(hc_id=op.hc_id, revision=op.revision, reason="stale_revision")
        )


def _apply_delete(conn, op: HealthRecordInput, now: str, accepted, rejected) -> None:
    cursor = conn.execute(
        """
        UPDATE health_records SET deleted_at = ?, updated_at = ?
        WHERE hc_id = ? AND (deleted_at IS NOT NULL OR last_modified_epoch_ms < ?)
        """,
        (now, now, op.hc_id, op.revision),
    )
    if cursor.rowcount == 1 or _row_exists(conn, op.hc_id) is None:
        accepted.append(OperationAck(hc_id=op.hc_id, revision=op.revision))
    else:
        rejected.append(
            RejectedOperation(hc_id=op.hc_id, revision=op.revision, reason="stale_revision")
        )


def _is_up_to_date(conn, op: HealthRecordInput) -> bool:
    row = conn.execute(
        "SELECT last_modified_epoch_ms FROM health_records WHERE hc_id = ?", (op.hc_id,)
    ).fetchone()
    return row is not None and row[0] == op.revision


def _row_exists(conn, hc_id: str) -> tuple | None:
    return conn.execute("SELECT 1 FROM health_records WHERE hc_id = ?", (hc_id,)).fetchone()
