"""Turn a free-text claim narrative into validated structured facts.

The LLM only extracts; it never decides or computes. Output is validated against
a strict schema — if it does not parse or validate, extraction fails closed
(low confidence, routed to a human) rather than passing junk to the engine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.llm import gemini

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


class ExtractedClaim(BaseModel):
    peril: str = "other"
    claimant_name: str = ""
    driver_name: str = ""
    loss_location: str = ""
    claimed_amount: float = 0.0
    repair_estimate: Optional[float] = None
    description: str = ""
    driver_under_influence: bool = False
    business_use: bool = False
    racing: bool = False
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def _load_prompt() -> str:
    version = get_settings().prompt_version
    return (PROMPT_DIR / f"extract_{version}.md").read_text()


def _loads_lenient(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def extract_claim(claim_text: str) -> ExtractedClaim:
    prompt = _load_prompt().replace("{claim_text}", claim_text)
    raw = gemini.generate(prompt)
    try:
        data = _loads_lenient(raw)
        return ExtractedClaim(**data)
    except (json.JSONDecodeError, ValidationError):
        # Fail closed: unusable extraction becomes a low-confidence claim that the
        # engine will route to a human rather than auto-deciding on bad facts.
        return ExtractedClaim(description=claim_text[:200], extraction_confidence=0.0)
