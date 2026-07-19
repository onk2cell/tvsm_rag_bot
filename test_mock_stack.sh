#!/usr/bin/env bash
set -euo pipefail

PROJECT=tvsm-rag-mock

cleanup() {
  docker compose -p "$PROJECT" --profile mock down --volumes
}
trap cleanup EXIT

docker compose -p "$PROJECT" --profile mock up \
  --build --detach redis mock-client client-webhook-mock mock-worker

python3 scripts/mock_client_smoke.py
