# TVS WhatsApp qualification bot (JAM CRM)

WhatsApp bot for TVS passenger 3W lead qualification. Production traffic is
**JAM CRM webhook → Redis queue → client worker → JAM send + dispose**.

## Production services

```bash
docker compose --profile client up -d --build
```

- `client-webhook` — `POST /client/webhook/messages` (ports 8002 / 8004)
- `client-worker` — RQ worker (`CLIENT_QUEUE_NAME=client`)
- `redis` — queue + 4h session TTL

Configure `.env` with Gemini, `CLIENT_*` JAM URLs/API key, dealers data under `data/`.

Contracts: [`docs/CLIENT_API_AND_WEBHOOK_GUIDE.md`](docs/CLIENT_API_AND_WEBHOOK_GUIDE.md).

## Local lab (verify before deploy)

Runs the **same** webhook → worker path against a mock CRM + reply sink, with a
browser chat where you choose **mobile** and **CRM JSON**.

```bash
# Needs GEMINI_API_KEY + FILE_SEARCH_STORE in .env for real answers;
# .env.mock sets CLIENT_TEST_MODE=true (deterministic mock LLM) by default.
docker compose --profile lab up -d --build
```

Open **http://localhost:8003/mock/chat**

1. Pick a **preset** (returning EV MAX, unknown number, …) or edit CRM JSON  
2. Click **Save CRM for this mobile**  
3. Optionally **Reset session** (clears Redis `client:session:+91…` + replies)  
4. Chat — messages go through `lab-webhook` → `lab-worker` → mock replies  

```text
browser lab → lab-webhook → Redis → lab-worker
            → mock CRM lookup + mock replies → browser
```

Stop lab:

```bash
docker compose --profile lab down
```

Smoke (optional):

```bash
bash test_mock_stack.sh
```

## Core modules

| Module | Role |
|--------|------|
| `client_webhook.py` | Inbound JAM events |
| `client_worker.py` / `client_tasks.py` | Queue consumer |
| `client_processing.py` | Turn orchestration |
| `client_adapters.py` | CRM / send / dispose / Redis session |
| `conversation_engine.py` | Qualification + Gemini |
| `dealers.py` / `dispose.py` | Nearest dealer + CRM dispose |
| `mock_client.py` | Local CRM lab UI + fixtures |

## Setup (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill Gemini + JAM keys for prod-like runs
```

Unit tests:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Notes

- Session idle expiry is **4 hours** (`CLIENT_HISTORY_TTL_SEC`); fresh session always shows the language menu.
- Keep a **single** `client-worker` replica so webhook order is preserved per queue.
- Lab values in `.env.mock` are test-only — never use them in production.
