#!/usr/bin/env bash
# Pull latest code and refresh deps on the server.
# .env stays untouched (it's gitignored and lives only on the server).
set -e
cd "$(dirname "$0")"

echo "==> Pulling latest code..."
git pull

echo "==> Updating dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

echo "==> Done."
echo "If uvicorn is running with --reload, code changes are already live."
echo "If requirements.txt changed, restart uvicorn to load new packages."
