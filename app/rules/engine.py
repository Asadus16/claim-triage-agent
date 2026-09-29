"""Deterministic decision engine.

Runs the rule catalog, computes the payout and the fraud score, then routes to
a recommendation. The routing is transparent and rule-driven; the LLM's only
job elsewhere is to extract facts and narrate this result, never to decide it.
"""

from __future__ import annotations

from app.models import (
    Claim,
    Decision,
    Policy,
    Recommendation,
    RuleResult,
    Severity,
    Status,
)
from app.rules import fraud
from app.rules.catalog import RULES
from app.rules.payout import compute_payout

# Routing thresholds. Kept as named constants so they are auditable and tunable
# against the golden set rather than buried in logic.
STP_MAX_PAYOUT = 2500.0
STP_MIN_CONFIDENCE = 0.85
ABSTAIN_BELOW = 0.55


def run_rules(claim: Claim, policy: Policy) -> list[RuleResult]:
    results: list[RuleResult] = []
    for rule in RULES:
        status, message = rule.fn(claim, policy)
        results.append(RuleResult(
            rule_id=rule.rule_id,
            category=rule.category,
            status=status,
            severity=rule.severity,
            message=message or rule.description,
            clause_ref=rule.clause_ref,
            reason_code=rule.reason_code if status is not Status.PASS else "OK",
        ))
    return results


def _confidence(extraction_confidence: float, warns: int, blocking_fail: bool) -> float:
    if blocking_fail:
        # A blocking rule failed deterministically; uncertainty is only in the
        # extracted facts, not in the rule itself.
        return round(max(0.0, min(1.0, extraction_confidence)), 4)
    penalty = 0.04 * warns
    return round(max(0.0, min(1.0, extraction_confidence - penalty)), 4)


def decide(claim: Claim, policy: Policy) -> Decision:
    results = run_rules(claim, policy)

    blocking_fails = [r for r in results
                      if r.status is Status.FAIL and r.severity is Severity.BLOCKING]
    warns = [r for r in results if r.status is Status.WARN]

    fraud_score, fraud_signals = fraud.score_fraud(claim, policy)
    fraud_band = fraud.band(fraud_score)

    payout = compute_payout(claim, policy)

    reason_codes: list[str] = [r.reason_code for r in results if r.status is not Status.PASS]
    reason_codes.append(f"FRAUD_{fraud_band.upper()}")

    confidence = _confidence(claim.extraction_confidence, len(warns), bool(blocking_fails))

    # Routing, in priority order.
    if blocking_fails:
        rec = Recommendation.DENY
        payout_out = None
    elif fraud_band == "high":
        rec = Recommendation.INVESTIGATE
        payout_out = payout
    elif confidence < ABSTAIN_BELOW:
        rec = Recommendation.REFER
        payout_out = payout
    else:
        rec = Recommendation.PAY
        payout_out = payout

    # Straight-through payment is blocked by any blocking/material flag, but an
    # advisory note (e.g. a round claimed amount) does not by itself stop it.
    stp_blocking_flag = any(
        r.status in (Status.FAIL, Status.WARN)
        and r.severity in (Severity.BLOCKING, Severity.MATERIAL)
        for r in results
    )
    stp_eligible = (
        rec is Recommendation.PAY
        and fraud_score < fraud.LOW_BAND
        and not stp_blocking_flag
        and confidence >= STP_MIN_CONFIDENCE
        and payout.payout <= STP_MAX_PAYOUT
    )

    # Human decides on everything except a clean straight-through payment.
    requires_human = not stp_eligible

    return Decision(
        claim_id=claim.claim_id,
        recommendation=rec,
        confidence=confidence,
        requires_human=requires_human,
        payout=payout_out,
        reason_codes=reason_codes,
        rule_results=results,
        fraud_signals=fraud_signals,
        fraud_score=fraud_score,
        stp_eligible=stp_eligible,
    )
