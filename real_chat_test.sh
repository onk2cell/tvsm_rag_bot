#!/usr/bin/env bash
set -euo pipefail

project="tvsm-rag-real-chat"
profile="real-chat-test"
services=(redis real-chat-client real-chat-worker client-webhook-real-chat)
action="${1:-up}"

case "$action" in
  up)
    if [[ ! -f .env ]]; then
      echo "Missing .env. Copy .env.example to .env and set GEMINI_API_KEY and FILE_SEARCH_STORE."
      exit 1
    fi
    docker compose -p "$project" --profile "$profile" up \
      --build --detach --wait "${services[@]}"
    echo
    echo "Real webhook test chat is ready:"
    echo "http://localhost:8003/mock/chat"
    ;;
  down)
    docker compose -p "$project" --profile "$profile" down
    ;;
  logs)
    docker compose -p "$project" --profile "$profile" logs --follow \
      real-chat-client real-chat-worker client-webhook-real-chat
    ;;
  *)
    echo "Usage: bash real_chat_test.sh [up|down|logs]"
    exit 2
    ;;
esac
