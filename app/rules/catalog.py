"""The rule catalog: 53 deterministic claim-adjudication rules a client can read.

Each rule is a small pure function of (claim, policy). No LLM, no randomness.
The engine (engine.py) runs them in order and turns each into a RuleResult with
a machine-readable reason code and a citation to the policy clause it enforces.

Categories:
  C  coverage / eligibility        X  exclusions
  L  limits & quantum              D  documentation / administrative
  F  fraud red-flag (SIU)          -- deeper weighted scoring lives in fraud.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.models import Claim, CoverageType, Peril, Policy, Severity, Status

# A rule returns its status plus an optional message override.
RuleFn = Callable[[Claim, Policy], "tuple[Status, str]"]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    severity: Severity
    description: str
    clause_ref: str
    reason_code: str   # emitted when the rule does not PASS
    fn: RuleFn


def _ok() -> "tuple[Status, str]":
    return (Status.PASS, "")


# Which coverage type a peril requires, for rule C05.
_PERIL_COVERAGE = {
    Peril.COLLISION: CoverageType.COLLISION,
    Peril.THEFT: CoverageType.COMPREHENSIVE,
    Peril.VANDALISM: CoverageType.COMPREHENSIVE,
    Peril.FIRE: CoverageType.COMPREHENSIVE,
    Peril.FLOOD: CoverageType.COMPREHENSIVE,
    Peril.HAIL: CoverageType.COMPREHENSIVE,
    Peril.GLASS: CoverageType.GLASS,
    Peril.LIABILITY: CoverageType.LIABILITY,
}


# ---------------------------------------------------------------------------
# C - Coverage / eligibility
# ---------------------------------------------------------------------------

def c01(c: Claim, p: Policy):
    return _ok() if p.policy_number == c.policy_number else (
        Status.FAIL, "Claim policy number does not match the policy on file")

def c02(c: Claim, p: Policy):
    active = p.effective_date <= c.loss_date <= p.expiration_date
    return _ok() if active else (Status.FAIL, "Loss date is outside the policy term")

def c03(c: Claim, p: Policy):
    return (Status.FAIL, "Premium lapsed as of the loss date") if p.premium_lapsed else _ok()

def c04(c: Claim, p: Policy):
    return _ok() if c.peril in p.covered_perils else (
        Status.FAIL, f"Peril '{c.peril.value}' is not a covered peril")

def c05(c: Claim, p: Policy):
    needed = _PERIL_COVERAGE.get(c.peril)
    if needed is None:
        return (Status.WARN, "No coverage mapping for this peril; refer")
    return _ok() if needed in p.coverage_types else (
        Status.FAIL, f"Policy lacks {needed.value} coverage required for this peril")

def c06(c: Claim, p: Policy):
    return _ok() if c.claimant_name.strip().lower() == p.insured_name.strip().lower() else (
        Status.WARN, "Claimant is not the named insured; verify permission")

def c07(c: Claim, p: Policy):
    if not p.listed_drivers:
        return _ok()
    return _ok() if c.driver_name in p.listed_drivers else (
        Status.FAIL, "Driver is not a listed or permitted driver")

def c08(c: Claim, p: Policy):
    if not p.listed_vehicles:
        return _ok()
    return _ok() if c.vehicle_id in p.listed_vehicles else (
        Status.FAIL, "Vehicle is not listed on the policy")

def c09(c: Claim, p: Policy):
    if not p.territory:
        return _ok()
    return _ok() if c.loss_location in p.territory else (
        Status.FAIL, "Loss location is outside the covered territory")

def c10(c: Claim, p: Policy):
    days = (c.reported_date - c.loss_date).days
    return _ok() if days <= 60 else (Status.WARN, f"Late notice: reported {days} days after loss")

def c11(c: Claim, p: Policy):
    return _ok() if c.loss_date >= p.effective_date else (
        Status.FAIL, "Loss predates policy inception")

def c12(c: Claim, p: Policy):
    if p.cancelled_date and c.loss_date > p.cancelled_date:
        return (Status.FAIL, "Loss occurred after policy cancellation")
    return _ok()


# ---------------------------------------------------------------------------
# X - Exclusions
# ---------------------------------------------------------------------------

def _excluded(p: Policy, code: str) -> bool:
    return code in p.exclusions

def x01(c: Claim, p: Policy):
    return (Status.FAIL, "Wear and tear / mechanical breakdown is excluded") \
        if _excluded(p, "wear_and_tear") and "wear" in c.description.lower() else _ok()

def x02(c: Claim, p: Policy):
    return (Status.FAIL, "Intentional or fraudulent act is excluded") \
        if "intentional" in c.description.lower() else _ok()

def x03(c: Claim, p: Policy):
    if c.peril == Peril.FLOOD and "flood_endorsement" not in p.endorsements:
        return (Status.FAIL, "Flood / earth movement excluded without endorsement")
    return _ok()

def x04(c: Claim, p: Policy):
    return (Status.FAIL, "Business / commercial use of a personal auto is excluded") \
        if c.business_use and _excluded(p, "business_use") else _ok()

def x05(c: Claim, p: Policy):
    return (Status.FAIL, "Racing / speed contest is excluded") if c.racing else _ok()

def x06(c: Claim, p: Policy):
    return (Status.FAIL, "Loss while under the influence is excluded") \
        if c.driver_under_influence else _ok()

def x07(c: Claim, p: Policy):
    if p.listed_drivers and c.driver_name not in p.listed_drivers and _excluded(p, "unlisted_driver"):
        return (Status.FAIL, "Unlisted driver exclusion applies")
    return _ok()

def x08(c: Claim, p: Policy):
    d = c.description.lower()
    return (Status.FAIL, "War / terrorism / nuclear exclusion applies") \
        if any(t in d for t in ("war", "terrorism", "nuclear")) else _ok()

def x09(c: Claim, p: Policy):
    return (Status.WARN, "Possible damage from lack of maintenance; verify") \
        if "neglect" in c.description.lower() or "maintenance" in c.description.lower() else _ok()

def x10(c: Claim, p: Policy):
    return (Status.WARN, "Pre-existing or cosmetic damage may be excluded") \
        if "pre-existing" in c.description.lower() or "preexisting" in c.description.lower() else _ok()

def x11(c: Claim, p: Policy):
    return (Status.FAIL, "Territorial exclusion applies") \
        if _excluded(p, "territory") and c.loss_location not in p.territory else _ok()

def x12(c: Claim, p: Policy):
    return (Status.FAIL, "Invalid or suspended license at time of loss") \
        if not c.driver_valid_license else _ok()


# ---------------------------------------------------------------------------
# L - Limits & quantum  (sanity checks; the math itself lives in payout.py)
# ---------------------------------------------------------------------------

def l01(c: Claim, p: Policy):
    return _ok() if c.claimed_amount > 0 else (Status.FAIL, "Claimed amount must be positive")

def l02(c: Claim, p: Policy):
    return _ok() if c.claimed_amount <= p.per_occurrence_limit else (
        Status.WARN, "Claimed amount exceeds the per-occurrence limit; payout will be capped")

def l03(c: Claim, p: Policy):
    remaining = p.aggregate_limit - p.aggregate_used
    return _ok() if remaining > 0 else (Status.FAIL, "Aggregate limit for the term is exhausted")

def l04(c: Claim, p: Policy):
    cap = p.sublimits.get(c.peril.value)
    if cap is not None and c.claimed_amount > cap:
        return (Status.WARN, f"A sublimit of {cap:.2f} applies to {c.peril.value}")
    return _ok()

def l05(c: Claim, p: Policy):
    return _ok() if p.deductible >= 0 else (Status.FAIL, "Deductible is misconfigured")

def l06(c: Claim, p: Policy):
    return _ok() if 0.0 <= p.coinsurance < 1.0 else (Status.FAIL, "Coinsurance out of range")

def l07(c: Claim, p: Policy):
    return _ok()  # betterment/salvage handled in payout; placeholder guard

def l08(c: Claim, p: Policy):
    return _ok() if c.claimed_amount >= p.deductible else (
        Status.WARN, "Claimed amount is at or below the deductible; likely zero payout")

def l09(c: Claim, p: Policy):
    if c.repair_estimate and c.repair_estimate > 0:
        variance = abs(c.claimed_amount - c.repair_estimate) / c.repair_estimate
        if variance > 0.25:
            return (Status.WARN, f"Claimed amount deviates {variance*100:.0f}% from repair estimate")
    return _ok()


# ---------------------------------------------------------------------------
# D - Documentation / administrative
# ---------------------------------------------------------------------------

def _has_doc(c: Claim, kind: str) -> bool:
    return any(d.kind == kind and d.present for d in c.documents)

def d01(c: Claim, p: Policy):
    return _ok() if c.documents else (Status.WARN, "No supporting documents attached")

def d02(c: Claim, p: Policy):
    if c.peril in (Peril.THEFT, Peril.VANDALISM) and not _has_doc(c, "police_report"):
        return (Status.FAIL, "Police report required for theft/vandalism is missing")
    return _ok()

def d03(c: Claim, p: Policy):
    if c.peril in (Peril.COLLISION, Peril.GLASS) and not _has_doc(c, "estimate"):
        return (Status.WARN, "Repair estimate is missing")
    return _ok()

def d04(c: Claim, p: Policy):
    if c.peril == Peril.THEFT and not _has_doc(c, "proof_of_ownership"):
        return (Status.WARN, "Proof of ownership is missing for a theft claim")
    return _ok()

def d05(c: Claim, p: Policy):
    return _ok() if c.claimant_name.strip() else (Status.FAIL, "Claimant identity is missing")

def d06(c: Claim, p: Policy):
    return _ok() if len(c.description.strip()) >= 10 else (
        Status.WARN, "Loss description is missing or too brief")

def d07(c: Claim, p: Policy):
    return _ok() if c.reported_date >= c.loss_date else (
        Status.FAIL, "Report date is before the loss date (inconsistent)")

def d08(c: Claim, p: Policy):
    hashes = [d.sha256 for d in c.documents if d.sha256]
    return _ok() if len(hashes) == len(set(hashes)) else (
        Status.WARN, "Duplicate documents detected (identical hashes)")


# ---------------------------------------------------------------------------
# F - Fraud red-flags (surfaced as rules; weighted score in fraud.py)
# ---------------------------------------------------------------------------

def f01(c: Claim, p: Policy):
    early = p.inception_history_months <= 3 or c.coverage_increase_lt_90d
    return (Status.WARN, "Loss soon after inception or a coverage increase") if early else _ok()

def f02(c: Claim, p: Policy):
    return (Status.WARN, "Reporting delayed beyond 30 days") \
        if (c.reported_date - c.loss_date).days > 30 else _ok()

def f03(c: Claim, p: Policy):
    return (Status.WARN, "Attorney/public adjuster retained before first contact") \
        if c.attorney_retained_before_contact else _ok()

def f04(c: Claim, p: Policy):
    return (Status.WARN, "Elevated prior-claim history across carriers") \
        if c.prior_claims_other_carriers >= 3 else _ok()

def f05(c: Claim, p: Policy):
    round_amt = c.claimed_amount >= 1000 and c.claimed_amount % 1000 == 0
    return (Status.WARN, "Suspiciously round claimed amount") if round_amt else _ok()

def f06(c: Claim, p: Policy):
    for d in c.documents:
        if d.created_at and d.stated_date and d.created_at < d.stated_date:
            return (Status.WARN, "Document created before the date it describes (metadata mismatch)")
    return _ok()

def f07(c: Claim, p: Policy):
    return (Status.WARN, "Font/template anomaly flagged on a document") \
        if any(d.font_anomaly for d in c.documents) else _ok()

def f08(c: Claim, p: Policy):
    return (Status.WARN, "Inspection/EUO avoidance (cancelled appointments)") \
        if c.cancelled_inspections >= 2 else _ok()

def f09(c: Claim, p: Policy):
    return (Status.WARN, "Recent bankruptcy / financial distress") if c.recent_bankruptcy else _ok()

def f10(c: Claim, p: Policy):
    return (Status.WARN, "Address/employer changed within 6 months") \
        if c.address_changed_lt_6mo else _ok()

def f11(c: Claim, p: Policy):
    return (Status.WARN, "Contradictions in the insured's statements") \
        if c.statement_contradiction else _ok()

def f12(c: Claim, p: Policy):
    return (Status.WARN, "Single-provider routing to one repair shop") \
        if c.single_provider_routing else _ok()


RULES: list[Rule] = [
    # C - coverage
    Rule("C01", "coverage", Severity.BLOCKING, "Policy on file matches the claim", "Decl. Page", "POLICY_MISMATCH", c01),
    Rule("C02", "coverage", Severity.BLOCKING, "Policy active on the loss date", "Sec. I - Term", "COVERAGE_NOT_ACTIVE", c02),
    Rule("C03", "coverage", Severity.BLOCKING, "Premium not lapsed on the loss date", "Sec. VIII - Premium", "PREMIUM_LAPSED", c03),
    Rule("C04", "coverage", Severity.BLOCKING, "Peril is a covered peril", "Sec. II - Perils", "PERIL_NOT_COVERED", c04),
    Rule("C05", "coverage", Severity.BLOCKING, "Required coverage type present for the peril", "Decl. Page - Coverages", "COVERAGE_TYPE_MISSING", c05),
    Rule("C06", "coverage", Severity.MATERIAL, "Claimant is the named insured", "Sec. I - Insured", "CLAIMANT_NOT_INSURED", c06),
    Rule("C07", "coverage", Severity.BLOCKING, "Driver is listed or permitted", "Sec. III - Drivers", "DRIVER_NOT_LISTED", c07),
    Rule("C08", "coverage", Severity.BLOCKING, "Vehicle is listed on the policy", "Decl. Page - Vehicles", "VEHICLE_NOT_LISTED", c08),
    Rule("C09", "coverage", Severity.BLOCKING, "Loss within covered territory", "Sec. II - Territory", "OUT_OF_TERRITORY", c09),
    Rule("C10", "coverage", Severity.MATERIAL, "Timely notice of loss", "Sec. VII - Duties", "LATE_NOTICE", c10),
    Rule("C11", "coverage", Severity.BLOCKING, "Loss not before inception", "Sec. I - Term", "LOSS_BEFORE_INCEPTION", c11),
    Rule("C12", "coverage", Severity.BLOCKING, "Loss not after cancellation", "Sec. I - Term", "LOSS_AFTER_CANCELLATION", c12),
    # X - exclusions
    Rule("X01", "exclusion", Severity.BLOCKING, "Wear and tear excluded", "Sec. IV - Exclusions (a)", "EXCL_WEAR_TEAR", x01),
    Rule("X02", "exclusion", Severity.BLOCKING, "Intentional acts excluded", "Sec. IV - Exclusions (b)", "EXCL_INTENTIONAL", x02),
    Rule("X03", "exclusion", Severity.BLOCKING, "Flood excluded without endorsement", "Sec. IV - Exclusions (c)", "EXCL_FLOOD", x03),
    Rule("X04", "exclusion", Severity.BLOCKING, "Business use excluded", "Sec. IV - Exclusions (d)", "EXCL_BUSINESS_USE", x04),
    Rule("X05", "exclusion", Severity.BLOCKING, "Racing excluded", "Sec. IV - Exclusions (e)", "EXCL_RACING", x05),
    Rule("X06", "exclusion", Severity.BLOCKING, "DUI loss excluded", "Sec. IV - Exclusions (f)", "EXCL_DUI", x06),
    Rule("X07", "exclusion", Severity.BLOCKING, "Unlisted-driver exclusion", "Sec. IV - Exclusions (g)", "EXCL_UNLISTED_DRIVER", x07),
    Rule("X08", "exclusion", Severity.BLOCKING, "War/terrorism/nuclear excluded", "Sec. IV - Exclusions (h)", "EXCL_WAR", x08),
    Rule("X09", "exclusion", Severity.ADVISORY, "Neglect/maintenance advisory", "Sec. IV - Exclusions (a)", "EXCL_NEGLECT", x09),
    Rule("X10", "exclusion", Severity.ADVISORY, "Pre-existing/cosmetic advisory", "Sec. IV - Exclusions (i)", "EXCL_PREEXISTING", x10),
    Rule("X11", "exclusion", Severity.BLOCKING, "Territorial exclusion", "Sec. IV - Exclusions (j)", "EXCL_TERRITORY", x11),
    Rule("X12", "exclusion", Severity.BLOCKING, "Invalid license exclusion", "Sec. IV - Exclusions (k)", "EXCL_INVALID_LICENSE", x12),
    # L - limits & quantum
    Rule("L01", "limits", Severity.BLOCKING, "Claimed amount positive", "Sec. V - Limits", "AMOUNT_INVALID", l01),
    Rule("L02", "limits", Severity.MATERIAL, "Within per-occurrence limit", "Sec. V - Limits", "OVER_OCCURRENCE_LIMIT", l02),
    Rule("L03", "limits", Severity.BLOCKING, "Aggregate not exhausted", "Sec. V - Limits", "AGGREGATE_EXHAUSTED", l03),
    Rule("L04", "limits", Severity.MATERIAL, "Sublimit applied", "Sec. V - Sublimits", "SUBLIMIT_APPLIES", l04),
    Rule("L05", "limits", Severity.BLOCKING, "Deductible configured", "Decl. Page - Deductible", "DEDUCTIBLE_INVALID", l05),
    Rule("L06", "limits", Severity.BLOCKING, "Coinsurance in range", "Sec. V - Coinsurance", "COINSURANCE_INVALID", l06),
    Rule("L07", "limits", Severity.ADVISORY, "Betterment/salvage guard", "Sec. VI - Valuation", "BETTERMENT", l07),
    Rule("L08", "limits", Severity.ADVISORY, "Amount above deductible", "Decl. Page - Deductible", "BELOW_DEDUCTIBLE", l08),
    Rule("L09", "limits", Severity.MATERIAL, "Amount consistent with estimate", "Sec. VI - Valuation", "ESTIMATE_VARIANCE", l09),
    # D - documentation
    Rule("D01", "documentation", Severity.ADVISORY, "Documents attached", "Sec. VII - Duties", "NO_DOCUMENTS", d01),
    Rule("D02", "documentation", Severity.BLOCKING, "Police report for theft/vandalism", "Sec. VII - Duties", "MISSING_POLICE_REPORT", d02),
    Rule("D03", "documentation", Severity.MATERIAL, "Repair estimate present", "Sec. VII - Duties", "MISSING_ESTIMATE", d03),
    Rule("D04", "documentation", Severity.MATERIAL, "Proof of ownership present", "Sec. VII - Duties", "MISSING_OWNERSHIP", d04),
    Rule("D05", "documentation", Severity.BLOCKING, "Claimant identity present", "Sec. VII - Duties", "MISSING_CLAIMANT", d05),
    Rule("D06", "documentation", Severity.MATERIAL, "Loss description present", "Sec. VII - Duties", "MISSING_DESCRIPTION", d06),
    Rule("D07", "documentation", Severity.BLOCKING, "Dates internally consistent", "Sec. VII - Duties", "DATE_INCONSISTENT", d07),
    Rule("D08", "documentation", Severity.MATERIAL, "No duplicate documents", "Sec. VII - Duties", "DUPLICATE_DOCS", d08),
    # F - fraud red-flags
    Rule("F01", "fraud", Severity.ADVISORY, "Early loss after inception/increase", "SIU Indicator 1", "FRAUD_EARLY_LOSS", f01),
    Rule("F02", "fraud", Severity.ADVISORY, "Delayed reporting", "SIU Indicator 2", "FRAUD_DELAYED_REPORT", f02),
    Rule("F03", "fraud", Severity.ADVISORY, "Early attorney involvement", "SIU Indicator 3", "FRAUD_EARLY_ATTORNEY", f03),
    Rule("F04", "fraud", Severity.ADVISORY, "Cross-carrier claim history", "SIU Indicator 4", "FRAUD_PRIOR_CLAIMS", f04),
    Rule("F05", "fraud", Severity.ADVISORY, "Round claimed amount", "SIU Indicator 5", "FRAUD_ROUND_AMOUNT", f05),
    Rule("F06", "fraud", Severity.ADVISORY, "Document metadata mismatch", "SIU Indicator 6", "FRAUD_METADATA", f06),
    Rule("F07", "fraud", Severity.ADVISORY, "Template/font anomaly", "SIU Indicator 7", "FRAUD_TEMPLATE", f07),
    Rule("F08", "fraud", Severity.ADVISORY, "Inspection avoidance", "SIU Indicator 8", "FRAUD_INSPECTION_AVOID", f08),
    Rule("F09", "fraud", Severity.ADVISORY, "Financial distress", "SIU Indicator 9", "FRAUD_FINANCIAL", f09),
    Rule("F10", "fraud", Severity.ADVISORY, "Recent address/employer change", "SIU Indicator 10", "FRAUD_ADDRESS_CHANGE", f10),
    Rule("F11", "fraud", Severity.ADVISORY, "Statement contradictions", "SIU Indicator 11", "FRAUD_CONTRADICTION", f11),
    Rule("F12", "fraud", Severity.ADVISORY, "Single-provider routing", "SIU Indicator 12", "FRAUD_SINGLE_PROVIDER", f12),
]

assert len({r.rule_id for r in RULES}) == len(RULES), "duplicate rule ids"
