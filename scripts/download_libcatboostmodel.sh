#!/usr/bin/env bash
# Download prebuilt CatBoost C evaluation library for Linux (for ClickHouse Docker).
# Saves as libcatboostmodel.so in project root. Use with: clickhouse/config.d mounted in docker-compose.
#
# Usage: scripts/download_libcatboostmodel.sh [VERSION] [ARCH]
#   VERSION defaults to 1.2.10
#   ARCH defaults to x86_64. On Apple Silicon (M1/M2) Docker runs linux/arm64 → use aarch64
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION="${1:-1.2.10}"
ARCH="${2:-x86_64}"   # Use aarch64 for Apple Silicon / linux/arm64 containers
ASSET="libcatboostmodel-linux-${ARCH}-${VERSION}.so"
URL="https://github.com/catboost/catboost/releases/download/v${VERSION}/${ASSET}"
OUTPUT="libcatboostmodel.so"

if [[ -f "$OUTPUT" ]]; then
  echo "$OUTPUT already exists. Remove it to re-download."
  exit 0
fi

echo "Downloading CatBoost C evaluation library v${VERSION} (Linux ${ARCH})..."
if command -v curl &>/dev/null; then
  curl -sSL -o "$OUTPUT" "$URL"
elif command -v wget &>/dev/null; then
  wget -q -O "$OUTPUT" "$URL"
else
  echo "Need curl or wget to download."
  exit 1
fi

if [[ ! -s "$OUTPUT" ]]; then
  echo "Download failed or empty. Check URL: $URL"
  rm -f "$OUTPUT"
  exit 1
fi
echo "Saved to $PROJECT_ROOT/$OUTPUT"
echo "Next: docker compose up -d --force-recreate && python create_view.py"
