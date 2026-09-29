"""Domain models for claim triage.

Deliberately plain dataclasses with no external dependencies: the deterministic
core (rules, payout, fraud) never imports a framework, so it can be unit tested
in isolation and reused outside the API. Pydantic lives only at the HTTP edge
(see app/schemas.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Peril(str, Enum):
    COLLISION = "collision"
    THEFT = "theft"
    VANDALISM = "vandalism"
    FIRE = "fire"
    FLOOD = "flood"
    HAIL = "hail"
    GLASS = "glass"
    LIABILITY = "liability"
    OTHER = "other"


class CoverageType(str, Enum):
    COLLISION = "collision"
    COMPREHENSIVE = "comprehensive"
    LIABILITY = "liability"
    GLASS = "glass"
    RENTAL = "rental"


class Recommendation(str, Enum):
    PAY = "pay"
    INVESTIGATE = "investigate"
    DENY = "deny"
    REFER = "refer"


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NA = "na"


class Severity(str, Enum):
    BLOCKING = "blocking"      # a fail here forces deny/refer
    MATERIAL = "material"      # a fail lowers confidence / may refer
    ADVISORY = "advisory"      # informational; does not block


@dataclass(frozen=True)
class Document:
    kind: str                       # e.g. "police_report", "estimate", "photo"
    present: bool = True
    created_at: date | None = None  # metadata timestamp, for date-mismatch checks
    stated_date: date | None = None # date the doc claims to describe
    sha256: str | None = None       # for duplicate/template detection
    font_anomaly: bool = False      # flagged by an upstream document check


@dataclass(frozen=True)
class Policy:
    policy_number: str
    insured_name: str
    effective_date: date
    expiration_date: date
    territory: list[str]                       # allowed regions/states
    covered_perils: list[Peril]
    coverage_types: list[CoverageType]
    deductible: float
    per_occurrence_limit: float
    aggregate_limit: float
    aggregate_used: float = 0.0                # already paid this term
    sublimits: dict[str, float] = field(default_factory=dict)  # by category
    coinsurance: float = 0.0                   # 0..1, insured's share above deductible
    listed_drivers: list[str] = field(default_factory=list)
    listed_vehicles: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)        # exclusion codes present
    endorsements: list[str] = field(default_factory=list)      # e.g. "flood_endorsement"
    premium_lapsed: bool = False
    cancelled_date: date | None = None
    inception_history_months: int = 999        # months policy has existed (for F rules)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    policy_number: str
    loss_date: date
    reported_date: date
    peril: Peril
    claimant_name: str
    driver_name: str
    vehicle_id: str
    loss_location: str                         # region/state code
    claimed_amount: float
    description: str
    repair_estimate: float | None = None
    documents: list[Document] = field(default_factory=list)
    prior_claims_12mo: int = 0
    prior_claims_other_carriers: int = 0
    attorney_retained_before_contact: bool = False
    driver_valid_license: bool = True
    driver_under_influence: bool = False
    business_use: bool = False
    racing: bool = False
    cancelled_inspections: int = 0
    address_changed_lt_6mo: bool = False
    recent_bankruptcy: bool = False
    coverage_increase_lt_90d: bool = False
    statement_contradiction: bool = False
    single_provider_routing: bool = False
    # confidence in the machine-extracted facts above (0..1); set by the LLM layer
    extraction_confidence: float = 1.0


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    category: str
    status: Status
    severity: Severity
    message: str
    clause_ref: str                # exact policy clause / manual section cited
    reason_code: str               # machine-readable, e.g. "COVERAGE_NOT_ACTIVE"


@dataclass(frozen=True)
class FraudSignal:
    indicator_id: str
    category: str                  # document | behavioral | financial
    triggered: bool
    weight: float
    evidence: str


@dataclass
class PayoutBreakdown:
    covered_loss: float
    deductible_applied: float
    coinsurance_applied: float
    sublimit_cap: float | None
    limit_cap: float | None
    aggregate_remaining: float
    payout: float
    steps: list[str] = field(default_factory=list)   # human-readable math trace


@dataclass
class Decision:
    claim_id: str
    recommendation: Recommendation
    confidence: float
    requires_human: bool
    payout: PayoutBreakdown | None
    reason_codes: list[str]
    rule_results: list[RuleResult]
    fraud_signals: list[FraudSignal]
    fraud_score: float
    stp_eligible: bool             # straight-through-processing candidate
    narrative: str = ""            # LLM explanation, filled at the edge; never numbers
    prompt_version: str | None = None
    audit_id: str | None = None
