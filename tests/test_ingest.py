"""Integration tests for ingest: row count and anomaly stats after run_ingest (v2)."""

import pytest
from clickhouse_driver import Client

from src.config import SERVICE_LOGS_V2_TABLE
from src.schema import ensure_service_logs_v2_table
from ingest import run_ingest


@pytest.mark.integration
def test_ingest_inserts_expected_row_count(ch_client: Client) -> None:
    """After run_ingest(n=1000, scenario='normal'), table has 1000 rows."""
    ensure_service_logs_v2_table(ch_client)
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {SERVICE_LOGS_V2_TABLE}")
    inserted = run_ingest(n=1_000, seed=99, scenario="normal", client=ch_client)
    assert inserted == 1_000
    (count,) = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_V2_TABLE}")[0]
    assert count == 1_000


@pytest.mark.integration
def test_ingest_anomaly_ratio_in_stored_data(ch_client: Client) -> None:
    """After ingest, is_anomaly ratio in DB is roughly 18–22%."""
    ensure_service_logs_v2_table(ch_client)
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {SERVICE_LOGS_V2_TABLE}")
    run_ingest(n=5_000, seed=123, scenario="normal", client=ch_client)
    result = ch_client.execute(
        f"SELECT countIf(is_anomaly = 1) AS anomalies, count() AS total FROM {SERVICE_LOGS_V2_TABLE}"
    )
    anomalies, total = result[0]
    ratio = anomalies / total
    assert 0.18 <= ratio <= 0.22, f"Expected ~0.20, got {ratio}"


@pytest.mark.integration
def test_ingest_scenario_festival_inserts_extra_rows_in_burst(ch_client: Client) -> None:
    """run_ingest with scenario=festival inserts at least n rows (extra rows in 5-min burst window)."""
    ensure_service_logs_v2_table(ch_client)
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {SERVICE_LOGS_V2_TABLE}")
    inserted = run_ingest(n=2_000, seed=77, scenario="festival", client=ch_client)
    assert inserted >= 2_000
    (count,) = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_V2_TABLE}")[0]
    assert count == inserted
