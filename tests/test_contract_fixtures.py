"""Cross-check: the exact contract fixtures (health-sync-contract.md §6) that
Android serializes (HealthSyncClientTest covers the Android side of the shape)
must round-trip through the Python ingest service."""

import json
import sqlite3
from pathlib import Path

from src.database import init_db
from src.health_sync_service import ingest_health_records, parse_payload

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "health_sync_contract.json").read_text()
)


def _applied(db_path: str, hc_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT value_json, last_modified_epoch_ms, deleted_at "
            "FROM health_records WHERE hc_id = ?",
            (hc_id,),
        ).fetchone()
        return {"value_json": row[0], "revision": row[1], "deleted": row[2]} if row else None
    finally:
        conn.close()


def test_contract_upsert_is_accepted(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    result = ingest_health_records(db, parse_payload(FIXTURES["fixture_upsert"]))
    assert result.accepted_count == 1
    row = _applied(db, "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c")
    assert row["revision"] == 1754678400000
    assert '"count":8123' in row["value_json"]


def test_contract_update_with_higher_revision_applies(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ingest_health_records(db, parse_payload(FIXTURES["fixture_upsert"]))
    result = ingest_health_records(db, parse_payload(FIXTURES["fixture_update"]))
    assert result.accepted_count == 1
    row = _applied(db, "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c")
    assert '"count":9123' in row["value_json"]


def test_contract_replay_does_not_duplicate(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    payload = parse_payload(FIXTURES["fixture_upsert"])
    ingest_health_records(db, payload)
    result = ingest_health_records(db, payload)
    assert result.accepted_count == 1
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0]
    conn.close()
    assert count == 1


def test_contract_delete_applies_and_hides_record(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    ingest_health_records(db, parse_payload(FIXTURES["fixture_upsert"]))
    delete = json.loads(json.dumps(FIXTURES["fixture_delete"]))
    delete["operations"][0]["hc_id"] = "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c"
    delete["operations"][0]["revision"] = 1754679000000
    result = ingest_health_records(db, parse_payload(delete))
    assert result.accepted_count == 1
    row = _applied(db, "6e3b2f1a-9c4d-4b8e-8f1a-2d5c7e9a0b1c")
    assert row["deleted"] is not None


def test_contract_delete_unknown_record_is_idempotent(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    result = ingest_health_records(db, parse_payload(FIXTURES["fixture_delete"]))
    assert result.accepted_count == 1  # no-op acked, no row created
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0]
    conn.close()
    assert count == 0
