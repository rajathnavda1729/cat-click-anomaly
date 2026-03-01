"""Data loading and feature contract tests for training pipeline."""

import pytest
from clickhouse_driver import Client

from src.config import FEATURE_COLUMNS, CAT_FEATURES, TARGET
from src.data import load_training_data
from src.schema import ensure_service_logs_table


@pytest.mark.integration
def test_load_training_data_returns_expected_columns(ch_client: Client) -> None:
    """load_training_data returns a DataFrame with feature columns + target in order."""
    ensure_service_logs_table(ch_client)
    df = load_training_data(client=ch_client, limit=100)
    expected_cols = FEATURE_COLUMNS + [TARGET]
    assert list(df.columns) == expected_cols, f"Expected {expected_cols}, got {list(df.columns)}"


@pytest.mark.integration
def test_load_training_data_feature_contract(ch_client: Client) -> None:
    """Categorical features are object/string; numeric are int; column order is stable."""
    ensure_service_logs_table(ch_client)
    df = load_training_data(client=ch_client, limit=500)
    for col in CAT_FEATURES:
        assert col in df.columns
    for col in ["status_code", "response_time_ms", TARGET]:
        assert col in df.columns
    assert set(df[TARGET].unique()).issubset({0, 1})


@pytest.mark.integration
def test_load_training_data_categorical_list_matches_config() -> None:
    """CAT_FEATURES is subset of FEATURE_COLUMNS and order is stable for CatBoost."""
    assert set(CAT_FEATURES).issubset(set(FEATURE_COLUMNS))
    assert CAT_FEATURES == ["service_id", "endpoint", "user_agent"]
    assert FEATURE_COLUMNS == ["status_code", "response_time_ms", "service_id", "endpoint", "user_agent"]
