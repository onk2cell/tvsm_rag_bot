# WhatsApp RAG Bot — full version

Managed RAG over one document (Gemini File Search) + WhatsApp Cloud API.

## What this adds over the basic walkthrough
- **Conversation memory** — follow-up questions work ("what about the 125cc one?").
- **Citations** — source titles the answer was grounded on (logged; you can also send them).
- **Webhook signature verification** — rejects forged POSTs (set `APP_SECRET`).
- **Duplicate handling** — Meta sometimes redelivers; we dedupe by message id.
- **Per-user rate limiting** — caps messages/user/minute.
- **Retries** on both the Gemini call and the WhatsApp send.
- **`test_rag.py`** — validate retrieval from the terminal before touching WhatsApp.

## Files
- `config.py` — all settings, read from `.env`
- `index_document.py` — one-time PDF indexing
- `rag.py` — `ask(question, history)` -> `(answer, citations)`
- `memory.py` — history, dedup, rate limit (Redis)
- `whatsapp.py` — send / mark-read / signature verify
- `tasks.py` — the background job
- `app.py` — FastAPI webhook
- `test_rag.py` — terminal RAG tester

## Setup
1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. `cp .env.example .env` and fill in your keys.
4. `python index_document.py manual.pdf` — copy the printed `FILE_SEARCH_STORE=...` into `.env`.
5. `python test_rag.py` — confirm answers look right.

## Run (three processes)
```
redis-server
rq worker
uvicorn app:app --host 0.0.0.0 --port 8000
```
Expose port 8000 over HTTPS (domain + Nginx/Caddy, or `ngrok http 8000` for testing),
then set the webhook URL + verify token in Meta and subscribe to the `messages` field.

## Notes
- Citation field paths in the Gemini SDK can change between versions; `rag.py` reads them
  defensively and simply returns fewer/none if the shape differs.
- Free-form replies only work within 24h of the user's last message; outside that window,
  WhatsApp requires a pre-approved template.

## Interaction history and load tests

Web and WhatsApp turns are stored in `data/interactions.db` for 90 days. Open
`/admin` to filter, export, and review failed interactions.

Synthetic traffic is kept in `data/load_test_interactions.db`. Set a secret in
`.env` before running Locust:

```bash
LOAD_TEST_TOKEN=replace_with_a_long_random_value
```

Load the environment and run ten users:

```bash
set -a; source .env; set +a
locust -f locustfile.py --host http://127.0.0.1:8000 \
  --headless -u 10 -r 2 -t 1m
```

## Client CRM webhook and mock stack

The client-app channel is separate from WhatsApp. It accepts Basic-Auth events at
`POST /client/webhook/messages`, performs the CRM customer lookup asynchronously,
uses the qualification engine, and posts text replies to one configured callback URL.

Run the isolated deployment-like smoke test:

```bash
bash test_mock_stack.sh
```

This builds and starts Redis, the client webhook, a dedicated RQ worker, and a mock
CRM/callback service under a separate Compose project. It sends a real HTTP event,
waits for the correlated callback, and removes the isolated stack afterward.

To inspect the services manually:

```bash
docker compose -p tvsm-rag-mock --profile mock up \
  --build redis mock-client client-webhook-mock mock-worker
```

The local webhook is then available on port `8004`, and mock CRM inspection is on
port `8003`. Values in `.env.mock` are test-only and must not be used in production.

For production, fill the `CLIENT_*` settings in `.env`, then start the dedicated
client profile with `docker compose --profile client up -d`. Keep `client-worker`
at one replica: its dedicated FIFO queue is what preserves webhook arrival order.
