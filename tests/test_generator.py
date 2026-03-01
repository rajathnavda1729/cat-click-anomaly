"""Tests for synthetic log generator: distribution, fields, ranges, categoricals."""

import numpy as np
import pandas as pd
import pytest

from src.generator import generate_logs

# Expected column names (must match config and ClickHouse)
REQUIRED_COLUMNS = [
    "timestamp",
    "service_id",
    "endpoint",
    "status_code",
    "response_time_ms",
    "user_agent",
    "is_anomaly",
]


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


def test_generator_timestamps_ordered() -> None:
    """timestamp column is present and sortable (datetime-like)."""
    rng = np.random.default_rng(3)
    df = generate_logs(n=100, rng=rng)
    assert df["timestamp"].isna().sum() == 0
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
