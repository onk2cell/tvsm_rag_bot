#!/usr/bin/env bash
# Serve the bot's outbound WhatsApp media from the stable public hostname
# instead of the ephemeral cloudflared tunnel.
#
#   bash scripts/media_public_route.sh          # apply (idempotent)
#   bash scripts/media_public_route.sh revert   # tunnel URL back in .env
#
# Before: data/media is served by tvsm-media-nginx on host port 8088 and
# reached only through a cloudflared quick tunnel whose hostname changes
# whenever the tunnel restarts; when it is down, Meta cannot fetch the
# share-location card and every pincode ask degrades. After: the
# force-router nginx on the public port forwards /media/ to 8088, so the
# card lives at https://aichatbot.jamoutsourcing.com:9004/media/... —
# JAM's TLS, JAM's hostname, no tunnel. The route is also in the router's
# apply script (kb_qa_bot/scripts/force_router_on_tvs.sh) so a re-apply
# keeps it. Nothing about the webhook routing changes: /media/ is the
# only new location, and it only serves files.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=103.195.71.242
SSH=(ssh -o BatchMode=yes -p 3082 -i ~/.ssh/tvsm_deploy "onkarg@$HOST")
PUBLIC_MEDIA=https://aichatbot.jamoutsourcing.com:9004/media

if [ "${1:-}" = "revert" ]; then
  "${SSH[@]}" 'bash -s' <<'REMOTE'
set -e
cd ~/tvsm_rag_bot
last=$(ls -t .env.bak-media-* 2>/dev/null | head -1)
[ -n "$last" ] || { echo "no .env.bak-media-* backup to restore"; exit 1; }
old=$(grep -E '^CLIENT_MEDIA_BASE_URL=' "$last" || true)
[ -n "$old" ] || { echo "backup has no CLIENT_MEDIA_BASE_URL"; exit 1; }
sed -i "s#^CLIENT_MEDIA_BASE_URL=.*#${old}#" .env
grep -E '^CLIENT_MEDIA_BASE_URL=' .env
docker compose --profile client up -d client-worker 2>&1 | tail -1
echo REVERTED
REMOTE
  exit
fi

"${SSH[@]}" 'bash -s' <<'REMOTE'
set -e
STAMP=$(date +%Y%m%d-%H%M%S)

echo "== 1. router: /media/ -> tvsm-media-nginx (8088)"
cd ~/force-router
cp -p nginx.conf nginx.conf.bak-$STAMP
python3 - <<'PY'
from pathlib import Path
p = Path("nginx.conf"); s = p.read_text()
if "upstream media" in s:
    print("   already routed; nothing to change")
else:
    s = s.replace(
        "upstream force { server host.docker.internal:8010; }\n",
        "upstream force { server host.docker.internal:8010; }\n"
        "# The TVS bot's outbound WhatsApp images/documents (its data/media, served\n"
        "# by tvsm-media-nginx). On the stable public hostname instead of an\n"
        "# ephemeral cloudflared tunnel, so Meta can always fetch the file.\n"
        "upstream media { server host.docker.internal:8088; }\n", 1)
    s = s.replace(
        "    location /force/client/ { proxy_pass http://force/client/; }\n",
        "    location /media/ { proxy_pass http://media; }\n"
        "    location /force/client/ { proxy_pass http://force/client/; }\n", 1)
    assert "upstream media" in s and "location /media/" in s
    p.write_text(s); print("   /media/ route added")
PY
docker exec force-router nginx -t 2>&1 | tail -1
docker exec force-router nginx -s reload
sleep 1
echo "   router :8002 /media/share_location/how_to.jpg -> $(curl -s -m 5 -o /dev/null -w '%{http_code} %{size_download}B' localhost:8002/media/share_location/how_to.jpg)  (want 200 116209B)"
echo "   router :8002 /force/health                     -> $(curl -s -m 5 -o /dev/null -w '%{http_code}' localhost:8002/force/health)  (want 200)"
echo "   router :8002 webhook, no auth                  -> $(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST localhost:8002/client/webhook/messages -H 'Content-Type: application/json' -d '{}')  (want 401)"

echo "== 2. bot: CLIENT_MEDIA_BASE_URL -> public hostname"
cd ~/tvsm_rag_bot
cp -p .env .env.bak-media-$STAMP
sed -i 's#^CLIENT_MEDIA_BASE_URL=.*#CLIENT_MEDIA_BASE_URL=https://aichatbot.jamoutsourcing.com:9004/media#' .env
grep -E '^CLIENT_MEDIA_BASE_URL=' .env
docker compose --profile client up -d client-worker 2>&1 | tail -1
sleep 5
docker compose --profile client exec -T client-worker python3 -c "
import client_media_assets as m; print('   worker card URL:', m.share_location_image_url('English'))" </dev/null
REMOTE

echo "== 3. from the public internet (this laptop)"
for f in how_to english hindi; do
  curl -sk -o /dev/null -m 15 -w "   %{http_code} %{size_download}B %{content_type} %{time_total}s  $f.jpg\n" \
    "$PUBLIC_MEDIA/share_location/$f.jpg"
done
echo "MEDIA_ROUTE_OK"
