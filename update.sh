#!/usr/bin/env bash
# One-command redeploy on the server: check out an explicit ref and restart the
# client stack. .env is gitignored and lives only on the server, so it is never
# overwritten.
#
# The ref is REQUIRED and always checked out detached. Production used to track a
# branch and redeploy with a bare `git pull`, which meant anything pushed to that
# branch was one redeploy away from the live bot. Now the code being deployed is
# something a human types:
#
#     ./update.sh tvs-prod-2026-08-21      # rebuild the same production code
#     ./update.sh feature/multi-client     # deliberate move onto new code
#
# WARNING: data/ is a bind mount and is NOT versioned. Rolling back to an older
# ref does not roll back data/admin_config.json, leads.csv, or interactions.db,
# and config is re-validated on every turn — so a newer config schema left on
# disk will break older code. Back up data/ before deploying a ref that changes
# the config schema.
set -e

REF="${1:-}"
if [ -z "$REF" ]; then
    echo "usage: ./update.sh <git-ref>" >&2
    echo "  e.g. ./update.sh tvs-prod-2026-08-21" >&2
    echo >&2
    echo "Available tags:" >&2
    git tag | sed 's/^/  /' >&2
    exit 2
fi

# Server has no real home dir; fall back to the writable workspace.
[ -d "$HOME" ] || export HOME=/var/tmp/onkarg

cd "$(dirname "$0")"

echo "==> Fetching refs..."
git fetch --all --tags --prune

# Prefer the remote-tracking ref so a branch name deploys what is on origin,
# not a stale local copy. Tags and commit SHAs fall through unchanged.
if git rev-parse --verify --quiet "origin/$REF" >/dev/null; then
    TARGET="origin/$REF"
else
    TARGET="$REF"
fi

if ! git rev-parse --verify --quiet "$TARGET" >/dev/null; then
    echo "error: no such ref: $REF" >&2
    exit 1
fi

# Always detached: the server never tracks a branch, so nothing can advance
# underneath it between deploys.
echo "==> Checking out $TARGET ($(git rev-parse --short "$TARGET"))..."
git checkout --detach "$TARGET"

echo "==> Rebuilding and restarting JAM client stack..."
docker compose --profile client up -d --build

echo "==> Done. client-webhook + client-worker restarted."
echo "    ref:    $REF"
echo "    commit: $(git rev-parse --short HEAD)"
