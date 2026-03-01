"""Create anomalous_events view in ClickHouse (run after train.py and with Docker volume mount)."""

import sys
from clickhouse_driver import Client
from clickhouse_driver.errors import NetworkError

from src.config import MODEL_PATH_IN_CONTAINER, get_clickhouse_connection_params
from src.inference import ensure_anomalous_events_view


def main() -> int:
    try:
        client = Client(**get_clickhouse_connection_params())
        ensure_anomalous_events_view(client, MODEL_PATH_IN_CONTAINER)
    except NetworkError:
        print("Could not connect to ClickHouse (connection reset or refused).", file=sys.stderr)
        print("Check:", file=sys.stderr)
        print("  1. Container is running: docker ps --filter name=cat-click-anomaly-ch", file=sys.stderr)
        print("  2. Logs for crashes: docker logs cat-click-anomaly-ch --tail 80", file=sys.stderr)
        print("  3. On Apple Silicon, use aarch64 library: rm -f libcatboostmodel.so && bash scripts/download_libcatboostmodel.sh 1.2.10 aarch64", file=sys.stderr)
        print("  4. If ClickHouse crashes on startup, start without CatBoost config: docker compose -f docker-compose.yml -f docker-compose.no-catboost.yml up -d", file=sys.stderr)
        return 1
    print(f"View anomalous_events created (model path: {MODEL_PATH_IN_CONTAINER})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
