"""FastAPI service: the deterministic claim-triage engine behind the n8n workflow.

n8n orchestrates the flow and the human approval step; this service does the
extraction (LLM), the deterministic decision, the guarded narration, the audit
log, and exposes the rule catalog and the regression runner.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException

from app.config import get_settings
from app.golden import parse_claim, parse_policy, run_all
from app.llm.extract import extract_claim
from app.llm.narrate import narrate
from app.rules.catalog import RULES
from app.rules.engine import decide
from app.schemas import (
    DecideRequest,
    ExtractRequest,
    FromTextRequest,
    HumanDecisionRequest,
)
from app.security import verify_api_key
from app.store import ClaimStore

app = FastAPI(title="Claim Triage Agent", version="1.0.0")
_settings = get_settings()
_store = ClaimStore(_settings.claims_db)


def _enum_safe(obj):
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"not serializable: {type(obj)}")


def _decision_dict(decision) -> dict:
    import json
    return json.loads(json.dumps(asdict(decision), default=_enum_safe))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_mode": _settings.llm_mode,
            "prompt_version": _settings.prompt_version, "rules": len(RULES)}


@app.get("/rules", dependencies=[Depends(verify_api_key)])
def rules() -> list[dict]:
    return [
        {"rule_id": r.rule_id, "category": r.category, "severity": r.severity.value,
         "description": r.description, "clause_ref": r.clause_ref,
         "reason_code": r.reason_code}
        for r in RULES
    ]


@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract(req: ExtractRequest) -> dict:
    return extract_claim(req.claim_text).model_dump()


@app.post("/decide", dependencies=[Depends(verify_api_key)])
def decide_endpoint(req: DecideRequest) -> dict:
    policy = parse_policy(req.policy.model_dump())
    claim = parse_claim(req.claim.model_dump())
    decision = decide(claim, policy)
    narrative, used_llm = ("", False)
    if req.narrate:
        narrative, used_llm = narrate(decision)
    audit_id = _store.save(policy, claim, decision, prompt_version=_settings.prompt_version)
    result = _decision_dict(decision)
    result["narrative"] = narrative
    result["narrative_from_llm"] = used_llm
    result["audit_id"] = audit_id
    return result


@app.post("/triage/from-text", dependencies=[Depends(verify_api_key)])
def triage_from_text(req: FromTextRequest) -> dict:
    extracted = extract_claim(req.claim_text)
    claim_dict = {
        "claim_id": req.claim_id,
        "policy_number": req.policy_number,
        "loss_date": req.loss_date,
        "reported_date": req.reported_date,
        "vehicle_id": req.vehicle_id,
        "loss_location": req.loss_location or extracted.loss_location,
        "peril": extracted.peril,
        "claimant_name": extracted.claimant_name or req.policy.insured_name,
        "driver_name": extracted.driver_name or extracted.claimant_name,
        "claimed_amount": extracted.claimed_amount,
        "repair_estimate": extracted.repair_estimate,
        "description": extracted.description,
        "driver_under_influence": extracted.driver_under_influence,
        "business_use": extracted.business_use,
        "racing": extracted.racing,
        "extraction_confidence": extracted.extraction_confidence,
    }
    policy = parse_policy(req.policy.model_dump())
    claim = parse_claim(claim_dict)
    decision = decide(claim, policy)
    narrative, used_llm = narrate(decision) if req.narrate else ("", False)
    audit_id = _store.save(policy, claim, decision, prompt_version=_settings.prompt_version)
    result = _decision_dict(decision)
    result["extracted"] = extracted.model_dump()
    result["narrative"] = narrative
    result["narrative_from_llm"] = used_llm
    result["audit_id"] = audit_id
    return result


@app.post("/human/{audit_id}", dependencies=[Depends(verify_api_key)])
def human_decision(audit_id: str, req: HumanDecisionRequest) -> dict:
    if not _store.record_human(audit_id, req.action, req.note):
        raise HTTPException(status_code=404, detail="audit id not found")
    return {"audit_id": audit_id, "action": req.action, "recorded": True}


@app.get("/audit/{audit_id}", dependencies=[Depends(verify_api_key)])
def get_audit(audit_id: str) -> dict:
    record = _store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="audit id not found")
    return record


@app.post("/golden/run", dependencies=[Depends(verify_api_key)])
def golden_run() -> dict:
    results = run_all()
    passed = [r for r in results if r.passed]
    return {
        "total": len(results),
        "passed": len(passed),
        "failed": len(results) - len(passed),
        "failures": [{"name": r.name, "failures": r.failures}
                     for r in results if not r.passed],
    }
