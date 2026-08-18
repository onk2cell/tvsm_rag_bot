# Admin Panel on a Stable URL — DevOps Runbook

**Audience:** whoever owns infrastructure for the TVS WhatsApp bot
**Goal:** reach the admin panel at a permanent address on our own domain, with a real login, without changing how customer traffic flows
**Time:** ~30 minutes, no downtime

---

## What is running today

| Item | Value |
|---|---|
| Host | `103.195.71.242` (SSH port `3082`, user `onkarg`, key `~/.ssh/tvsm_deploy`) |
| App directory | `~/tvsm_rag_bot` |
| Admin panel | container `admin`, published on host port **8006** |
| Media (brochures) | container `tvsm-media-nginx`, host port **8088** |
| Compose profile | `client` — `admin`, `client-webhook`, `client-worker`, `redis` |

SSH prefix used throughout:

```bash
ssh -p 3082 -i ~/.ssh/tvsm_deploy onkarg@103.195.71.242
```

### The constraint that shapes everything

**This box is behind NAT and has no inbound ports forwarded.** Verified:

- nginx listens on `:80`, but `/var/log/nginx/access.log` has been **0 bytes since 25 Jul** — nothing from outside has ever reached it
- **Nothing listens on `:443`.** No `listen 443`, no `ssl_certificate` anywhere in the nginx config. There is no TLS on this server
- The `web` container logged a request from `192.168.1.1`, i.e. a router doing NAT in front of the public IP
- Ports `8000`–`8006` and `8088` bind `0.0.0.0`, but that only means the process accepts connections — it does not make them reachable from the internet

**Therefore inbound port-based access is not available to us.** Everything public here works through Cloudflare tunnels, which dial *outbound* and need no port forwarding. That is why media already uses one.

### Tunnels currently running

Both are **quick tunnels** — free, anonymous, and assigned a **random hostname that changes on every restart**.

| Container | Points at | Serves | Current URL |
|---|---|---|---|
| `tvsm-media-tunnel` | `host.docker.internal:8088` | brochures, location images | `laser-developmental-transport-montreal.trycloudflare.com` |
| `tvsm-admin-tunnel` | `host.docker.internal:8006` | admin panel | `painting-spirit-winter-accordance.trycloudflare.com` |

Both are `--restart unless-stopped`, so they come back after a reboot — **but with different hostnames**.

### Why this needs fixing

1. **The share-location card breaks silently.** `CLIENT_MEDIA_BASE_URL` in the server's `.env` is pinned to the media tunnel's current random hostname. When that tunnel restarts the URL changes, the env var goes stale, and the image 404s with nothing alerting on it. The tunnel has survived since 24 Jul on luck alone.

   Scope, precisely: `media_base_url()` is consumed by exactly one caller, `share_location_image_url()`. **Brochures are not affected** — `documents` in the admin config points at JAM's own CDN (`https://1.jamoutsourcing.com/f`), a different host entirely. So the blast radius is the how-to image shown to customers who do not know their pincode: they get asked to share their location with no picture explaining how. Real, and worth fixing, but not the whole document pipeline.
2. **The admin panel is protected by one shared static token.** No expiry, no rate limit, no lockout, no record of who accessed what — in front of every customer's phone number, name, and full chat transcript.

Both are fixed by the same change.

---

## Prerequisites

- A **Cloudflare account** with a domain we control (free plan is sufficient)
- That domain's **nameservers already pointed at Cloudflare** (Cloudflare must be authoritative for DNS, or `route dns` fails)
- SSH access to the box

`cloudflared` **v2026.6.1 is already installed on the host** — no install step needed.

Pick two hostnames. This runbook uses `admin.example.com` and `media.example.com`; substitute the real ones.

---

## Option A — Dashboard-managed tunnel (recommended)

Fewer moving parts than config files, and hostnames are editable in the UI later without SSH.

### 1. Create the tunnel

Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared** → name it `tvsm`.

Cloudflare shows an install command containing a long token. **Copy the token only** — we run our own container.

### 2. Add the two public hostnames

Still in the tunnel's config, add:

| Subdomain | Domain | Type | URL |
|---|---|---|---|
| `admin` | `example.com` | HTTP | `host.docker.internal:8006` |
| `media` | `example.com` | HTTP | `host.docker.internal:8088` |

Cloudflare creates the DNS records automatically.

### 3. Run the connector

```bash
docker run -d --name tvsm-tunnel \
  --restart unless-stopped \
  --add-host host.docker.internal:host-gateway \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate run --token <TOKEN-FROM-DASHBOARD>
```

`--add-host host.docker.internal:host-gateway` is required — it is how the container reaches services published on the host. The existing tunnels use the same flag.

### 4. Verify before touching anything else

```bash
curl -s -o /dev/null -w "admin  %{http_code}\n" https://admin.example.com/admin/health
curl -s -o /dev/null -w "status %{http_code} (expect 401)\n" https://admin.example.com/admin/api/status
curl -s -o /dev/null -w "media  %{http_code} %{size_download}b\n" \
  https://media.example.com/media/brochures/king_ev_max.pdf
```

Expect `200`, `401`, and `200` with roughly 3.2 MB. **Do not proceed until all three pass.** The old tunnels are still running, so nothing is at risk yet.

---

## Option B — CLI-managed tunnel

Use this instead of Option A if config-as-file is preferred.

```bash
cloudflared tunnel login          # opens a browser URL; writes ~/.cloudflared/cert.pem
cloudflared tunnel create tvsm    # writes ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns tvsm admin.example.com
cloudflared tunnel route dns tvsm media.example.com
```

`/etc/cloudflared/config.yml`:

```yaml
tunnel: <UUID>
credentials-file: /etc/cloudflared/<UUID>.json

ingress:
  - hostname: admin.example.com
    service: http://127.0.0.1:8006
  - hostname: media.example.com
    service: http://127.0.0.1:8088
  - service: http_status:404
```

```bash
sudo cp ~/.cloudflared/<UUID>.json /etc/cloudflared/
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

Then run the same verification as Option A step 4.

---

## 5. Point media at the stable URL

Only after verification passes.

```bash
cd ~/tvsm_rag_bot
cp .env .env.bak.$(date +%F)          # keep a rollback copy
```

Edit `.env`:

```diff
-CLIENT_MEDIA_BASE_URL=https://laser-developmental-transport-montreal.trycloudflare.com/media
+CLIENT_MEDIA_BASE_URL=https://media.example.com/media
```

Restart the worker so it re-reads `.env`:

```bash
docker compose --profile client up -d client-worker
docker compose --profile client ps client-worker
```

> Do **not** `scp` a local `.env` over the server's. It holds production secrets that exist nowhere else.

**Optional while in there** — two settings the admin status page uses. Both have working defaults, so this is only needed to tune them:

```
ADMIN_QUEUE_WARN_DEPTH=20     # queue depth at which the status page goes amber
ADMIN_PROBE_CACHE_SEC=60      # how long a live JAM reachability probe is reused
```

`ADMIN_QUEUE_WARN_DEPTH=20` is a placeholder — nobody has measured real peak volume yet. Watch a campaign push, then set it from actual numbers.

---

## 6. Put a real login in front of the admin panel

**Do not skip this.** Without it, the panel is a public URL protected by one shared password, in front of customer PII.

Cloudflare dashboard → **Zero Trust** → **Access** → **Applications** → **Add an application** → **Self-hosted**.

- Application domain: `admin.example.com`
- Policy: **Allow**, rule type **Emails**, listing the people who should have access

Cloudflare then challenges every visitor for an email one-time code before the request ever reaches our server. Free for up to 50 users.

This gives us what the shared token cannot: per-person access, and revoking one person without changing everyone else's credentials.

The `ADMIN_TOKEN` stays in place as a second factor behind it.

---

## 7. Retire the quick tunnels

Only once the new hostnames have been serving correctly for a while.

```bash
docker rm -f tvsm-admin-tunnel
docker rm -f tvsm-media-tunnel
```

Removing `tvsm-media-tunnel` **breaks the share-location card instantly** if step 5 was skipped or `.env` was not applied. Confirm the image loads over `media.example.com` first. (Brochures come from JAM's CDN and are unaffected either way.)

---

## Rollback

| Situation | Action |
|---|---|
| New tunnel misbehaves, quick tunnels still running | `docker rm -f tvsm-tunnel`. Nothing else changed; old URLs keep working |
| Share-location image stopped after the `.env` edit | `cp .env.bak.<date> .env` then `docker compose --profile client up -d client-worker` |
| Quick tunnels already deleted and the new one fails | Recreate: `docker run -d --name tvsm-media-tunnel --restart unless-stopped --add-host host.docker.internal:host-gateway cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://host.docker.internal:8088`, read the new URL from `docker logs`, put it in `.env`, restart `client-worker` |

Read a quick tunnel's current URL at any time:

```bash
docker logs tvsm-media-tunnel 2>&1 | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | tail -1
```

---

## Alternative if we control the router

If someone can forward **:80** and **:443** to `103.195.71.242`, tunnels become unnecessary: nginx already has an `acme-challenge` location, so Let's Encrypt would issue a certificate and we could serve `admin` and `media` from our own nginx directly.

That is cleaner long term and removes the Cloudflare dependency. It is listed second only because the router change is outside our control, and the existing `acme-challenge` block suggests someone attempted this before and stopped.

If that route is taken, **still put authentication in front of `/admin/`** — Let's Encrypt solves transport encryption, not access control.

---

## Do not change

These carry live customer traffic and are unrelated to this work:

- The `/client/` nginx location, and containers `client-webhook`, `client-worker`, `redis`
- The `data/` directory — leads, interaction history, dealer data, the runtime Gemini key
- The server's `.env` beyond the lines named above

There are also orphan containers (`tvsm_rag_bot-webhook-1`, `tvsm_rag_bot-worker-1`, `tvsm_rag_bot-web-1`) up ~4 weeks from an older stack. One of them registers as a second RQ worker, which is why the admin status page reports two workers. Cleaning them up is worth doing but is a separate change — confirm they are genuinely unused first.
