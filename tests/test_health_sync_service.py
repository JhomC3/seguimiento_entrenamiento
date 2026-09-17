"""Health Connect ingest service: idempotent mirror with per-operation acks."""

import sqlite3

import pytest

from src.database import init_db
from src.health_sync_service import ingest_health_records, parse_payload
from src.models import HealthSyncPayload, ValidationError


def _payload(operations: list[dict], device: str = "android-test") -> HealthSyncPayload:
    return parse_payload({"schema_version": 1, "device_id": device, "operations": operations})


def _upsert(hc_id: str, revision: int, record_type: str = "STEPS", count: int = 100) -> dict:
    return {
        "op": "UPSERT",
        "hc_id": hc_id,
        "record_type": record_type,
        "revision": revision,
        "start_epoch_ms": 1_000_000,
        "end_epoch_ms": 1_000_100,
        "data_origin_package": "com.samsung.health",
        "time_zone_offset_minutes": -300,
        "payload_schema_version": 1,
        "value": {"count": count},
    }


def _delete(hc_id: str, revision: int, record_type: str = "STEPS") -> dict:
    return {"op": "DELETE", "hc_id": hc_id, "record_type": record_type, "revision": revision}


def _row(db_path: str, hc_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT hc_id, record_type, value_json, last_modified_epoch_ms, deleted_at "
            "FROM health_records WHERE hc_id = ?",
            (hc_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hc_id": row[0],
            "record_type": row[1],
            "value_json": row[2],
            "revision": row[3],
            "deleted": row[4],
        }
    finally:
        conn.close()


def test_valid_batch_is_applied_and_acked(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    result = ingest_health_records(db, _payload([_upsert("a", 100), _upsert("b", 200)]))
    assert result.received == 2
    assert result.accepted_count == 2
    assert result.rejected == []
    assert _row(db, "a")["revision"] == 100
    assert _row(db, "b")["revision"] == 200


def test_heart_rate_5min_buckets_are_accepted_and_idempotent(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    bucket = {
        "op": "UPSERT",
        "hc_id": "HR5M:1786452000000",
        "record_type": "HEART_RATE_5MIN",
        "revision": 1786452000000,
        "start_epoch_ms": 1786452000000,
        "end_epoch_ms": 1786452300000,
        "payload_schema_version": 1,
        "value": {"avg": 72, "min": 60, "max": 95},
    }
    first = ingest_health_records(db, _payload([bucket]))
    assert first.accepted_count == 1
    row = _row(db, "HR5M:1786452000000")
    assert row["record_type"] == "HEART_RATE_5MIN"
    assert '"avg":72' in row["value_json"]

    # Replay del mismo tramo (re-agregación): idempotente, mismo hc_id.
    replay = ingest_health_records(db, _payload([bucket]))
    assert replay.accepted_count == 1
    assert replay.rejected == []
    assert _row(db, "HR5M:1786452000000")["revision"] == 1786452000000


def test_hourly_sums_are_accepted_and_idempotent(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    hour = {
        "op": "UPSERT",
        "hc_id": "STEPS_H1:1786452000000",
        "record_type": "STEPS_H1",
        "revision": 1786452000000,
        "start_epoch_ms": 1786452000000,
        "end_epoch_ms": 1786455600000,
        "payload_schema_version": 1,
        "value": {"count": 7000},
    }
    first = ingest_health_records(db, _payload([hour]))
    assert first.accepted_count == 1
    row = _row(db, "STEPS_H1:1786452000000")
    assert row["record_type"] == "STEPS_H1"
    assert '"count":7000' in row["value_json"]

    # Replay de la misma hora (re-agregación con solape): idempotente.
    replay = ingest_health_records(db, _payload([hour]))
    assert replay.accepted_count == 1
    assert replay.rejected == []


def test_hourly_calorie_and_distance_types_are_accepted(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ops = [
        _upsert("CALA_H1:1", 100, record_type="ACTIVE_CALORIES_H1", count=10),
        _upsert("CALT_H1:1", 100, record_type="TOTAL_CALORIES_H1", count=20),
        _upsert("DIST_H1:1", 100, record_type="DISTANCE_H1", count=30),
    ]
    result = ingest_health_records(db, _payload(ops))
    assert result.accepted_count == 3
    assert result.rejected == []


def test_replay_identical_is_acked_without_rewrite(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    payload = _payload([_upsert("a", 100, count=100)])
    ingest_health_records(db, payload)
    first_updated = (
        sqlite3.connect(db)
        .execute("SELECT updated_at FROM health_records WHERE hc_id = 'a'")
        .fetchone()[0]
    )
    result = ingest_health_records(db, payload)
    assert result.accepted_count == 1
    second_updated = (
        sqlite3.connect(db)
        .execute("SELECT updated_at FROM health_records WHERE hc_id = 'a'")
        .fetchone()[0]
    )
    assert first_updated == second_updated


def test_higher_revision_updates_value(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ingest_health_records(db, _payload([_upsert("a", 100, count=100)]))
    ingest_health_records(db, _payload([_upsert("a", 200, count=900)]))
    row = _row(db, "a")
    assert row["revision"] == 200
    assert '"count":900' in row["value_json"]


def test_stale_revision_is_rejected_without_touching_db(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ingest_health_records(db, _payload([_upsert("a", 200, count=900)]))
    result = ingest_health_records(db, _payload([_upsert("a", 100, count=100)]))
    assert result.accepted_count == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].hc_id == "a"
    assert result.rejected[0].reason == "stale_revision"
    row = _row(db, "a")
    assert row["revision"] == 200


def test_delete_sets_deleted_at_and_is_idempotent(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ingest_health_records(db, _payload([_upsert("a", 100, count=100)]))
    result = ingest_health_records(db, _payload([_delete("a", 150)]))
    assert result.accepted_count == 1
    assert _row(db, "a")["deleted"] is not None
    result2 = ingest_health_records(db, _payload([_delete("a", 150)]))
    assert result2.accepted_count == 1


def test_delete_for_unknown_record_is_acked(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    result = ingest_health_records(db, _payload([_delete("ghost", 150)]))
    assert result.accepted_count == 1
    assert _row(db, "ghost") is None


def test_unknown_record_type_rejects_whole_batch(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    bad = _upsert("a", 100)
    bad["record_type"] = "ALIEN"
    with pytest.raises(ValidationError):
        ingest_health_records(db, _payload([bad, _upsert("b", 200)]))
    assert _row(db, "a") is None
    assert _row(db, "b") is None


def test_malformed_operation_rejects_whole_batch(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        ingest_health_records(db, _payload([_upsert("a", 100), {"op": "UPSERT", "hc_id": "x"}]))
    assert _row(db, "a") is None


def test_batch_over_limit_rejected(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ops = [_upsert(f"r{i}", i) for i in range(501)]
    with pytest.raises(ValidationError):
        ingest_health_records(db, _payload(ops))


def test_end_before_start_rejected(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    bad = _upsert("a", 100)
    bad["end_epoch_ms"] = 999
    with pytest.raises(ValidationError):
        ingest_health_records(db, _payload([bad]))


def test_schema_version_mismatch_rejected(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        parse_payload({"schema_version": 2, "device_id": "x", "operations": []})
