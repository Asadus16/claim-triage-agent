"""Unit tests for the deterministic payout math."""

from datetime import date

from app.models import CoverageType, Peril, Policy, Claim
from app.rules.payout import compute_payout


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


def _claim(amount: float, peril: Peril = Peril.COLLISION) -> Claim:
    return Claim(
        claim_id="C", policy_number="P", loss_date=date(2026, 6, 1),
        reported_date=date(2026, 6, 2), peril=peril, claimant_name="A",
        driver_name="A", vehicle_id="V", loss_location="CA",
        claimed_amount=amount, description="x",
    )


def test_deductible_subtracted():
    assert compute_payout(_claim(2000), _policy()).payout == 1500.0


def test_below_deductible_is_zero():
    assert compute_payout(_claim(300), _policy()).payout == 0.0


def test_per_occurrence_cap():
    assert compute_payout(_claim(30000), _policy()).payout == 24500.0


def test_sublimit_caps_before_deductible():
    p = _policy(sublimits={"glass": 1000}, covered_perils=[Peril.GLASS],
                coverage_types=[CoverageType.GLASS])
    assert compute_payout(_claim(1500, Peril.GLASS), p).payout == 500.0


def test_coinsurance_applied_after_deductible():
    p = _policy(coinsurance=0.2)
    # (5000 - 500) * 0.8 = 3600
    assert compute_payout(_claim(5000), p).payout == 3600.0


def test_aggregate_remaining_caps_payout():
    p = _policy(aggregate_used=49000)  # 1000 remaining
    assert compute_payout(_claim(5000), p).payout == 1000.0


def test_steps_are_recorded():
    breakdown = compute_payout(_claim(2000), _policy())
    assert breakdown.steps and "final payout" in breakdown.steps[-1]
