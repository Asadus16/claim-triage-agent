"""Weighted SIU fraud scoring.

The F-series rules surface individual red flags; this module assigns each a
weight and combines them into a calibrated 0..1 score plus a band. The score is
fully deterministic and explainable: every point traces to a named indicator
with its evidence. The LLM never sets this score.
"""

from __future__ import annotations

from app.models import Claim, FraudSignal, Policy

# indicator_id -> (category, weight, human evidence template, predicate)
_INDICATORS = [
    ("F01", "behavioral", 0.15, "loss within 90 days of inception or a coverage increase",
     lambda c, p: p.inception_history_months <= 3 or c.coverage_increase_lt_90d),
    ("F02", "behavioral", 0.08, "reporting delayed beyond 30 days",
     lambda c, p: (c.reported_date - c.loss_date).days > 30),
    ("F03", "behavioral", 0.15, "attorney/public adjuster retained before first contact",
     lambda c, p: c.attorney_retained_before_contact),
    ("F04", "behavioral", 0.12, "elevated prior-claim history across carriers",
     lambda c, p: c.prior_claims_other_carriers >= 3),
    ("F05", "financial", 0.06, "suspiciously round claimed amount",
     lambda c, p: c.claimed_amount >= 1000 and c.claimed_amount % 1000 == 0),
    ("F06", "document", 0.18, "document created before the date it describes",
     lambda c, p: any(d.created_at and d.stated_date and d.created_at < d.stated_date
                      for d in c.documents)),
    ("F07", "document", 0.15, "font/template anomaly on a document",
     lambda c, p: any(d.font_anomaly for d in c.documents)),
    ("F08", "behavioral", 0.12, "inspection/EUO avoidance (cancelled appointments)",
     lambda c, p: c.cancelled_inspections >= 2),
    ("F09", "financial", 0.10, "recent bankruptcy / financial distress",
     lambda c, p: c.recent_bankruptcy),
    ("F10", "behavioral", 0.06, "address/employer changed within 6 months",
     lambda c, p: c.address_changed_lt_6mo),
    ("F11", "behavioral", 0.14, "contradictions in the insured's statements",
     lambda c, p: c.statement_contradiction),
    ("F12", "financial", 0.10, "single-provider routing to one repair shop",
     lambda c, p: c.single_provider_routing),
]

# Sum of weights at which the score saturates to 1.0. Tuned so that ~3 strong
# indicators push a claim into the high band. Calibrate against the golden set.
_SATURATION = 0.60

LOW_BAND = 0.30
HIGH_BAND = 0.60


def score_fraud(claim: Claim, policy: Policy) -> tuple[float, list[FraudSignal]]:
    signals: list[FraudSignal] = []
    total = 0.0
    for ind_id, category, weight, evidence, predicate in _INDICATORS:
        triggered = bool(predicate(claim, policy))
        if triggered:
            total += weight
        signals.append(FraudSignal(
            indicator_id=ind_id, category=category, triggered=triggered,
            weight=weight, evidence=evidence,
        ))
    score = round(min(1.0, total / _SATURATION), 4)
    return score, signals


def band(score: float) -> str:
    if score >= HIGH_BAND:
        return "high"
    if score >= LOW_BAND:
        return "medium"
    return "low"
