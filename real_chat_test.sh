#!/usr/bin/env bash
# Start the local WhatsApp bot lab (mock CRM + real webhook/worker path).
set -euo pipefail

project="${COMPOSE_PROJECT_NAME:-tvsm-rag-lab}"
action="${1:-up}"

case "$action" in
  up)
    docker compose -p "$project" --profile lab up \
      --build --detach --wait redis mock-client lab-webhook lab-worker
    echo
    echo "WhatsApp bot lab is ready:"
    echo "http://localhost:8003/mock/chat"
    echo
    echo "Tip: Save CRM, then Reset session before a fresh language-menu flow."
    ;;
  down)
    docker compose -p "$project" --profile lab down
    ;;
  logs)
    docker compose -p "$project" --profile lab logs --follow \
      mock-client lab-webhook lab-worker
    ;;
  *)
    echo "Usage: bash real_chat_test.sh [up|down|logs]"
    exit 2
    ;;
esac
