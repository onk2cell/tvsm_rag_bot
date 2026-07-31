"""Bot LLM settings — thin re-export of the single source of truth in the
top-level config.py. Deliberately not a second settings system: config.py
already loads .env and is validated by client_tasks.validate_worker_config(),
so introducing pydantic-settings here would just create a second place the
same Gemini key/model could drift out of sync.
"""
import os

import config as _config

GEMINI_API_KEY = _config.GEMINI_API_KEY
FILE_SEARCH_STORE = _config.FILE_SEARCH_STORE
MODEL_SMART = _config.MODEL

# No separate "fast" Gemini model is configured in production yet — default
# to the same model, override via GEMINI_MODEL_FAST when one is needed
# (e.g. a future non-grounded classifier/tool-routing call).
MODEL_FAST = os.environ.get("GEMINI_MODEL_FAST", _config.MODEL)
