"""Synthetic log generator: 80% normal, 20% anomaly traffic for service_logs."""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# Normal traffic: common endpoints and user agents
NORMAL_ENDPOINTS = ["/api/health", "/api/users", "/api/orders", "/api/products", "/api/search"]
NORMAL_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/96.0.4664.110",
]
# Anomaly: unusual user agents and 5xx-like behavior
ANOMALY_USER_AGENTS = [
    "MaliciousBot/1.0",
    "curl/7.99.99",
    "Python-requests/2.99",
    "Scanner/Probe",
    "Unknown-Weird-Client",
]
SERVICE_IDS = ["svc-a", "svc-b", "svc-c"]


def generate_logs(
    n: int,
    *,
    rng: Optional[np.random.Generator] = None,
    anomaly_ratio: float = 0.20,
    base_time: Optional[datetime] = None,
) -> pd.DataFrame:
    """Generate n rows of synthetic service logs (80% normal, 20% anomaly by default).

    Normal: status 200, Gaussian response times, consistent endpoints/user_agents.
    Anomaly: 5xx spikes, unusual user_agent, high latency.
    """
    if rng is None:
        rng = np.random.default_rng()
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, 0)

    n_anom = int(round(n * anomaly_ratio))
    n_norm = n - n_anom

    # Timestamps: spread over ~7 days
    ts_deltas = rng.integers(0, 7 * 24 * 3600 * 1000, size=n)  # milliseconds
    timestamps = [base_time + timedelta(milliseconds=int(d)) for d in ts_deltas]
    rng.shuffle(timestamps)

    is_anomaly = np.array([1] * n_anom + [0] * n_norm, dtype=np.uint8)
    rng.shuffle(is_anomaly)

    service_ids: list[str] = []
    endpoints: list[str] = []
    status_codes: list[int] = []
    response_times: list[int] = []
    user_agents: list[str] = []

    for i in range(n):
        if is_anomaly[i]:
            service_ids.append(rng.choice(SERVICE_IDS))
            endpoints.append(rng.choice(["/api/unknown", "/admin", "/debug", "/.env"]))
            status_codes.append(int(rng.choice([500, 502, 503])))
            # High latency: 2000–10000 ms
            response_times.append(int(rng.integers(2000, 10001)))
            user_agents.append(rng.choice(ANOMALY_USER_AGENTS))
        else:
            service_ids.append(rng.choice(SERVICE_IDS))
            endpoints.append(rng.choice(NORMAL_ENDPOINTS))
            status_codes.append(200)
            # Gaussian-ish latency: mean ~150 ms, std ~50, clip to positive
            rt = int(rng.normal(150, 50))
            response_times.append(max(1, min(rt, 1000)))
            user_agents.append(rng.choice(NORMAL_USER_AGENTS))

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "service_id": service_ids,
            "endpoint": endpoints,
            "status_code": np.array(status_codes, dtype=np.uint16),
            "response_time_ms": np.array(response_times, dtype=np.uint32),
            "user_agent": user_agents,
            "is_anomaly": is_anomaly,
        },
        columns=[
            "timestamp",
            "service_id",
            "endpoint",
            "status_code",
            "response_time_ms",
            "user_agent",
            "is_anomaly",
        ],
    )
