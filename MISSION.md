# Mission: Own this bot safely

## Why
You maintain the TVS qualification WhatsApp bot and need to ship changes without breaking production. Much of the code was AI-assisted; you need a durable mental model of Docker, Redis, and the real seams in this repo so you can review, debug, and change it with confidence.

## Success looks like
- Trace one inbound client message from webhook → Redis/RQ → worker → reply/dispose, naming the process that does each step
- Read `compose.yaml` and know which services must be up for a change you are shipping
- Spot when AI-generated code is putting slow work in the wrong process (webhook vs worker) or inventing the wrong Redis key/role
- Make a small, safe change (config, flow, adapter) and know which tests/mock stack prove it

## Constraints
- Learn against this codebase first (not generic Docker/Redis tutorials in isolation)
- Prefer short lessons with retrieval practice over long lectures
- Time is limited: one tight concept per session

## Out of scope
- Deep LLM/prompt engineering theory beyond how this bot uses Gemini File Search
- Rewriting the stack (Celery, Kubernetes, etc.) unless a real shipping need appears
- Meta/legacy WhatsApp open-Q&A path (`app.py`) until the client path is solid
