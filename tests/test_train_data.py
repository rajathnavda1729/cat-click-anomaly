"""Data loading and feature contract tests for training pipeline (v2)."""

import pytest
from clickhouse_driver import Client

from src.config import (
    FEATURE_COLUMNS_V2,
    CAT_FEATURES_V2,
    TARGET,
)
from src.data import load_training_data
from src.schema import ensure_service_logs_v2_table


@pytest.mark.integration
def test_load_training_data_returns_expected_columns(ch_client: Client) -> None:
    """load_training_data(use_v2=True) returns a DataFrame with FEATURE_COLUMNS_V2 + target in order."""
    ensure_service_logs_v2_table(ch_client)
    df = load_training_data(client=ch_client, limit=100, use_v2=True)
    expected_cols = FEATURE_COLUMNS_V2 + [TARGET]
    assert list(df.columns) == expected_cols, f"Expected {expected_cols}, got {list(df.columns)}"


@pytest.mark.integration
def test_load_training_data_feature_contract(ch_client: Client) -> None:
    """Categorical and numeric columns present; column order matches FEATURE_COLUMNS_V2 (no text in v2)."""
    ensure_service_logs_v2_table(ch_client)
    df = load_training_data(client=ch_client, limit=500, use_v2=True)
    for col in CAT_FEATURES_V2:
        assert col in df.columns
    for col in ["status_code", "response_time_ms", "throughput_velocity", "error_acceleration", "hour_of_day", TARGET]:
        assert col in df.columns
    assert set(df[TARGET].unique()).issubset({0, 1})


@pytest.mark.integration
def test_load_training_data_v2_contract_matches_config() -> None:
    """CAT_FEATURES_V2 is subset of FEATURE_COLUMNS_V2; order stable for CatBoost and ClickHouse."""
    assert set(CAT_FEATURES_V2).issubset(set(FEATURE_COLUMNS_V2))
    assert FEATURE_COLUMNS_V2 == [
        "status_code",
        "response_time_ms",
        "throughput_velocity",
        "error_acceleration",
        "hour_of_day",
        "service_id",
        "endpoint",
        "log_signature",
    ]
    assert CAT_FEATURES_V2 == ["service_id", "endpoint", "log_signature"]
