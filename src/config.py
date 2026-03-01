"""Connection and schema constants for ClickHouse (single source of truth)."""

import os
from typing import Any

# Connection (env with defaults for local Docker)
CLICKHOUSE_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.environ.get("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_HTTP_PORT = int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123"))
# Optional: set CLICKHOUSE_PASSWORD in CI or when server requires auth (e.g. "")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD")

# Table and schema (must match training and inference)
SERVICE_LOGS_TABLE = "service_logs"

# Schema contract: (name, type) for validation. Type strings match ClickHouse system.columns.
SERVICE_LOGS_COLUMNS = [
    ("timestamp", "DateTime64(3)"),
    ("service_id", "String"),
    ("endpoint", "String"),
    ("status_code", "UInt16"),
    ("response_time_ms", "UInt32"),
    ("user_agent", "String"),
    ("is_anomaly", "UInt8"),
]

SERVICE_LOGS_DDL = f"""
CREATE TABLE IF NOT EXISTS {SERVICE_LOGS_TABLE} (
    timestamp DateTime64(3),
    service_id String,
    endpoint String,
    status_code UInt16,
    response_time_ms UInt32,
    user_agent String,
    is_anomaly UInt8
) ENGINE = MergeTree()
ORDER BY (timestamp, service_id)
"""


def get_clickhouse_connection_params() -> dict[str, Any]:
    """Return kwargs for clickhouse_driver.Client."""
    params: dict[str, Any] = {"host": CLICKHOUSE_HOST, "port": CLICKHOUSE_PORT}
    if CLICKHOUSE_PASSWORD is not None:
        params["password"] = CLICKHOUSE_PASSWORD
    return params


# --- Training / inference contract (column order must match CatBoost and ClickHouse modelEvaluate) ---
# For catboostEvaluate in ClickHouse: C library expects NUMERIC columns first, then CATEGORICAL.
# So we use this order everywhere (training, inference, view DDL).
FEATURE_COLUMNS = ["status_code", "response_time_ms", "service_id", "endpoint", "user_agent"]
CAT_FEATURES = ["service_id", "endpoint", "user_agent"]
TARGET = "is_anomaly"
MODEL_PATH = "catboost_model.bin"

# Path to model as seen by ClickHouse inside Docker (mount project root as /workspace)
MODEL_PATH_IN_CONTAINER = "/workspace/catboost_model.bin"
ANOMALOUS_EVENTS_VIEW = "anomalous_events"
