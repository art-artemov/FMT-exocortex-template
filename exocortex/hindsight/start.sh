#!/bin/bash
# start.sh — launch Hindsight for IWE
# Usage: bash start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: OPENAI_API_KEY is not set."
    echo "Export it first: export OPENAI_API_KEY=sk-..."
    echo "Or add it to ~/.iwe/hindsight.env"
    exit 1
fi

echo "Starting Hindsight (localhost:8888)..."
docker compose up -d

echo "Waiting for healthcheck..."
for i in {1..30}; do
    if curl -sf http://localhost:8888/health >/dev/null 2>&1; then
        echo "Hindsight is ready."
        exit 0
    fi
    sleep 1
done

echo "ERROR: Hindsight did not become healthy within 30s."
echo "Check logs: docker logs iwe-hindsight"
exit 1
