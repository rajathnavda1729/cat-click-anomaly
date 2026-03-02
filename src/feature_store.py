"""Feature store: 1-minute aggregates table and materialized view from service_logs_v2."""

from clickhouse_driver import Client

from src.config import (
    LOG_FEATURES_1M_DDL,
    LOG_FEATURES_1M_TABLE,
    LOG_FEATURES_MV_DDL,
    LOG_FEATURES_MV,
)


def ensure_log_features_1m(client: Client) -> None:
    """Create log_features_1m AggregatingMergeTree table if it does not exist (TTL 14 days)."""
    client.execute(LOG_FEATURES_1M_DDL)


def ensure_log_features_mv(client: Client) -> None:
    """Create materialized view from service_logs_v2 to log_features_1m if it does not exist.
    Call ensure_log_features_1m first."""
    client.execute(LOG_FEATURES_MV_DDL)


def feature_store_ready(client: Client) -> bool:
    """Return True if both log_features_1m table and log_features_mv exist."""
    tables = client.execute(
        "SELECT name FROM system.tables WHERE database = currentDatabase() AND name IN %(names)s",
        {"names": (LOG_FEATURES_1M_TABLE, LOG_FEATURES_MV)},
    )
    return len(tables) == 2
