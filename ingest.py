"""Ingest synthetic logs into ClickHouse: create table and insert 100k rows."""

import argparse
import sys
from typing import Optional

import numpy as np
from clickhouse_driver import Client

from src.config import SERVICE_LOGS_TABLE, get_clickhouse_connection_params
from src.generator import generate_logs
from src.schema import ensure_service_logs_table

INSERT_BATCH_SIZE = 10_000


def run_ingest(
    n: int = 100_000,
    *,
    seed: Optional[int] = 42,
    client: Optional[Client] = None,
) -> int:
    """Create service_logs table if needed and insert n synthetic rows. Returns rows inserted."""
    if client is None:
        client = Client(**get_clickhouse_connection_params())
    ensure_service_logs_table(client)
    rng = np.random.default_rng(seed)
    df = generate_logs(n=n, rng=rng)
    # Column order must match table
    cols = ["timestamp", "service_id", "endpoint", "status_code", "response_time_ms", "user_agent", "is_anomaly"]
    rows = [tuple(df.loc[i, c] for c in cols) for i in range(len(df))]
    inserted = 0
    for i in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[i : i + INSERT_BATCH_SIZE]
        client.execute(f"INSERT INTO {SERVICE_LOGS_TABLE} VALUES", batch)
        inserted += len(batch)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest synthetic logs into ClickHouse")
    parser.add_argument("-n", "--rows", type=int, default=100_000, help="Number of rows to generate and insert")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()
    inserted = run_ingest(n=args.rows, seed=args.seed)
    print(f"Inserted {inserted} rows into {SERVICE_LOGS_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
