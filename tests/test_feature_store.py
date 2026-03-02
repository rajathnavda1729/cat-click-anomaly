"""Feature store tests: log_features_1m and log_features_mv; insert into service_logs_v2 and assert merged counts."""

from datetime import datetime

import pytest
from clickhouse_driver import Client

from src.config import (
    SERVICE_LOGS_V2_TABLE,
    LOG_FEATURES_1M_TABLE,
)
from src.schema import ensure_service_logs_v2_table
from src.feature_store import (
    ensure_log_features_1m,
    ensure_log_features_mv,
    feature_store_ready,
)


def _make_v2_row(
    ts: datetime,
    service_id: str = "svc-a",
    status_code: int = 200,
) -> tuple:
    """One row for service_logs_v2: (timestamp, service_id, endpoint, status_code, response_time_ms,
    user_agent, hour_of_day, is_weekend, throughput_velocity, error_acceleration, is_surge,
    log_signature, log_payload, is_anomaly)."""
    return (
        ts,
        service_id,
        "/api/health",
        status_code,
        50,
        "test-agent",
        ts.hour,
        1 if ts.weekday() >= 5 else 0,
        1.0,
        0.0,
        0,
        "[SVC]:[ACTION]:[OK]",
        "payload",
        0,
    )


@pytest.mark.integration
def test_feature_store_ready_after_ensure(ch_client: Client) -> None:
    """ensure_log_features_1m and ensure_log_features_mv create table and MV; feature_store_ready is True."""
    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    assert feature_store_ready(ch_client)


@pytest.mark.integration
def test_log_features_1m_counts_consistent_with_service_logs_v2(ch_client: Client) -> None:
    """Insert rows into service_logs_v2; query log_features_1m with countMerge/countIfMerge; assert consistency."""
    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)

    # Start from a clean slate so previous tests or manual runs don't affect aggregates.
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {SERVICE_LOGS_V2_TABLE}")
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {LOG_FEATURES_1M_TABLE}")

    # Use a fixed minute so all rows land in one bucket per service_id
    base_ts = datetime(2025, 3, 1, 12, 34, 0)
    rows = [
        _make_v2_row(base_ts, "svc-a", 200),
        _make_v2_row(base_ts, "svc-a", 200),
        _make_v2_row(base_ts, "svc-a", 503),
        _make_v2_row(base_ts, "svc-b", 200),
        _make_v2_row(base_ts, "svc-b", 500),
    ]
    ch_client.execute(f"INSERT INTO {SERVICE_LOGS_V2_TABLE} VALUES", rows)

    # Query merged aggregates: total requests and error requests per (service_id, window_start, hour_of_day)
    result = ch_client.execute(
        f"""
        SELECT
            service_id,
            window_start,
            hour_of_day,
            countMerge(total_reqs) AS total,
            countIfMerge(error_reqs) AS errors
        FROM {LOG_FEATURES_1M_TABLE}
        GROUP BY service_id, window_start, hour_of_day
        ORDER BY service_id
        """
    )

    total_reqs = sum(r[3] for r in result)
    total_errors = sum(r[4] for r in result)
    assert total_reqs == 5, "Expected 5 rows in log_features_1m aggregates"
    assert total_errors == 2, "Expected 2 error rows (503 and 500)"

    # Per-service check: svc-a has 3 total, 1 error; svc-b has 2 total, 1 error
    by_svc = {r[0]: (r[3], r[4]) for r in result}
    assert by_svc["svc-a"] == (3, 1)
    assert by_svc["svc-b"] == (2, 1)
