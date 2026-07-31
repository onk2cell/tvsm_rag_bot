"""LLM provider factory — the "multi-model layer": the only file that
should need to change to add/swap a provider or tier.

get_llm("smart") returns the existing, production-proven grounded adapter
(raw google-genai SDK + Gemini File Search over the product KB) — unchanged
behavior, just re-exposed behind this factory.

get_llm("fast") returns a plain LangChain chat model, reserved for future
non-grounded calls (e.g. LLM-driven tool routing). Nothing in bot/graph.py
calls it yet — v1 keeps the main reply call off the LangChain chat-model
abstraction entirely, since langchain-google-genai does not support File
Search grounding together with bind_tools.
"""
from functools import lru_cache
from typing import Literal

from bot.config import FILE_SEARCH_STORE, GEMINI_API_KEY, MODEL_FAST, MODEL_SMART

Tier = Literal["fast", "smart"]


@lru_cache
def get_llm(tier: Tier = "smart"):
    if tier == "smart":
        from conversation_engine import GeminiLLMAdapter

        return GeminiLLMAdapter(MODEL_SMART, FILE_SEARCH_STORE)

    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=MODEL_FAST,
        google_api_key=GEMINI_API_KEY,
        temperature=0,
    )
