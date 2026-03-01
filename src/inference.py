"""ClickHouse inference: create anomalous_events view using catboostEvaluate."""

from clickhouse_driver import Client

from src.config import (
    SERVICE_LOGS_TABLE,
    ANOMALOUS_EVENTS_VIEW,
    FEATURE_COLUMNS,
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


def ensure_anomalous_events_view(client: Client, model_path: str) -> None:
    """Create or replace anomalous_events view that scores rows via catboostEvaluate."""
    ddl = get_anomalous_events_view_ddl(model_path).strip()
    # clickhouse_driver: pass model_path as a string (will be escaped)
    client.execute(ddl.replace("%(model_path)s", "'" + model_path.replace("'", "''") + "'"))


def view_exists(client: Client, view_name: str = ANOMALOUS_EVENTS_VIEW) -> bool:
    """Return True if view exists in default database."""
    result = client.execute(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name = %(name)s",
        {"name": view_name},
    )
    return result[0][0] > 0
