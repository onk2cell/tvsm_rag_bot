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

# Classifier tier: small structured-output calls (location, language switch,
# brochure intent) where the cheapest model is enough. Defaults to the same
# model as MODEL_SMART so a single GEMINI_MODEL change moves both; set
# GEMINI_MODEL_FAST to split the tiers.
MODEL_FAST = os.environ.get("GEMINI_MODEL_FAST", _config.MODEL)
