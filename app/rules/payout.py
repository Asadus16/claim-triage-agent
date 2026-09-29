"""Deterministic payout math. No LLM ever computes a figure here.

Order of operations (each step recorded for the audit trail):
  1. covered loss starts at the claimed amount
  2. cap by the peril sublimit, if any
  3. cap by the per-occurrence limit
  4. subtract the deductible (never below zero)
  5. apply coinsurance (the insured's retained share)
  6. cap by the remaining aggregate for the term
"""

from __future__ import annotations

from app.models import Claim, PayoutBreakdown, Policy


def compute_payout(claim: Claim, policy: Policy) -> PayoutBreakdown:
    steps: list[str] = []
    covered = float(claim.claimed_amount)
    steps.append(f"covered loss = claimed amount = {covered:.2f}")

    sublimit_cap = policy.sublimits.get(claim.peril.value)
    if sublimit_cap is not None and covered > sublimit_cap:
        covered = float(sublimit_cap)
        steps.append(f"apply {claim.peril.value} sublimit -> {covered:.2f}")

    limit_cap = policy.per_occurrence_limit
    if covered > limit_cap:
        covered = float(limit_cap)
        steps.append(f"apply per-occurrence limit -> {covered:.2f}")

    after_deductible = max(0.0, covered - policy.deductible)
    steps.append(f"subtract deductible {policy.deductible:.2f} -> {after_deductible:.2f}")

    coinsurance_applied = after_deductible * policy.coinsurance
    payable = after_deductible - coinsurance_applied
    if policy.coinsurance:
        steps.append(
            f"apply coinsurance {policy.coinsurance:.2%} "
            f"(insured share {coinsurance_applied:.2f}) -> {payable:.2f}"
        )

    aggregate_remaining = policy.aggregate_limit - policy.aggregate_used
    if payable > aggregate_remaining:
        payable = max(0.0, aggregate_remaining)
        steps.append(f"cap by remaining aggregate {aggregate_remaining:.2f} -> {payable:.2f}")

    payout = round(max(0.0, payable), 2)
    steps.append(f"final payout = {payout:.2f}")

    return PayoutBreakdown(
        covered_loss=round(covered, 2),
        deductible_applied=round(min(covered, policy.deductible), 2),
        coinsurance_applied=round(coinsurance_applied, 2),
        sublimit_cap=sublimit_cap,
        limit_cap=limit_cap,
        aggregate_remaining=round(aggregate_remaining, 2),
        payout=payout,
        steps=steps,
    )
