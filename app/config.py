"""Runtime settings, read from the environment (.env supported)."""

from __future__ import annotations

import os
from functools import lru_cache

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional in production
    pass


class Settings:
    def __init__(self) -> None:
        # Shared-secret used by n8n to authenticate to this service.
        self.service_api_key: str = os.getenv("SERVICE_API_KEY", "dev-key-change-me")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        # live = call Gemini; record = call and cache; replay = read cache only.
        self.llm_mode: str = os.getenv("LLM_MODE", "replay")
        self.prompt_version: str = os.getenv("PROMPT_VERSION", "v1")
        self.claims_db: str = os.getenv("CLAIMS_DB", "data/claims.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
