"""Pydantic schemas at the HTTP boundary.

These validate incoming JSON and are converted into the framework-free domain
dataclasses via the shared parsers in app.golden, so there is one definition of
how a claim/policy dict becomes a domain object.
"""

from typing import Optional

from pydantic import BaseModel, Field


class PolicyIn(BaseModel):
    policy_number: str
    insured_name: str
    effective_date: str
    expiration_date: str
    territory: list[str] = []
    covered_perils: list[str] = []
    coverage_types: list[str] = []
    deductible: float = 0.0
    per_occurrence_limit: float = 0.0
    aggregate_limit: float = 0.0
    aggregate_used: float = 0.0
    sublimits: dict[str, float] = {}
    coinsurance: float = 0.0
    listed_drivers: list[str] = []
    listed_vehicles: list[str] = []
    exclusions: list[str] = []
    endorsements: list[str] = []
    premium_lapsed: bool = False
    cancelled_date: Optional[str] = None
    inception_history_months: int = 999


class DocumentIn(BaseModel):
    kind: str
    present: bool = True
    created_at: Optional[str] = None
    stated_date: Optional[str] = None
    sha256: Optional[str] = None
    font_anomaly: bool = False


class ClaimIn(BaseModel):
    claim_id: str
    policy_number: str
    loss_date: str
    reported_date: str
    peril: str
    claimant_name: str
    driver_name: str
    vehicle_id: str
    loss_location: str
    claimed_amount: float
    description: str = ""
    repair_estimate: Optional[float] = None
    documents: list[DocumentIn] = []
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
    extraction_confidence: float = 1.0


class DecideRequest(BaseModel):
    policy: PolicyIn
    claim: ClaimIn
    narrate: bool = False


class FromTextRequest(BaseModel):
    policy: PolicyIn
    claim_id: str
    policy_number: str
    loss_date: str
    reported_date: str
    vehicle_id: str
    loss_location: str = ""
    claim_text: str
    narrate: bool = True


class ExtractRequest(BaseModel):
    claim_text: str


class HumanDecisionRequest(BaseModel):
    action: str = Field(description="approve | override | escalate")
    note: str = ""
