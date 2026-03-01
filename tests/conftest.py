"""Pytest fixtures and shared test config."""

import pytest
from clickhouse_driver import Client

from src.config import get_clickhouse_connection_params


@pytest.fixture(scope="session")
def clickhouse_client() -> Client:
    """Session-scoped ClickHouse client (requires Docker)."""
    return Client(**get_clickhouse_connection_params())


@pytest.fixture
def ch_client(clickhouse_client: Client) -> Client:
    """Per-test alias for clickhouse_client."""
    return clickhouse_client
