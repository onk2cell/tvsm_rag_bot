# Deploy to live / production server

Use this when the user says **deploy**, **update prod**, **go live**, **prd**, or **update code on server**.

## Server

| Item | Value |
|------|--------|
| Host | `103.195.71.242` |
| SSH port | `3082` |
| User | `onkarg` |
| Identity file | `~/.ssh/tvsm_deploy` |
| App directory | `~/tvsm_rag_bot` |
| Compose profile | `client` (services: `client-worker`, `client-webhook`, `redis`, `admin`) |

SSH one-liner prefix:

```bash
ssh -o BatchMode=yes -p 3082 -i ~/.ssh/tvsm_deploy onkarg@103.195.71.242
```

## Choose a deploy path

### Path A — Uncommitted local changes (usual for WIP)

Code is only on the laptop. Copy files, then rebuild containers.

1. Copy the runtime files you changed (typical set):

```bash
scp -P 3082 -i ~/.ssh/tvsm_deploy \
  client_processing.py \
  client_adapters.py \
  client_tasks.py \
  compose.yaml \
  onkarg@103.195.71.242:~/tvsm_rag_bot/
```

Add/remove files to match what actually changed. Do **not** scp `.env`.

2. Rebuild and restart worker + webhook:

```bash
ssh -o BatchMode=yes -p 3082 -i ~/.ssh/tvsm_deploy onkarg@103.195.71.242 'bash -s' <<'EOF'
set -e
cd ~/tvsm_rag_bot
docker compose --profile client up -d --build client-worker client-webhook
docker compose --profile client ps client-worker client-webhook
sleep 5
docker compose --profile client exec -T client-worker python3 -c "import client_processing; print('worker import: OK')"
echo DEPLOY_OK
EOF
```

### Path B — Changes already committed and pushed

```bash
# laptop
git push

# server
ssh -o BatchMode=yes -p 3082 -i ~/.ssh/tvsm_deploy onkarg@103.195.71.242 \
  'cd ~/tvsm_rag_bot && bash ./update.sh'
```

`update.sh` runs `git pull` then `docker compose --profile client up -d --build`.

## Rules

- Ask for approval / use network permissions before any prod SSH/scp.
- Never overwrite or print prod `.env` secrets.
- Prefer rebuilding only `client-worker` + `client-webhook` unless the user asks for full stack.
- Leave Redis data and `data/` alone unless the user explicitly asks to clear sessions/leads.
- Do not `git push --force`, `reset --hard`, or `clean` on prod unless the user explicitly requests it.
- After deploy, confirm containers are up/healthy and report which path (A or B) you used.

## Verify

```bash
ssh -o BatchMode=yes -p 3082 -i ~/.ssh/tvsm_deploy onkarg@103.195.71.242 \
  'cd ~/tvsm_rag_bot && docker compose --profile client ps client-worker client-webhook && docker compose --profile client logs --tail 20 client-worker'
```

Look for worker healthy and no crash loops. For dispose-on-pincode work, logs may show `dispose ok mobile=...` or `dispose failed mobile=...`.
