"""The 'numbers from code, not the model' guardrail."""

from datetime import date

from app.llm.narrate import find_violations, allowed_numbers
from app.models import CoverageType, Peril, Policy, Claim
from app.rules.engine import decide


def _decision():
    policy = Policy(
        policy_number="P", insured_name="A",
        effective_date=date(2026, 1, 1), expiration_date=date(2027, 1, 1),
        territory=["CA"], covered_perils=[Peril.COLLISION],
        coverage_types=[CoverageType.COLLISION],
        deductible=500, per_occurrence_limit=25000, aggregate_limit=50000,
    )
    claim = Claim(
        claim_id="C", policy_number="P", loss_date=date(2026, 6, 1),
        reported_date=date(2026, 6, 2), peril=Peril.COLLISION, claimant_name="A",
        driver_name="A", vehicle_id="V", loss_location="CA",
        claimed_amount=2000, repair_estimate=2000, description="collision",
    )
    return decide(claim, policy)


def test_payout_number_is_allowed():
    d = _decision()  # payout 1500
    assert 1500.0 in allowed_numbers(d)
    assert find_violations("The payout is 1500.00 after the deductible.", d) == []


def test_invented_number_is_flagged():
    d = _decision()
    violations = find_violations("The payout is 9999 dollars.", d)
    assert 9999.0 in violations


def test_reason_code_numbers_do_not_false_positive():
    d = _decision()
    # 500 (deductible) appears in the engine output, so citing it is fine.
    assert find_violations("A deductible of 500 was applied.", d) == []
