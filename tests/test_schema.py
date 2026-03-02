"""Schema contract tests: service_logs (v1) and service_logs_v2 tables exist and match expected columns."""

import pytest
from clickhouse_driver import Client

from src.config import (
    SERVICE_LOGS_TABLE,
    SERVICE_LOGS_COLUMNS,
    SERVICE_LOGS_V2_TABLE,
    SERVICE_LOGS_V2_COLUMNS,
)
from src.schema import (
    ensure_service_logs_table,
    ensure_service_logs_v2_table,
    get_table_columns,
    table_exists,
)


@pytest.mark.integration
def test_service_logs_table_exists_after_ensure(ch_client: Client) -> None:
    """ensure_service_logs_table creates table; table_exists returns True."""
    ensure_service_logs_table(ch_client)
    assert table_exists(ch_client, SERVICE_LOGS_TABLE)


@pytest.mark.integration
def test_service_logs_schema_matches_contract(ch_client: Client) -> None:
    """Table has exactly the expected columns in order (name and type)."""
    ensure_service_logs_table(ch_client)
    actual = get_table_columns(ch_client, SERVICE_LOGS_TABLE)
    assert actual == SERVICE_LOGS_COLUMNS, f"Expected {SERVICE_LOGS_COLUMNS}, got {actual}"


@pytest.mark.integration
def test_service_logs_v2_table_exists_after_ensure(ch_client: Client) -> None:
    """ensure_service_logs_v2_table creates v2 table; table_exists returns True."""
    ensure_service_logs_v2_table(ch_client)
    assert table_exists(ch_client, SERVICE_LOGS_V2_TABLE)


@pytest.mark.integration
def test_service_logs_v2_schema_matches_contract(ch_client: Client) -> None:
    """v2 table has exactly the expected columns in order (name and type)."""
    ensure_service_logs_v2_table(ch_client)
    actual = get_table_columns(ch_client, SERVICE_LOGS_V2_TABLE)
    assert actual == SERVICE_LOGS_V2_COLUMNS, f"Expected {SERVICE_LOGS_V2_COLUMNS}, got {actual}"
