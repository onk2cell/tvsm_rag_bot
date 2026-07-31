"""LangGraphEngine — a drop-in-shaped replacement for
conversation_engine.ConversationEngine, same handle_turn(TurnInput) ->
TurnOutput contract, so it can be swapped in behind a flag in a later
phase without touching client_processing.py's call site.

Not wired into client_tasks.build_processor yet — see the migration plan.
"""
from __future__ import annotations

from conversation_engine import LANGUAGE_SELECTED_TRIGGER, TurnInput, TurnOutput
from bot.graph import graph
from bot.state import BotState


class LangGraphEngine:
    """Qualification-first conversation module, backed by a LangGraph
    StateGraph instead of a single inline LLM call. Same seam as
    ConversationEngine — stateless per call, session state stays owned by
    the caller (client_processing.ClientMessageProcessor / RedisClientState)."""

    def __init__(self, *, config_store, lead_writer=None):
        self._config_store = config_store
        self._lead_writer = lead_writer

    def handle_turn(self, turn: TurnInput) -> TurnOutput:
        config = self._config_store.get()
        user_text = (turn.message or "").strip() or LANGUAGE_SELECTED_TRIGGER

        state: BotState = {
            "config": config,
            "language": turn.language,
            "product_hint": turn.product_hint,
            "confirm_crm_dealer": turn.confirm_crm_dealer,
            "history": turn.history,
            "user_text": user_text,
            "reply_text": "",
            "captured": False,
            "lead_profile": None,
            "citations": [],
        }
        result = graph.invoke(state)

        profile = result["lead_profile"]
        captured = False
        if profile and self._lead_writer is not None:
            self._lead_writer.append(
                channel=turn.channel,
                source=turn.source,
                session=turn.session_id,
                language=turn.language,
                profile=profile,
            )
            captured = True

        return TurnOutput(
            reply_text=result["reply_text"],
            captured=captured,
            profile=profile,
            citations=list(result.get("citations") or []),
        )


def make_langgraph_engine(
    *,
    config_store=None,
    leads_path: str | None = None,
) -> LangGraphEngine:
    """Build a production LangGraphEngine wired to admin config and CSV
    leads — same factory shape as conversation_engine.make_engine, for
    parity when this gets flag-switched into client_tasks.build_processor."""
    from pathlib import Path

    import config as app_config
    from admin_config import get_store
    from leads import LeadWriter

    store = config_store or get_store()
    writer = LeadWriter(Path(leads_path or app_config.LEADS_CSV_PATH), store)
    return LangGraphEngine(config_store=store, lead_writer=writer)
