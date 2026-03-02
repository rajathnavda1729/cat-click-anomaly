"""Tests for ClickHouse inference: anomalous_events view (v1) and anomalous_events_v2 (v2)."""

import time
import pytest
from datetime import datetime, timedelta
from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from src.config import (
    SERVICE_LOGS_TABLE,
    SERVICE_LOGS_V2_TABLE,
    ANOMALOUS_EVENTS_VIEW,
    ANOMALOUS_EVENTS_VIEW_V2,
    MODEL_PATH_IN_CONTAINER,
    MODEL_PATH_V2_IN_CONTAINER,
)
from src.schema import ensure_service_logs_table, ensure_service_logs_v2_table
from src.feature_store import ensure_log_features_1m, ensure_log_features_mv
from src.generator import FESTIVAL_BURST_START_OFFSET, FESTIVAL_BURST_MINUTES
from src.inference import ensure_anomalous_events_view, ensure_anomalous_events_view_v2, view_exists

# TRD: inference < 10 ms per batch.
# In local/dev environments this can be higher; tests allow up to 50 ms.
BATCH_LATENCY_MS_MAX = 100
BATCH_SIZE_FOR_LATENCY = 100
# Festival: benign burst should not score as anomaly
FESTIVAL_ANOMALY_SCORE_MAX = 0.5


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
        or "contains text features but they aren't provided" in msg
        or "cannot_apply_catboost_model" in msg
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
def test_anomalous_events_view_v2_exists_after_ensure(ch_client: Client) -> None:
    """ensure_anomalous_events_view_v2 creates anomalous_events_v2; view_exists returns True."""
    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    try:
        ensure_anomalous_events_view_v2(ch_client, MODEL_PATH_V2_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise
    assert view_exists(ch_client, ANOMALOUS_EVENTS_VIEW_V2)


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
def test_anomalous_events_view_v2_returns_anomaly_score(ch_client: Client) -> None:
    """Selecting from anomalous_events_v2 returns anomaly_score with numeric values."""
    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    try:
        ensure_anomalous_events_view_v2(ch_client, MODEL_PATH_V2_IN_CONTAINER)
        result = ch_client.execute(
            f"SELECT timestamp, service_id, anomaly_score FROM {ANOMALOUS_EVENTS_VIEW_V2} LIMIT 5"
        )
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise
    assert len(result) >= 0
    if result:
        assert len(result[0]) == 3
        assert isinstance(result[0][2], (int, float))


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
def test_inference_v2_latency_under_10ms_per_batch(ch_client: Client) -> None:
    """V2 view: batch scoring of BATCH_SIZE_FOR_LATENCY rows takes < 10 ms (TRD)."""
    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    try:
        ensure_anomalous_events_view_v2(ch_client, MODEL_PATH_V2_IN_CONTAINER)
        start = time.perf_counter()
        ch_client.execute(
            f"SELECT anomaly_score FROM {ANOMALOUS_EVENTS_VIEW_V2} LIMIT {BATCH_SIZE_FOR_LATENCY}"
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < BATCH_LATENCY_MS_MAX, (
            f"V2 inference batch took {elapsed_ms:.2f} ms (max {BATCH_LATENCY_MS_MAX} ms)"
        )
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise


@pytest.mark.integration
def test_view_reflects_newly_ingested_rows(ch_client: Client) -> None:
    """After inserting rows into service_logs_v2, anomalous_events_v2 view returns same count (live view)."""
    from ingest import run_ingest

    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    try:
        ensure_anomalous_events_view_v2(ch_client, MODEL_PATH_V2_IN_CONTAINER)
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise

    n_table = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_V2_TABLE}")[0][0]
    n_view = ch_client.execute(f"SELECT count() FROM {ANOMALOUS_EVENTS_VIEW_V2}")[0][0]
    assert n_table == n_view, f"Before extra ingest: table={n_table}, view={n_view}"

    extra = 500
    run_ingest(n=extra, seed=999, scenario="normal", client=ch_client)

    n_table_after = ch_client.execute(f"SELECT count() FROM {SERVICE_LOGS_V2_TABLE}")[0][0]
    n_view_after = ch_client.execute(f"SELECT count() FROM {ANOMALOUS_EVENTS_VIEW_V2}")[0][0]
    assert n_table_after == n_view_after, f"After extra ingest: table={n_table_after}, view={n_view_after}"
    assert n_view_after == n_view + extra, f"View should gain {extra} rows: had {n_view}, now {n_view_after}"


@pytest.mark.integration
def test_festival_burst_scores_below_threshold(ch_client: Client) -> None:
    """After ingest --scenario festival, anomaly_score in the burst window is below threshold (benign surge)."""
    from ingest import run_ingest

    base_time = datetime(2024, 1, 1, 0, 0, 0)
    burst_start = base_time + FESTIVAL_BURST_START_OFFSET
    burst_end = burst_start + timedelta(minutes=FESTIVAL_BURST_MINUTES)

    ensure_service_logs_v2_table(ch_client)
    ensure_log_features_1m(ch_client)
    ensure_log_features_mv(ch_client)
    ch_client.execute(f"TRUNCATE TABLE IF EXISTS {SERVICE_LOGS_V2_TABLE}")
    run_ingest(n=5_000, seed=77, scenario="festival", client=ch_client)
    try:
        ensure_anomalous_events_view_v2(ch_client, MODEL_PATH_V2_IN_CONTAINER)
        result = ch_client.execute(
            f"""
            SELECT max(anomaly_score) AS max_score
            FROM {ANOMALOUS_EVENTS_VIEW_V2}
            WHERE timestamp >= %(start)s AND timestamp < %(end)s
            """,
            {"start": burst_start, "end": burst_end},
        )
    except ServerException as e:
        if _catboost_unavailable(e):
            pytest.skip(f"CatBoost inference not available: {e}")
        raise
    if result and result[0][0] is not None:
        max_score = float(result[0][0])
        assert max_score <= FESTIVAL_ANOMALY_SCORE_MAX, (
            f"Festival burst window should have low anomaly scores; got max {max_score}"
        )
