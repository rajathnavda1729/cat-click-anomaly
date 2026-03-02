"""Ingest synthetic logs into ClickHouse: create v2 table and insert rows (with optional scenario)."""

import argparse
import sys
from typing import Optional

import numpy as np
from clickhouse_driver import Client

from src.config import (
    SERVICE_LOGS_V2_TABLE,
    get_clickhouse_connection_params,
)
from src.generator import V2_COLUMNS, generate_logs
from src.schema import ensure_service_logs_v2_table
from src.feature_store import ensure_log_features_1m, ensure_log_features_mv

INSERT_BATCH_SIZE = 10_000
SCENARIOS = ("normal", "festival", "silent_failure")


def run_ingest(
    n: int = 100_000,
    *,
    seed: Optional[int] = 42,
    scenario: str = "normal",
    client: Optional[Client] = None,
) -> int:
    """Create service_logs_v2 and feature store if needed; insert n synthetic rows. Returns rows inserted."""
    if client is None:
        client = Client(**get_clickhouse_connection_params())
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, got {scenario!r}")
    ensure_service_logs_v2_table(client)
    ensure_log_features_1m(client)
    ensure_log_features_mv(client)
    rng = np.random.default_rng(seed)
    df = generate_logs(n=n, rng=rng, scenario=scenario)
    rows = [tuple(df.loc[i, c] for c in V2_COLUMNS) for i in range(len(df))]
    inserted = 0
    for i in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[i : i + INSERT_BATCH_SIZE]
        client.execute(f"INSERT INTO {SERVICE_LOGS_V2_TABLE} VALUES", batch)
        inserted += len(batch)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest synthetic logs into ClickHouse (v2)")
    parser.add_argument("-n", "--rows", type=int, default=100_000, help="Number of rows to generate and insert")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--scenario",
        type=str,
        default="normal",
        choices=SCENARIOS,
        help="Scenario: normal, festival (10× burst in a 5-min window), silent_failure (rare log_signature in a window)",
    )
    args = parser.parse_args()
    inserted = run_ingest(n=args.rows, seed=args.seed, scenario=args.scenario)
    print(f"Inserted {inserted} rows into {SERVICE_LOGS_V2_TABLE} (scenario={args.scenario})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
