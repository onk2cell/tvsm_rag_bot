"""Redis-backed conversation memory, dedup, and rate limiting (all keyed by sender)."""
import json
import time

from redis import Redis

import config

r = Redis.from_url(config.REDIS_URL, decode_responses=True)


# ---------- conversation history ----------
def get_history(sender: str) -> list:
    raw = r.get(f"hist:{sender}")
    return json.loads(raw) if raw else []


def append_turn(sender: str, role: str, text: str) -> None:
    hist = get_history(sender)
    hist.append({"role": role, "text": text})
    hist = hist[-config.MAX_HISTORY_TURNS:]               # keep only the last N turns
    r.set(f"hist:{sender}", json.dumps(hist), ex=config.HISTORY_TTL_SEC)


def clear_history(sender: str) -> None:
    r.delete(f"hist:{sender}")


# ---------- dedup (Meta may redeliver the same webhook) ----------
def already_processed(message_id: str) -> bool:
    # SET NX returns True only the first time we see this id; not added => duplicate
    added = r.set(f"seen:{message_id}", "1", nx=True, ex=3600)
    return not added


# ---------- per-user rate limit ----------
def over_rate_limit(sender: str) -> bool:
    key = f"rate:{sender}:{int(time.time() // 60)}"       # one bucket per minute
    count = r.incr(key)
    if count == 1:
        r.expire(key, 60)
    return count > config.RATE_LIMIT_PER_MIN
