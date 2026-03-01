"""Smoke tests: ClickHouse connectivity and basic sanity (Phase 0)."""

import pytest
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

from src.config import (
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    get_clickhouse_connection_params,
)


@pytest.mark.integration
def test_clickhouse_ping(ch_client: Client) -> None:
    """ClickHouse server is reachable and responds to SELECT 1."""
    result = ch_client.execute("SELECT 1")
    assert result == [(1,)]


@pytest.mark.integration
def test_clickhouse_version(ch_client: Client) -> None:
    """ClickHouse reports version 24.x or higher."""
    result = ch_client.execute("SELECT version()")
    assert len(result) == 1
    version = result[0][0]
    assert version.startswith("24."), f"Expected 24.x, got {version}"


def test_connection_params_from_env() -> None:
    """Connection params use env or defaults (no live connection)."""
    params = get_clickhouse_connection_params()
    assert params["host"] == CLICKHOUSE_HOST
    assert params["port"] == CLICKHOUSE_PORT
    assert isinstance(params["port"], int)


@pytest.mark.integration
def test_clickhouse_connection_fails_gracefully() -> None:
    """Connecting to invalid host raises ClickHouseError (no hang)."""
    with pytest.raises((ClickHouseError, OSError, ConnectionError)):
        bad_client = Client(host="nonexistent.invalid", port=9999, connect_timeout=2)
        bad_client.execute("SELECT 1")
