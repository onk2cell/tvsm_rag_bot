#!/usr/bin/env bash
# One-command redeploy on the server: pull latest code, refresh deps, restart app.
# Does NOT touch Docker or the cloudflared tunnel, so the public URL stays the same.
# .env is gitignored and lives only on the server, so it is never overwritten.
set -e

# Server has no real home dir; fall back to the writable workspace.
[ -d "$HOME" ] || export HOME=/var/tmp/onkarg

cd "$(dirname "$0")"
PORT=8123

echo "==> Pulling latest code..."
git pull

echo "==> Updating dependencies..."
source venv/bin/activate
pip install -q -r requirements.txt

echo "==> Restarting app on port $PORT (only our uvicorn; Docker untouched)..."
pkill -f "uvicorn web:app --host 127.0.0.1 --port $PORT" 2>/dev/null || true
sleep 1
nohup uvicorn web:app --host 127.0.0.1 --port "$PORT" > app.log 2>&1 &
sleep 3
tail -n 5 app.log

echo "==> Done. Public tunnel URL is unchanged."
