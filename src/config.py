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

# v2 schema: primary table for upgrade; v1 (service_logs) kept for revert.
SERVICE_LOGS_V2_TABLE = "service_logs_v2"

# Schema contract v1: (name, type) for validation.
SERVICE_LOGS_COLUMNS = [
    ("timestamp", "DateTime64(3)"),
    ("service_id", "String"),
    ("endpoint", "String"),
    ("status_code", "UInt16"),
    ("response_time_ms", "UInt32"),
    ("user_agent", "String"),
    ("is_anomaly", "UInt8"),
]

# Schema contract v2: adds hour_of_day, is_weekend, throughput_velocity, error_acceleration, is_surge, log_signature, log_payload.
SERVICE_LOGS_V2_COLUMNS = [
    ("timestamp", "DateTime64(3)"),
    ("service_id", "String"),
    ("endpoint", "String"),
    ("status_code", "UInt16"),
    ("response_time_ms", "UInt32"),
    ("user_agent", "String"),
    ("hour_of_day", "UInt8"),
    ("is_weekend", "UInt8"),
    ("throughput_velocity", "Float64"),
    ("error_acceleration", "Float64"),
    ("is_surge", "UInt8"),
    ("log_signature", "String"),
    ("log_payload", "String"),
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

SERVICE_LOGS_V2_DDL = f"""
CREATE TABLE IF NOT EXISTS {SERVICE_LOGS_V2_TABLE} (
    timestamp DateTime64(3),
    service_id String,
    endpoint String,
    status_code UInt16,
    response_time_ms UInt32,
    user_agent String,
    hour_of_day UInt8,
    is_weekend UInt8,
    throughput_velocity Float64,
    error_acceleration Float64,
    is_surge UInt8,
    log_signature String,
    log_payload String,
    is_anomaly UInt8
) ENGINE = MergeTree()
ORDER BY (timestamp, service_id)
"""

# Feature store: 1-minute aggregates for velocity/acceleration (U2)
LOG_FEATURES_1M_TABLE = "log_features_1m"
LOG_FEATURES_MV = "log_features_mv"

LOG_FEATURES_1M_DDL = f"""
CREATE TABLE IF NOT EXISTS {LOG_FEATURES_1M_TABLE} (
    service_id String,
    window_start DateTime,
    hour_of_day UInt8,
    total_reqs AggregateFunction(count),
    error_reqs AggregateFunction(countIf, UInt8)
) ENGINE = AggregatingMergeTree()
ORDER BY (service_id, window_start)
TTL window_start + INTERVAL 14 DAY
"""

LOG_FEATURES_MV_DDL = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {LOG_FEATURES_MV}
TO {LOG_FEATURES_1M_TABLE}
AS SELECT
    service_id,
    toStartOfMinute(timestamp) AS window_start,
    toHour(timestamp) AS hour_of_day,
    countState() AS total_reqs,
    countIfState(status_code >= 500) AS error_reqs
FROM {SERVICE_LOGS_V2_TABLE}
GROUP BY service_id, window_start, hour_of_day
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

# v2: contextual + log_signature (no text: ClickHouse catboostEvaluate does not support text features)
# Order: numeric first, then categorical. Same 8 features used in training and in anomalous_events_v2 view.
FEATURE_COLUMNS_V2 = [
    "status_code",
    "response_time_ms",
    "throughput_velocity",
    "error_acceleration",
    "hour_of_day",
    "service_id",
    "endpoint",
    "log_signature",
]
CAT_FEATURES_V2 = ["service_id", "endpoint", "log_signature"]
# Not used in training; log_payload remains in schema for analytics; ClickHouse view omits it from catboostEvaluate
TEXT_FEATURES_V2: list[str] = []
MODEL_PATH_V2 = "catboost_model_v2.bin"

# Path to model as seen by ClickHouse inside Docker (mount project root as /workspace)
MODEL_PATH_IN_CONTAINER = "/workspace/catboost_model.bin"
MODEL_PATH_V2_IN_CONTAINER = "/workspace/catboost_model_v2.bin"
ANOMALOUS_EVENTS_VIEW = "anomalous_events"
ANOMALOUS_EVENTS_VIEW_V2 = "anomalous_events_v2"
