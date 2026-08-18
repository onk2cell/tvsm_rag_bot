"""Redis key formats shared between the worker and the admin panel.

Kept in its own module on purpose. The admin app needs the session key to
reset a stuck customer, but importing it from ``client_adapters`` would drag
the whole conversation engine (``client_processing``) into the admin
container's import graph. Duplicating the literal instead would let the two
copies drift apart silently — the reset would quietly stop working.
"""
from __future__ import annotations


def client_session_key(mobile: str) -> str:
    """Redis key holding one WhatsApp customer's live session."""
    return f"client:session:{mobile}"
