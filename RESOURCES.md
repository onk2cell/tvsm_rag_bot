# TVS Bot Ops Resources

## Knowledge

### Start here (lesson 1 path)

- [What is Redis?](https://redis.io/tutorials/what-is-redis/)
  Official overview of Redis as in-memory store / broker. Use for: mental model before keys/queues in this bot.
- [RQ: Simple job queues for Python](https://python-rq.org/)
  Primary RQ docs (Queue / Job / Worker). Use for: enqueue → worker → job; matches `client_webhook` / `client_worker`.
- [RQ documentation overview](https://python-rq.org/docs/)
  Jobs, queues, retries. Use for: `Retry` and queue names (`CLIENT_QUEUE_NAME`).
- [Docker Compose Quickstart](https://docs.docker.com/compose/gettingstarted/)
  Official tutorial: Python app + Redis in Compose. Use for: services talking over a network (closest to this repo).
- [Docker Compose application model](https://docs.docker.com/compose/intro/compose-application-model/)
  Official model: services, networks, volumes. Use for: why webhook/worker/redis are separate containers.
- [Networking in Compose](https://docs.docker.com/compose/how-tos/networking)
  Service-name DNS on the default network. Use for: `REDIS_URL=redis://redis:6379` in this repo.

### Deeper / courses

- [Redis University — Get Started with Redis](https://university.redis.io/academy/)
  Official free Redis course (replaces old RU101). Use for: data types, TTL, commands you’ll see in dedupe/rate-limit.
- [Compose file reference](https://docs.docker.com/reference/compose-file/)
  Spec for `profiles`, `depends_on`, `env_file`. Use for: reading `compose.yaml` safely before deploy.
- [Redis docs (latest)](https://redis.io/docs/latest/)
  Command and data-type reference. Use for: `SET NX`, `INCR`, locks, TTLs as used in client code.
- [Repo: Client API and webhook guide](docs/CLIENT_API_AND_WEBHOOK_GUIDE.md)
  This project's inbound/outbound contracts. Use for: what "accepted" means and what the worker owes CRM.

### Video (supplementary)

- [TechWorld with Nana — Docker Compose tutorial](https://www.youtube.com/watch?v=SXwC9fSwct8)
  Clear multi-service Compose walkthrough. Use for: visual of services/networks after reading official Compose quickstart.
  Note: community video — prefer Docker docs when they disagree.

## Wisdom (Communities)

- [Redis Community Forum](https://forum.redis.io/)
  Official Redis forum (ops + data structures). Use for: persistence, memory, "is Redis down?" triage.
- [Docker Community Forums](https://forums.docker.com/)
  Docker Inc. forums. Use for: Compose networking / volume surprises in deploy.

## Gaps

- No single canonical "read AI-generated FastAPI+RQ code safely" guide — teach via this repo's seams instead.
- JAM CRM dispose/send API details live mainly in repo docs and Postman collection; treat vendor docs as secondary.
