"""ClickHouse inference: create anomalous_events view using catboostEvaluate (v1 and v2)."""

from clickhouse_driver import Client

from src.config import (
    SERVICE_LOGS_TABLE,
    SERVICE_LOGS_V2_TABLE,
    LOG_FEATURES_1M_TABLE,
    ANOMALOUS_EVENTS_VIEW,
    ANOMALOUS_EVENTS_VIEW_V2,
    FEATURE_COLUMNS,
    FEATURE_COLUMNS_V2,
)


def get_anomalous_events_view_ddl(model_path: str) -> str:
    """Return CREATE VIEW SQL for anomalous_events with catboostEvaluate.
    Feature order must match FEATURE_COLUMNS: numeric first (status_code, response_time_ms),
    then categorical (service_id, endpoint, user_agent), as required by the C evaluation library.
    """
    features = ", ".join(FEATURE_COLUMNS)
    return f"""
CREATE OR REPLACE VIEW {ANOMALOUS_EVENTS_VIEW} AS
SELECT
    timestamp,
    service_id,
    endpoint,
    status_code,
    response_time_ms,
    user_agent,
    is_anomaly,
    catboostEvaluate(%(model_path)s, {features}) AS anomaly_score
FROM {SERVICE_LOGS_TABLE}
"""


def get_anomalous_events_view_v2_ddl(model_path: str) -> str:
    """Return CREATE VIEW SQL for anomalous_events_v2: join service_logs_v2 with log_features_1m
    bucketed aggregates (throughput_velocity, error_acceleration, is_surge), then catboostEvaluate
    with v2 feature order. ClickHouse catboostEvaluate does not support text features; pass only
    numeric + categorical (omit log_payload). Order: status_code, response_time_ms, throughput_velocity,
    error_acceleration, hour_of_day, service_id, endpoint, log_signature.
    """
    # CTE: merged 1m aggregates per (service_id, window_start)
    # Then window functions for velocity (10 buckets), error_acceleration (lag 10), is_surge (z-score 60)
    # catboostEvaluate: 8 features (no log_payload - not supported in ClickHouse)
    return f"""
CREATE OR REPLACE VIEW {ANOMALOUS_EVENTS_VIEW_V2} AS
WITH
merged AS (
    SELECT
        service_id,
        window_start,
        countMerge(total_reqs) AS total_reqs,
        countIfMerge(error_reqs) AS error_reqs
    FROM {LOG_FEATURES_1M_TABLE}
    GROUP BY service_id, window_start
),
with_rates AS (
    SELECT
        service_id,
        window_start,
        total_reqs,
        error_reqs / nullIf(total_reqs, 0) AS error_rate
    FROM merged
),
with_velocity AS (
    SELECT
        service_id,
        window_start,
        total_reqs / nullIf(avg(total_reqs) OVER (PARTITION BY service_id ORDER BY window_start ROWS BETWEEN 9 PRECEDING AND CURRENT ROW), 0) AS throughput_velocity,
        error_rate / nullIf(lagInFrame(error_rate, 10) OVER (PARTITION BY service_id ORDER BY window_start), 0) AS error_acceleration,
        if((total_reqs - avg(total_reqs) OVER (PARTITION BY service_id ORDER BY window_start ROWS BETWEEN 60 PRECEDING AND CURRENT ROW)) / nullIf(stddevPop(total_reqs) OVER (PARTITION BY service_id ORDER BY window_start ROWS BETWEEN 60 PRECEDING AND CURRENT ROW), 0) > 3, 1, 0) AS is_surge
    FROM with_rates
)
SELECT
    l.timestamp,
    l.service_id,
    l.endpoint,
    l.status_code,
    l.response_time_ms,
    l.hour_of_day,
    coalesce(b.throughput_velocity, 1) AS throughput_velocity,
    coalesce(b.error_acceleration, 0) AS error_acceleration,
    coalesce(b.is_surge, 0) AS is_surge,
    l.log_signature,
    l.log_payload,
    l.is_anomaly,
    catboostEvaluate(%(model_path)s, l.status_code, l.response_time_ms, coalesce(b.throughput_velocity, 1), coalesce(b.error_acceleration, 0), l.hour_of_day, l.service_id, l.endpoint, l.log_signature) AS anomaly_score
FROM {SERVICE_LOGS_V2_TABLE} AS l
LEFT JOIN with_velocity AS b ON l.service_id = b.service_id AND toStartOfMinute(l.timestamp) = b.window_start
"""


def ensure_anomalous_events_view(client: Client, model_path: str) -> None:
    """Create or replace anomalous_events view that scores rows via catboostEvaluate (v1)."""
    ddl = get_anomalous_events_view_ddl(model_path).strip()
    client.execute(ddl.replace("%(model_path)s", "'" + model_path.replace("'", "''") + "'"))


def ensure_anomalous_events_view_v2(client: Client, model_path: str) -> None:
    """Create or replace anomalous_events_v2 view: join v2 logs with log_features_1m aggregates, then catboostEvaluate with v2 model."""
    ddl = get_anomalous_events_view_v2_ddl(model_path).strip()
    client.execute(ddl.replace("%(model_path)s", "'" + model_path.replace("'", "''") + "'"))


def view_exists(client: Client, view_name: str = ANOMALOUS_EVENTS_VIEW) -> bool:
    """Return True if view exists in default database."""
    result = client.execute(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name = %(name)s",
        {"name": view_name},
    )
    return result[0][0] > 0
