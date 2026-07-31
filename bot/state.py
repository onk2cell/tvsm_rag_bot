"""Graph state — the bridge between a turn's inputs (from
conversation_engine.TurnInput, itself built from the Redis-persisted
session) and the LangGraph orchestration layer.

Deliberately holds `history`/`user_text` in the same shape
conversation_engine.build_contents() already expects, rather than
LangChain BaseMessage objects: v1's chatbot node calls the raw Gemini SDK
adapter directly (no bind_tools/ToolNode), so converting through
LangChain's message types would be pure ceremony with no functional
benefit. Revisit if/when a later phase adds LLM-driven tool calling via a
second, non-grounded model.

No LangGraph checkpointer is used for cross-turn persistence — RQ workers
are stateless per job, and RedisClientState already durably persists
session state (with the correct 4h TTL). `graph.invoke()` runs once per
turn with a fully-formed BotState built from TurnInput.
"""
from typing import Any, TypedDict


class BotState(TypedDict):
    config: dict[str, Any]
    language: str
    product_hint: str
    confirm_crm_dealer: bool
    history: list[dict[str, str]]
    user_text: str

    # populated by the chatbot node:
    reply_text: str
    captured: bool
    lead_profile: dict[str, Any] | None
    citations: list[str]
