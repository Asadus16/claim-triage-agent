"""Gemini client with record / replay.

LLM_MODE controls behavior:
  live    - call Gemini, no caching
  record  - call Gemini and cache the response keyed by a hash of the input
  replay  - never call the network; read the cached response (raises if missing)

Record/replay makes the test suite fast, free and deterministic, and lets the
n8n demo run without a live key. Only re-record when a prompt changes on purpose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.config import get_settings

CASSETTE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cassettes"


class ReplayMiss(RuntimeError):
    pass


def _key(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:20]


def _cassette(key: str) -> Path:
    return CASSETTE_DIR / f"{key}.json"


def _read_cassette(key: str) -> str | None:
    path = _cassette(key)
    if path.exists():
        return json.loads(path.read_text())["response"]
    return None


def _write_cassette(key: str, prompt: str, response: str) -> None:
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    _cassette(key).write_text(json.dumps({"prompt": prompt, "response": response}, indent=2))


def _call_gemini(prompt: str, model: str, api_key: str) -> str:
    import google.generativeai as genai  # imported lazily so replay needs no dep
    genai.configure(api_key=api_key)
    resp = genai.GenerativeModel(model).generate_content(prompt)
    return resp.text


def generate(prompt: str) -> str:
    s = get_settings()
    key = _key(prompt, s.gemini_model)

    if s.llm_mode == "replay":
        cached = _read_cassette(key)
        if cached is None:
            raise ReplayMiss(
                f"No cassette for key {key}. Run with LLM_MODE=record and a GEMINI_API_KEY first."
            )
        return cached

    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for live/record mode")

    response = _call_gemini(prompt, s.gemini_model, s.gemini_api_key)
    if s.llm_mode == "record":
        _write_cassette(key, prompt, response)
    return response
