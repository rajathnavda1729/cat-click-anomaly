"""Schema contract tests: service_logs table exists and matches expected columns."""

import pytest
from clickhouse_driver import Client

from src.config import SERVICE_LOGS_TABLE, SERVICE_LOGS_COLUMNS
from src.schema import ensure_service_logs_table, get_table_columns, table_exists


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
