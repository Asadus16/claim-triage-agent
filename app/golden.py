"""Golden-sample loader and regression runner.

The golden set lives as plain JSON (data/golden/cases.json) so a claims manager
can read and extend it without touching code. This module parses a case into the
domain objects, runs the deterministic engine, and compares the result to the
expected outcome. The same runner backs both the pytest regression test and any
CI gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.models import Claim, CoverageType, Document, Peril, Policy
from app.rules.engine import decide

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "data" / "golden" / "cases.json"


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def parse_policy(raw: dict[str, Any]) -> Policy:
    return Policy(
        policy_number=raw["policy_number"],
        insured_name=raw["insured_name"],
        effective_date=_d(raw["effective_date"]),
        expiration_date=_d(raw["expiration_date"]),
        territory=list(raw.get("territory", [])),
        covered_perils=[Peril(p) for p in raw.get("covered_perils", [])],
        coverage_types=[CoverageType(c) for c in raw.get("coverage_types", [])],
        deductible=float(raw.get("deductible", 0.0)),
        per_occurrence_limit=float(raw.get("per_occurrence_limit", 0.0)),
        aggregate_limit=float(raw.get("aggregate_limit", 0.0)),
        aggregate_used=float(raw.get("aggregate_used", 0.0)),
        sublimits={k: float(v) for k, v in raw.get("sublimits", {}).items()},
        coinsurance=float(raw.get("coinsurance", 0.0)),
        listed_drivers=list(raw.get("listed_drivers", [])),
        listed_vehicles=list(raw.get("listed_vehicles", [])),
        exclusions=list(raw.get("exclusions", [])),
        endorsements=list(raw.get("endorsements", [])),
        premium_lapsed=bool(raw.get("premium_lapsed", False)),
        cancelled_date=_d(raw.get("cancelled_date")),
        inception_history_months=int(raw.get("inception_history_months", 999)),
    )


def parse_claim(raw: dict[str, Any]) -> Claim:
    docs = [
        Document(
            kind=d["kind"],
            present=bool(d.get("present", True)),
            created_at=_d(d.get("created_at")),
            stated_date=_d(d.get("stated_date")),
            sha256=d.get("sha256"),
            font_anomaly=bool(d.get("font_anomaly", False)),
        )
        for d in raw.get("documents", [])
    ]
    return Claim(
        claim_id=raw["claim_id"],
        policy_number=raw["policy_number"],
        loss_date=_d(raw["loss_date"]),
        reported_date=_d(raw["reported_date"]),
        peril=Peril(raw["peril"]),
        claimant_name=raw["claimant_name"],
        driver_name=raw["driver_name"],
        vehicle_id=raw["vehicle_id"],
        loss_location=raw["loss_location"],
        claimed_amount=float(raw["claimed_amount"]),
        description=raw.get("description", ""),
        repair_estimate=(float(raw["repair_estimate"])
                         if raw.get("repair_estimate") is not None else None),
        documents=docs,
        prior_claims_12mo=int(raw.get("prior_claims_12mo", 0)),
        prior_claims_other_carriers=int(raw.get("prior_claims_other_carriers", 0)),
        attorney_retained_before_contact=bool(raw.get("attorney_retained_before_contact", False)),
        driver_valid_license=bool(raw.get("driver_valid_license", True)),
        driver_under_influence=bool(raw.get("driver_under_influence", False)),
        business_use=bool(raw.get("business_use", False)),
        racing=bool(raw.get("racing", False)),
        cancelled_inspections=int(raw.get("cancelled_inspections", 0)),
        address_changed_lt_6mo=bool(raw.get("address_changed_lt_6mo", False)),
        recent_bankruptcy=bool(raw.get("recent_bankruptcy", False)),
        coverage_increase_lt_90d=bool(raw.get("coverage_increase_lt_90d", False)),
        statement_contradiction=bool(raw.get("statement_contradiction", False)),
        single_provider_routing=bool(raw.get("single_provider_routing", False)),
        extraction_confidence=float(raw.get("extraction_confidence", 1.0)),
    )


@dataclass
class CaseResult:
    name: str
    passed: bool
    failures: list[str]


def load_cases(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def check_case(case: dict[str, Any]) -> CaseResult:
    policy = parse_policy(case["policy"])
    claim = parse_claim(case["claim"])
    decision = decide(claim, policy)
    expect = case["expect"]
    failures: list[str] = []

    if "recommendation" in expect and decision.recommendation.value != expect["recommendation"]:
        failures.append(
            f"recommendation: got {decision.recommendation.value}, "
            f"expected {expect['recommendation']}")

    if "stp_eligible" in expect and decision.stp_eligible != expect["stp_eligible"]:
        failures.append(f"stp_eligible: got {decision.stp_eligible}, expected {expect['stp_eligible']}")

    if "payout" in expect:
        got = decision.payout.payout if decision.payout else None
        if got != expect["payout"]:
            failures.append(f"payout: got {got}, expected {expect['payout']}")

    for code in expect.get("must_include_reason_codes", []):
        if code not in decision.reason_codes:
            failures.append(f"missing reason code {code}")

    for code in expect.get("must_not_include_reason_codes", []):
        if code in decision.reason_codes:
            failures.append(f"unexpected reason code {code}")

    if "fraud_band" in expect:
        from app.rules.fraud import band
        got_band = band(decision.fraud_score)
        if got_band != expect["fraud_band"]:
            failures.append(f"fraud_band: got {got_band}, expected {expect['fraud_band']}")

    return CaseResult(name=case["name"], passed=not failures, failures=failures)


def run_all(path: Path = GOLDEN_PATH) -> list[CaseResult]:
    return [check_case(c) for c in load_cases(path)]
