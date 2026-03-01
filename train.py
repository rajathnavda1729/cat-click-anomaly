"""Train CatBoost binary classifier for anomaly detection; export model for ClickHouse."""

import argparse
import sys
from pathlib import Path
from typing import Optional

from catboost import CatBoostClassifier
from clickhouse_driver import Client

from src.config import (
    FEATURE_COLUMNS,
    CAT_FEATURES,
    TARGET,
    MODEL_PATH,
    get_clickhouse_connection_params,
)
from src.data import load_training_data

# TRD hyperparameters
ITERATIONS = 500
LEARNING_RATE = 0.1


def train_model(
    client: Optional[Client] = None,
    model_path: str = MODEL_PATH,
    iterations: int = ITERATIONS,
    learning_rate: float = LEARNING_RATE,
) -> str:
    """Load data from ClickHouse, train CatBoost, save model. Returns path to saved model."""
    if client is None:
        client = Client(**get_clickhouse_connection_params())
    df = load_training_data(client=client)
    X = df[FEATURE_COLUMNS]
    y = df[TARGET]
    model = CatBoostClassifier(
        iterations=iterations,
        learning_rate=learning_rate,
        cat_features=CAT_FEATURES,
        random_seed=42,
        verbose=0,
    )
    model.fit(X, y)
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_model(model_path)
    return model_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Train CatBoost anomaly model from ClickHouse data")
    parser.add_argument("-o", "--output", default=MODEL_PATH, help="Output model path (.bin)")
    parser.add_argument("--iterations", type=int, default=ITERATIONS, help="CatBoost iterations")
    parser.add_argument("--learning-rate", type=float, default=LEARNING_RATE, help="Learning rate")
    args = parser.parse_args()
    path = train_model(model_path=args.output, iterations=args.iterations, learning_rate=args.learning_rate)
    print(f"Model saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
