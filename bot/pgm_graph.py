"""Locate-nearest-PGM flow — LangGraph StateGraph for the location step.

The customer was asked for a WhatsApp location pin, a 6-digit pincode, or
the name of the place where they want to see a service centre. This graph
handles the typed reply:

    START ─┬─ has a pincode ─────────────────────────→ pincode
           ├─ not a place (filler, punctuation) ──────→ unclear
           └─ place name ──→ search_web (Gemini +   ─┬─ pincode found → pincode
                              Google Search)         ├─ NOT_FOUND     → not_found
                                                     └─ call failed   → lookup_failed

A location pin never reaches the graph: its coordinates are already exact
and client_processing handles it directly. Same discipline as bot/graph.py —
the graph only decides; the reply text, session writes and dispose stay in
client_processing._handle_pgm_turn.

The search callable is injected through RunnableConfig ("configurable" →
"search") so tests run the real graph against a fake, never the network.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from dealers import extract_pincode

log = logging.getLogger(__name__)

# What search_web is asked. One line back is all the parser needs, so the
# answer is capped well under search_web's default.
SEARCH_MAX_CHARS = 400
NOT_FOUND_TOKEN = "NOT_FOUND"


def search_query(place: str) -> str:
    return (
        "A customer in India typed this as the place where they want to find "
        f"a TVS service centre: {place!r}. What is the 6-digit Indian postal "
        "PIN code of that place? If it has several, give the main (GPO / "
        "head post office) one. Reply with only the PIN code followed by the "
        "place name, for example '411001 Pune'. If it is not a real place in "
        f"India, or you cannot find its PIN code, reply exactly {NOT_FOUND_TOKEN}."
    )


def default_search(query: str) -> str:
    from gemini_setup import search_web

    return search_web.invoke({"query": query, "max_chars": SEARCH_MAX_CHARS})


# A place name has letters (any script) and is more than a couple of
# characters; "ok", "?", "..." and bare non-pincode numbers are not worth a
# web search and are re-asked instead.
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def looks_like_place(text: str) -> bool:
    cleaned = (text or "").strip()
    return len(cleaned) >= 3 and bool(_HAS_LETTER_RE.search(cleaned))


class PgmLocationState(TypedDict):
    user_message: str
    search_result: str
    pincode: str
    result: str  # "pincode" | "not_found" | "unclear" | "lookup_failed"


def _route(state: PgmLocationState) -> str:
    text = state["user_message"] or ""
    if extract_pincode(text):
        return "typed_pincode"
    if not looks_like_place(text):
        return "unclear"
    return "search"


def _typed_pincode(state: PgmLocationState) -> dict:
    return {"pincode": extract_pincode(state["user_message"]), "result": "pincode"}


def _unclear(state: PgmLocationState) -> dict:
    return {"result": "unclear"}


def _search(state: PgmLocationState, config: RunnableConfig) -> dict:
    search: Callable[[str], str] = (config.get("configurable") or {}).get(
        "search"
    ) or default_search
    place = state["user_message"].strip()
    try:
        answer = search(search_query(place)) or ""
    except Exception:
        # Quota, network, missing key: say so and ask for a pincode instead
        # of pretending the place does not exist.
        log.exception("pgm pincode search failed for %r", place)
        return {"search_result": "", "result": "lookup_failed"}
    if NOT_FOUND_TOKEN in answer.upper():
        return {"search_result": answer, "result": "not_found"}
    pincode = extract_pincode(answer)
    if not pincode:
        return {"search_result": answer, "result": "not_found"}
    return {"search_result": answer, "pincode": pincode, "result": "pincode"}


_builder = StateGraph(PgmLocationState)
_builder.add_node("typed_pincode", _typed_pincode)
_builder.add_node("unclear", _unclear)
_builder.add_node("search", _search)
_builder.add_conditional_edges(START, _route, ["typed_pincode", "unclear", "search"])
_builder.add_edge("typed_pincode", END)
_builder.add_edge("unclear", END)
_builder.add_edge("search", END)

pgm_location_graph = _builder.compile()


@dataclass(frozen=True)
class PgmLocation:
    result: str
    pincode: str = ""
    search_result: str = ""


def resolve_pgm_location(
    user_message: str, *, search: Callable[[str], str] | None = None
) -> PgmLocation:
    """Turn a typed PGM-flow reply into a pincode, or say why not."""
    config: RunnableConfig = {"configurable": {"search": search}} if search else {}
    state = pgm_location_graph.invoke(
        {
            "user_message": user_message or "",
            "search_result": "",
            "pincode": "",
            "result": "unclear",
        },
        config=config,
    )
    return PgmLocation(
        result=state["result"],
        pincode=state.get("pincode") or "",
        search_result=state.get("search_result") or "",
    )
