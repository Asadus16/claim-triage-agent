"""API smoke tests. No live LLM needed: /decide is deterministic and narrate=False."""

import os

os.environ.setdefault("SERVICE_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
HEADERS = {"X-API-Key": "test-key"}

CLEAN_COLLISION = {
    "policy": {
        "policy_number": "P1", "insured_name": "Maria Lopez",
        "effective_date": "2026-01-01", "expiration_date": "2027-01-01",
        "territory": ["CA"], "covered_perils": ["collision"],
        "coverage_types": ["collision"], "deductible": 500,
        "per_occurrence_limit": 25000, "aggregate_limit": 50000,
    },
    "claim": {
        "claim_id": "CLM-API-1", "policy_number": "P1", "loss_date": "2026-06-01",
        "reported_date": "2026-06-03", "peril": "collision", "claimant_name": "Maria Lopez",
        "driver_name": "Maria Lopez", "vehicle_id": "VIN1", "loss_location": "CA",
        "claimed_amount": 1850, "repair_estimate": 1850,
        "description": "rear end collision at a stop light", "documents": [{"kind": "estimate"}],
    },
    "narrate": False,
}


def test_health_open():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["rules"] == 53


def test_decide_requires_key():
    assert client.post("/decide", json=CLEAN_COLLISION).status_code == 401


def test_decide_clean_collision():
    r = client.post("/decide", json=CLEAN_COLLISION, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"] == "pay"
    assert body["payout"]["payout"] == 1350.0  # 1850 - 500
    assert body["audit_id"]


def test_audit_roundtrip_and_human_override():
    r = client.post("/decide", json=CLEAN_COLLISION, headers=HEADERS)
    audit_id = r.json()["audit_id"]
    h = client.post(f"/human/{audit_id}", json={"action": "approve", "note": "ok"}, headers=HEADERS)
    assert h.status_code == 200
    a = client.get(f"/audit/{audit_id}", headers=HEADERS)
    assert a.json()["human_action"] == "approve"


def test_golden_endpoint_all_pass():
    r = client.post("/golden/run", headers=HEADERS)
    body = r.json()
    assert body["failed"] == 0 and body["passed"] >= 20


def test_rules_catalog():
    r = client.get("/rules", headers=HEADERS)
    assert len(r.json()) == 53
