"""Narrate a decision, with a hard guardrail that the model cannot invent numbers.

Pattern: numbers come from code, not the model. After the LLM writes its
explanation we extract every number from it and confirm each one already appears
in the decision produced by the deterministic engine. Any stray number is a
guardrail violation; the narration is rejected and retried, then falls back to a
templated explanation that uses only engine numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from app.llm import gemini
from app.models import Decision

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _enum_safe(obj):
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"not serializable: {type(obj)}")


def _numbers_in(text: str) -> set[float]:
    out: set[float] = set()
    for tok in _NUMBER_RE.findall(text):
        tok = tok.rstrip(".").replace(",", "")
        if tok in ("", "-"):
            continue
        try:
            out.add(round(float(tok), 2))
        except ValueError:
            continue
    return out


def allowed_numbers(decision: Decision) -> set[float]:
    """Every number the engine already produced is fair game to cite."""
    return _numbers_in(json.dumps(asdict(decision), default=_enum_safe))


def find_violations(narrative: str, decision: Decision) -> list[float]:
    allowed = allowed_numbers(decision)
    return [n for n in _numbers_in(narrative)
            if not any(abs(n - a) < 0.01 for a in allowed)]


def _template(decision: Decision) -> str:
    parts = [f"Recommendation: {decision.recommendation.value}."]
    if decision.payout:
        parts.append(f"Computed payout is {decision.payout.payout:.2f}.")
    if decision.reason_codes:
        parts.append("Reasons: " + ", ".join(decision.reason_codes[:6]) + ".")
    parts.append("A human reviewer must approve." if decision.requires_human
                 else "Eligible for straight-through processing.")
    return " ".join(parts)


def narrate(decision: Decision, max_retries: int = 1) -> tuple[str, bool]:
    """Returns (narrative, used_llm). Falls back to a safe template on violation."""
    prompt_tpl = (PROMPT_DIR / "narrate_v1.md").read_text()
    decision_json = json.dumps(asdict(decision), default=_enum_safe, indent=2)
    prompt = prompt_tpl.replace("{decision_json}", decision_json)

    for _ in range(max_retries + 1):
        try:
            text = gemini.generate(prompt)
        except Exception:
            break
        if not find_violations(text, decision):
            return text.strip(), True
    # Guardrail tripped or no LLM available: use engine-only text.
    return _template(decision), False
