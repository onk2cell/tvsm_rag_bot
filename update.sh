#!/usr/bin/env bash
# One-command redeploy on the server: pull latest code and restart client stack.
# .env is gitignored and lives only on the server, so it is never overwritten.
set -e

# Server has no real home dir; fall back to the writable workspace.
[ -d "$HOME" ] || export HOME=/var/tmp/onkarg

cd "$(dirname "$0")"

echo "==> Pulling latest code..."
git pull

echo "==> Rebuilding and restarting JAM client stack..."
docker compose --profile client up -d --build

echo "==> Done. client-webhook + client-worker restarted."
