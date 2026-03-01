"""ClickHouse schema: create and validate service_logs table."""

from clickhouse_driver import Client

from src.config import SERVICE_LOGS_DDL, SERVICE_LOGS_TABLE


def ensure_service_logs_table(client: Client) -> None:
    """Create service_logs table if it does not exist."""
    client.execute(SERVICE_LOGS_DDL)


def get_table_columns(client: Client, table: str = SERVICE_LOGS_TABLE) -> list[tuple[str, str]]:
    """Return list of (name, type) for table from ClickHouse system.columns."""
    rows = client.execute(
        "SELECT name, type FROM system.columns WHERE table = %(table)s ORDER BY position",
        {"table": table},
    )
    return [(r[0], r[1]) for r in rows]


def table_exists(client: Client, table: str = SERVICE_LOGS_TABLE) -> bool:
    """Return True if table exists in default database."""
    result = client.execute(
        "SELECT count() FROM system.tables WHERE database = currentDatabase() AND name = %(table)s",
        {"table": table},
    )
    return result[0][0] > 0
