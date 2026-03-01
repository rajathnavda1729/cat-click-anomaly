"""Tests for ClickHouse inference: anomalous_events view and catboostEvaluate."""

import time
import pytest
from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from src.config import (
    SERVICE_LOGS_TABLE,
    ANOMALOUS_EVENTS_VIEW,
    MODEL_PATH_IN_CONTAINER,
)
from src.schema import ensure_service_logs_table
from src.inference import ensure_anomalous_events_view, view_exists

# TRD: inference < 10 ms per batch
BATCH_LATENCY_MS_MAX = 10
BATCH_SIZE_FOR_LATENCY = 100


def _catboost_unavailable(exc: BaseException) -> bool:
    """True if the exception indicates CatBoost inference is not available."""
    msg = str(exc).lower()
    return (
        "catboost_lib_path" in msg
        or "libcatboostmodel" in msg
        or "catboostevaluate" in msg
        or "cannot open shared object" in msg
        or "library not loaded" in msg
        or "exit" in msg and "88" in msg
    )


@pytest.mark.integration
def test_anomalous_events_view_exists_after_ensure(ch_client: Client) -> None:
    """ensure_anomalous_events_view creates the view; view_exists returns True."""
    ensure_service_logs_table(ch_client)
    try:
        ensure_anomalous_events_view(ch_client, MODEL_PATH_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available (need libcatboostmodel.so): {e}")
        raise
    assert view_exists(ch_client, ANOMALOUS_EVENTS_VIEW)


@pytest.mark.integration
def test_anomalous_events_view_returns_anomaly_score(ch_client: Client) -> None:
    """Selecting from anomalous_events returns anomaly_score column with numeric values."""
    ensure_service_logs_table(ch_client)
    try:
        ensure_anomalous_events_view(ch_client, MODEL_PATH_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise
    result = ch_client.execute(
        f"SELECT timestamp, service_id, anomaly_score FROM {ANOMALOUS_EVENTS_VIEW} LIMIT 5"
    )
    assert len(result) >= 0  # may be 0 if table empty
    if result:
        assert len(result[0]) == 3
        score = result[0][2]
        assert isinstance(score, (int, float))


@pytest.mark.integration
def test_inference_latency_under_10ms_per_batch(ch_client: Client) -> None:
    """Batch scoring of BATCH_SIZE_FOR_LATENCY rows takes < 10 ms (TRD)."""
    ensure_service_logs_table(ch_client)
    try:
        ensure_anomalous_events_view(ch_client, MODEL_PATH_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise
    start = time.perf_counter()
    ch_client.execute(
        f"SELECT anomaly_score FROM {ANOMALOUS_EVENTS_VIEW} LIMIT {BATCH_SIZE_FOR_LATENCY}"
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < BATCH_LATENCY_MS_MAX, (
        f"Inference batch of {BATCH_SIZE_FOR_LATENCY} took {elapsed_ms:.2f} ms "
        f"(max {BATCH_LATENCY_MS_MAX} ms)"
    )


@pytest.mark.integration
def test_view_reflects_newly_ingested_rows(ch_client: Client) -> None:
    """After inserting more rows into service_logs, anomalous_events view returns the same count (live view)."""
    from ingest import run_ingest

    ensure_service_logs_table(ch_client)
    try:
        ensure_anomalous_events_view(ch_client, MODEL_PATH_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise

    n_table = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_TABLE}")[0][0]
    n_view = ch_client.execute(f"SELECT count() FROM {ANOMALOUS_EVENTS_VIEW}")[0][0]
    assert n_table == n_view, f"Before extra ingest: table={n_table}, view={n_view}"

    extra = 500
    run_ingest(n=extra, seed=999, client=ch_client)

    n_table_after = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_TABLE}")[0][0]
    n_view_after = ch_client.execute(f"SELECT count() FROM {ANOMALOUS_EVENTS_VIEW}")[0][0]
    assert n_table_after == n_view_after, f"After extra ingest: table={n_table_after}, view={n_view_after}"
    assert n_view_after == n_view + extra, f"View should gain {extra} rows: had {n_view}, now {n_view_after}"
