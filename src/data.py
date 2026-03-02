"""Load training data from ClickHouse into a DataFrame (feature columns + target)."""

from typing import Optional

import pandas as pd
from clickhouse_driver import Client

from src.config import (
    FEATURE_COLUMNS,
    FEATURE_COLUMNS_V2,
    TARGET,
    SERVICE_LOGS_TABLE,
    SERVICE_LOGS_V2_TABLE,
    get_clickhouse_connection_params,
)


def load_training_data(
    client: Optional[Client] = None,
    table: Optional[str] = None,
    limit: Optional[int] = None,
    *,
    use_v2: bool = True,
) -> pd.DataFrame:
    """Query ClickHouse for training data; return DataFrame with feature columns + TARGET in stable order.

    If use_v2 is True (default), reads from service_logs_v2 and uses FEATURE_COLUMNS_V2.
    If use_v2 is False, reads from service_logs and uses FEATURE_COLUMNS (v1).
    If table is given, it overrides the default table; use_v2 is then inferred from table name.
    """
    if client is None:
        client = Client(**get_clickhouse_connection_params())
    if table is None:
        table = SERVICE_LOGS_V2_TABLE if use_v2 else SERVICE_LOGS_TABLE
    else:
        use_v2 = table == SERVICE_LOGS_V2_TABLE
    feature_cols = FEATURE_COLUMNS_V2 if use_v2 else FEATURE_COLUMNS
    cols = feature_cols + [TARGET]
    sql = f"SELECT {', '.join(cols)} FROM {table}"
    if limit is not None:
        sql += f" LIMIT {limit}"
    result = client.execute(sql, with_column_types=True)
    rows, types = result
    columns = [t[0] for t in types]
    df = pd.DataFrame(rows, columns=columns)
    return df[cols]

