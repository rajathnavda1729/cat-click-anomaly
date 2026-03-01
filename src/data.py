"""Load training data from ClickHouse into a DataFrame (feature columns + target)."""

from typing import Optional

import pandas as pd
from clickhouse_driver import Client

from src.config import (
    FEATURE_COLUMNS,
    TARGET,
    SERVICE_LOGS_TABLE,
    get_clickhouse_connection_params,
)


def load_training_data(
    client: Optional[Client] = None,
    table: str = SERVICE_LOGS_TABLE,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Query ClickHouse for training data; return DataFrame with FEATURE_COLUMNS + TARGET in stable order."""
    if client is None:
        client = Client(**get_clickhouse_connection_params())
    cols = FEATURE_COLUMNS + [TARGET]
    sql = f"SELECT {', '.join(cols)} FROM {table}"
    if limit is not None:
        sql += f" LIMIT {limit}"
    result = client.execute(sql, with_column_types=True)
    rows, types = result
    columns = [t[0] for t in types]
    df = pd.DataFrame(rows, columns=columns)
    return df[cols]

