"""v010 — health_connect: mirror of Health Connect records (raw snapshot).

Generic table per health-sync-contract.md: one row per Health Connect record,
identified by hc_id (PK). Values are stored as a versioned JSON snapshot; a
logical delete sets deleted_at. No FK (mirror of external data, same snapshot
pattern as diario_alimentacion).
"""

VERSION = 10
NAME = "health_connect"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS health_records (
    hc_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    start_epoch_ms INTEGER NOT NULL,
    end_epoch_ms INTEGER,
    last_modified_epoch_ms INTEGER NOT NULL,
    data_origin_package TEXT,
    payload_schema_version INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_records_type_start
    ON health_records(record_type, start_epoch_ms);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
