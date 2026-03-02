#!/usr/bin/env python3
"""Validate anomalous_events output: score distribution and (for POC) alignment with is_anomaly.

Run from project root:
  python scripts/validate_anomaly_output.py

Optional:
- --sample N  (or --limit N) to limit rows (default: 50_000 for speed)
- --threshold to override suggested
- --view NAME to validate a different view (default: ANOMALOUS_EVENTS_VIEW)
"""

import argparse
import sys
from pathlib import Path

# Add project root so "import src" works when run as script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from typing import Optional  # noqa: E402

from clickhouse_driver import Client  # noqa: E402

from src.config import (  # noqa: E402
    ANOMALOUS_EVENTS_VIEW,
    get_clickhouse_connection_params,
)


def run_validation(
    client: Optional[Client] = None,
    sample: Optional[int] = 50_000,
    threshold: Optional[float] = None,
    view: str = ANOMALOUS_EVENTS_VIEW,
) -> None:
    if client is None:
        client = Client(**get_clickhouse_connection_params())

    total = client.execute(f"SELECT count() FROM {view}")[0][0]
    print(f"Total rows in view {view!r}: {total}")

    if total == 0:
        print("No data to validate.")
        return

    limit = f" LIMIT {sample}" if sample and sample < total else ""

    row = client.execute(
        f"SELECT min(anomaly_score), max(anomaly_score), avg(anomaly_score), count() FROM {view}{limit}"
    )[0]
    mn, mx, avg, n = row[0], row[1], row[2], row[3]
    print(f"Sample size: {n}")
    print(f"anomaly_score: min={mn:.4f}, max={mx:.4f}, avg={avg:.4f}")

    nulls = client.execute(f"SELECT count() FROM {view} WHERE anomaly_score IS NULL{limit}")[0][0]
    if nulls:
        print(f"WARNING: {nulls} rows have NULL anomaly_score")
    else:
        print("No NULL anomaly_score.")

    q = f"""
        SELECT is_anomaly,
               count() AS cnt,
               min(anomaly_score) AS min_s,
               max(anomaly_score) AS max_s,
               avg(anomaly_score) AS avg_s
        FROM (SELECT is_anomaly, anomaly_score FROM {view} {limit})
        GROUP BY is_anomaly
        ORDER BY is_anomaly
    """
    try:
        by_label = client.execute(q)
    except Exception as e:
        print(f"Could not group by is_anomaly: {e}")
        by_label = []

    if by_label:
        print("\nBy is_anomaly (ground truth):")
        for (label, cnt, min_s, max_s, avg_s) in by_label:
            print(f"  is_anomaly={label}: count={cnt}, score min/max/avg = {min_s:.4f} / {max_s:.4f} / {avg_s:.4f}")
        suggested = client.execute(
            f"SELECT quantile(0.9)(anomaly_score) FROM {view} {limit}"
        )[0][0]
        print(f"\nSuggested threshold (90th percentile of score): {suggested:.4f}")
        if threshold is None:
            threshold = suggested

        q2 = f"""
            SELECT
                countIf(is_anomaly = 1 AND anomaly_score >= {threshold}) AS tp,
                countIf(is_anomaly = 0 AND anomaly_score >= {threshold}) AS fp,
                countIf(is_anomaly = 1 AND anomaly_score < {threshold}) AS fn,
                countIf(is_anomaly = 0 AND anomaly_score < {threshold}) AS tn
            FROM (SELECT is_anomaly, anomaly_score FROM {view} {limit})
        """
        try:
            tp, fp, fn, tn = client.execute(q2)[0]
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            print(f"\nAt threshold {threshold:.4f}: TP={tp}, FP={fp}, FN={fn}, TN={tn}")
            print(f"  Precision = {prec:.2%}, Recall = {rec:.2%}")
        except Exception as e:
            print(f"Could not compute precision/recall: {e}")
    else:
        print("\nNo is_anomaly groups; skipping threshold validation.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate anomalous_events view output")
    parser.add_argument(
        "--sample",
        type=int,
        default=50_000,
        help="Max rows to sample (default 50000); use 0 for no limit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Alias for --sample (if provided, overrides sample)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Score threshold for precision/recall (default: 90th percentile)",
    )
    parser.add_argument(
        "--view",
        type=str,
        default=ANOMALOUS_EVENTS_VIEW,
        help="View name to validate (default: ANOMALOUS_EVENTS_VIEW)",
    )
    args = parser.parse_args()
    effective_sample = args.limit if args.limit is not None else args.sample
    sample = effective_sample if effective_sample > 0 else None
    try:
        run_validation(sample=sample, threshold=args.threshold, view=args.view)
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
