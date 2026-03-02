"""Tests for synthetic log generator: distribution, fields, ranges, categoricals, v2 scenarios."""

import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.generator import (
    V2_COLUMNS,
    generate_logs,
    LOG_SIGNATURE_SILENT_FAILURE,
    FESTIVAL_BURST_START_OFFSET,
    FESTIVAL_BURST_MINUTES,
    SILENT_FAILURE_WINDOW_OFFSET,
    SILENT_FAILURE_WINDOW_MINUTES,
)

# v2 columns (must match config SERVICE_LOGS_V2_COLUMNS)
REQUIRED_COLUMNS = list(V2_COLUMNS)
LOG_SIGNATURE_PATTERN = re.compile(r"^\[[^\]]+\]:\[[^\]]+\]:\[[^\]]+\]$")


def test_generator_returns_dataframe_with_required_columns() -> None:
    """Output has all required columns and no extras."""
    rng = np.random.default_rng(42)
    df = generate_logs(n=100, rng=rng)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == REQUIRED_COLUMNS


def test_generator_anomaly_ratio_about_20_percent() -> None:
    """With default params, is_anomaly fraction is roughly 18–22%."""
    rng = np.random.default_rng(123)
    df = generate_logs(n=10_000, rng=rng)
    ratio = df["is_anomaly"].mean()
    assert 0.18 <= ratio <= 0.22, f"Expected ~0.20, got {ratio}"


def test_generator_status_codes_in_valid_range() -> None:
    """status_code is 200 for normal, 2xx/5xx in valid HTTP range."""
    rng = np.random.default_rng(99)
    df = generate_logs(n=500, rng=rng)
    assert df["status_code"].min() >= 200
    assert df["status_code"].max() <= 599


def test_generator_response_time_positive() -> None:
    """response_time_ms is positive."""
    rng = np.random.default_rng(1)
    df = generate_logs(n=500, rng=rng)
    assert (df["response_time_ms"] >= 0).all()


def test_generator_categoricals_non_empty() -> None:
    """service_id, endpoint, user_agent are non-empty strings."""
    rng = np.random.default_rng(7)
    df = generate_logs(n=500, rng=rng)
    for col in ["service_id", "endpoint", "user_agent"]:
        # object, StringDtype, or str
        assert df[col].dtype == object or "str" in str(df[col].dtype).lower()
        assert (df[col].astype(str).str.len() > 0).all(), f"{col} has empty values"


def test_generator_is_anomaly_binary() -> None:
    """is_anomaly is 0 or 1."""
    rng = np.random.default_rng(5)
    df = generate_logs(n=1000, rng=rng)
    assert set(df["is_anomaly"].unique()).issubset({0, 1})


def test_generator_deterministic_with_same_seed() -> None:
    """Same seed produces same rows (deterministic)."""
    rng1 = np.random.default_rng(42)
    df1 = generate_logs(n=100, rng=rng1)
    rng2 = np.random.default_rng(42)
    df2 = generate_logs(n=100, rng=rng2)
    pd.testing.assert_frame_equal(df1, df2)


def test_generator_deterministic_with_same_seed_festival() -> None:
    """Same seed and scenario=festival produces same rows."""
    rng1 = np.random.default_rng(99)
    df1 = generate_logs(n=500, rng=rng1, scenario="festival")
    rng2 = np.random.default_rng(99)
    df2 = generate_logs(n=500, rng=rng2, scenario="festival")
    pd.testing.assert_frame_equal(df1, df2)


def test_generator_timestamps_ordered() -> None:
    """timestamp column is present and sortable (datetime-like)."""
    rng = np.random.default_rng(3)
    df = generate_logs(n=100, rng=rng)
    assert df["timestamp"].isna().sum() == 0
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])


def test_generator_v2_hour_of_day_in_range() -> None:
    """hour_of_day is 0–23."""
    rng = np.random.default_rng(11)
    df = generate_logs(n=500, rng=rng)
    assert (df["hour_of_day"] >= 0).all() and (df["hour_of_day"] <= 23).all()


def test_generator_v2_is_surge_binary() -> None:
    """is_surge is 0 or 1."""
    rng = np.random.default_rng(13)
    df = generate_logs(n=500, rng=rng)
    assert set(df["is_surge"].unique()).issubset({0, 1})


def test_generator_v2_log_signature_matches_pattern() -> None:
    """log_signature matches [X]:[Y]:[Z] pattern."""
    rng = np.random.default_rng(17)
    df = generate_logs(n=500, rng=rng)
    for sig in df["log_signature"].unique():
        assert LOG_SIGNATURE_PATTERN.match(sig), f"log_signature {sig!r} does not match pattern"


def test_generator_scenario_festival_10x_in_burst_window() -> None:
    """Scenario festival: normal rows in the 5-min burst are 10× (only normal rows are duplicated)."""
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    burst_start = base_time + FESTIVAL_BURST_START_OFFSET
    burst_end = burst_start + timedelta(minutes=FESTIVAL_BURST_MINUTES)
    rng = np.random.default_rng(77)
    n = 10_000
    df = generate_logs(n=n, rng=rng, base_time=base_time, scenario="festival")
    assert len(df) >= n
    in_burst = (df["timestamp"] >= burst_start) & (df["timestamp"] < burst_end)
    count_in_burst = in_burst.sum()
    # Generator duplicates only normal (is_anomaly=0) rows in burst; compare to normal-scenario normal rows in burst
    rng_normal = np.random.default_rng(77)
    df_normal = generate_logs(n=n, rng=rng_normal, base_time=base_time, scenario="normal")
    normal_rows_in_burst = (
        (df_normal["timestamp"] >= burst_start)
        & (df_normal["timestamp"] < burst_end)
        & (df_normal["is_anomaly"] == 0)
    ).sum()
    if normal_rows_in_burst > 0:
        assert count_in_burst >= 10 * normal_rows_in_burst, (
            f"Festival burst should have ≥10× normal rows in burst: got {count_in_burst}, normal_rows_in_burst {normal_rows_in_burst}"
        )
    # In festival scenario, the burst window is pure normal traffic.
    anomalies_in_burst_festival = int(df.loc[in_burst, "is_anomaly"].sum())
    assert anomalies_in_burst_festival == 0
    assert (df.loc[in_burst, "status_code"] == 200).all()


def test_generator_scenario_silent_failure_rare_signature_in_window() -> None:
    """Scenario silent_failure: rows in the target window have rare log_signature."""
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    window_start = base_time + SILENT_FAILURE_WINDOW_OFFSET
    window_end = window_start + timedelta(minutes=SILENT_FAILURE_WINDOW_MINUTES)
    rng = np.random.default_rng(88)
    df = generate_logs(n=5_000, rng=rng, base_time=base_time, scenario="silent_failure")
    in_window = (df["timestamp"] >= window_start) & (df["timestamp"] < window_end)
    if in_window.sum() > 0:
        sigs_in_window = df.loc[in_window, "log_signature"].unique()
        assert LOG_SIGNATURE_SILENT_FAILURE in sigs_in_window
    rare_count_silent = (df["log_signature"] == LOG_SIGNATURE_SILENT_FAILURE).sum()
    assert rare_count_silent >= in_window.sum()
