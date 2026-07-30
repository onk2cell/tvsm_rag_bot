#!/usr/bin/env bash
set -euo pipefail

PROJECT=tvsm-rag-lab

cleanup() {
  docker compose -p "$PROJECT" --profile lab down --volumes
}
trap cleanup EXIT

docker compose -p "$PROJECT" --profile lab up \
  --build --detach --wait redis mock-client lab-webhook lab-worker

python3 scripts/mock_client_smoke.py
