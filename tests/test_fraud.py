"""Unit tests for deterministic fraud scoring."""

from datetime import date

from app.models import CoverageType, Peril, Policy, Claim, Document
from app.rules.fraud import band, score_fraud, HIGH_BAND, LOW_BAND


def _policy(**overrides) -> Policy:
    base = dict(
        policy_number="P", insured_name="A",
        effective_date=date(2026, 1, 1), expiration_date=date(2027, 1, 1),
        territory=["CA"], covered_perils=[Peril.COLLISION],
        coverage_types=[CoverageType.COLLISION],
        deductible=500, per_occurrence_limit=25000, aggregate_limit=50000,
    )
    base.update(overrides)
    return Policy(**base)


def _claim(**overrides) -> Claim:
    base = dict(
        claim_id="C", policy_number="P", loss_date=date(2026, 6, 1),
        reported_date=date(2026, 6, 2), peril=Peril.COLLISION, claimant_name="A",
        driver_name="A", vehicle_id="V", loss_location="CA",
        claimed_amount=1850, description="collision at a stop sign",
    )
    base.update(overrides)
    return Claim(**base)


def test_clean_claim_is_low_band():
    score, signals = score_fraud(_claim(), _policy())
    assert band(score) == "low"
    assert all(not s.triggered for s in signals)


def test_multiple_strong_indicators_reach_high_band():
    claim = _claim(
        attorney_retained_before_contact=True,
        statement_contradiction=True,
        documents=[Document(kind="estimate", font_anomaly=True)],
    )
    score, _ = score_fraud(claim, _policy(inception_history_months=2))
    assert score >= HIGH_BAND
    assert band(score) == "high"


def test_score_is_deterministic():
    claim = _claim(recent_bankruptcy=True)
    a, _ = score_fraud(claim, _policy())
    b, _ = score_fraud(claim, _policy())
    assert a == b


def test_every_signal_has_evidence():
    _, signals = score_fraud(_claim(), _policy())
    assert all(s.evidence for s in signals)


def test_band_thresholds():
    assert band(0.0) == "low"
    assert band(LOW_BAND) == "medium"
    assert band(HIGH_BAND) == "high"
