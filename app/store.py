"""Relational persistence for claims, decisions and the audit trail.

A normalized schema: policy list-attributes (perils, coverages, sublimits) are
their own child tables rather than JSON blobs, and a human review is its own
table linked to a decision. This reconstructs a claim file end to end and makes
the data model reflect real database design.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import Claim, Decision, Policy

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS policies (
    policy_number TEXT PRIMARY KEY,
    insured_name TEXT,
    effective_date TEXT,
    expiration_date TEXT,
    deductible REAL,
    per_occurrence_limit REAL,
    aggregate_limit REAL,
    aggregate_used REAL,
    coinsurance REAL,
    territory TEXT,
    exclusions TEXT,
    endorsements TEXT,
    premium_lapsed INTEGER,
    cancelled_date TEXT,
    inception_history_months INTEGER
);

CREATE TABLE IF NOT EXISTS policy_perils (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number TEXT REFERENCES policies(policy_number),
    peril TEXT
);

CREATE TABLE IF NOT EXISTS policy_coverages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number TEXT REFERENCES policies(policy_number),
    coverage_type TEXT
);

CREATE TABLE IF NOT EXISTS policy_sublimits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number TEXT REFERENCES policies(policy_number),
    category TEXT,
    amount REAL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    policy_number TEXT REFERENCES policies(policy_number),
    loss_date TEXT,
    reported_date TEXT,
    peril TEXT,
    claimant_name TEXT,
    driver_name TEXT,
    vehicle_id TEXT,
    loss_location TEXT,
    claimed_amount REAL,
    repair_estimate REAL,
    description TEXT,
    extraction_confidence REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT REFERENCES claims(claim_id),
    kind TEXT,
    present INTEGER,
    created_at TEXT,
    stated_date TEXT,
    sha256 TEXT,
    font_anomaly INTEGER
);

CREATE TABLE IF NOT EXISTS decisions (
    audit_id TEXT PRIMARY KEY,
    claim_id TEXT REFERENCES claims(claim_id),
    recommendation TEXT,
    confidence REAL,
    requires_human INTEGER,
    payout REAL,
    fraud_score REAL,
    stp_eligible INTEGER,
    reason_codes TEXT,
    prompt_version TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT REFERENCES decisions(audit_id),
    action TEXT,
    note TEXT,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS rule_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT REFERENCES decisions(audit_id),
    rule_id TEXT,
    category TEXT,
    status TEXT,
    severity TEXT,
    message TEXT,
    clause_ref TEXT,
    reason_code TEXT
);

CREATE TABLE IF NOT EXISTS fraud_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT REFERENCES decisions(audit_id),
    indicator_id TEXT,
    category TEXT,
    triggered INTEGER,
    weight REAL,
    evidence TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _save_policy(self, con, p: Policy) -> None:
        con.execute(
            "INSERT OR REPLACE INTO policies (policy_number, insured_name, effective_date, "
            "expiration_date, deductible, per_occurrence_limit, aggregate_limit, aggregate_used, "
            "coinsurance, territory, exclusions, endorsements, premium_lapsed, cancelled_date, "
            "inception_history_months) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p.policy_number, p.insured_name, p.effective_date.isoformat(),
                p.expiration_date.isoformat(), p.deductible, p.per_occurrence_limit,
                p.aggregate_limit, p.aggregate_used, p.coinsurance,
                json.dumps(p.territory), json.dumps(p.exclusions), json.dumps(p.endorsements),
                int(p.premium_lapsed),
                p.cancelled_date.isoformat() if p.cancelled_date else None,
                p.inception_history_months,
            ),
        )
        for tbl, col, values in (
            ("policy_perils", "peril", [x.value for x in p.covered_perils]),
            ("policy_coverages", "coverage_type", [x.value for x in p.coverage_types]),
        ):
            con.execute(f"DELETE FROM {tbl} WHERE policy_number = ?", (p.policy_number,))
            for v in values:
                con.execute(f"INSERT INTO {tbl} (policy_number, {col}) VALUES (?,?)",
                            (p.policy_number, v))
        con.execute("DELETE FROM policy_sublimits WHERE policy_number = ?", (p.policy_number,))
        for cat, amt in p.sublimits.items():
            con.execute("INSERT INTO policy_sublimits (policy_number, category, amount) VALUES (?,?,?)",
                        (p.policy_number, cat, amt))

    def _save_claim(self, con, c: Claim) -> None:
        con.execute(
            "INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                c.claim_id, c.policy_number, c.loss_date.isoformat(),
                c.reported_date.isoformat(), c.peril.value, c.claimant_name,
                c.driver_name, c.vehicle_id, c.loss_location, c.claimed_amount,
                c.repair_estimate, c.description, c.extraction_confidence, _now(),
            ),
        )
        con.execute("DELETE FROM documents WHERE claim_id = ?", (c.claim_id,))
        for d in c.documents:
            con.execute(
                "INSERT INTO documents (claim_id, kind, present, created_at, stated_date, "
                "sha256, font_anomaly) VALUES (?,?,?,?,?,?,?)",
                (c.claim_id, d.kind, int(d.present),
                 d.created_at.isoformat() if d.created_at else None,
                 d.stated_date.isoformat() if d.stated_date else None,
                 d.sha256, int(d.font_anomaly)),
            )

    def save(self, policy: Policy, claim: Claim, decision: Decision,
             prompt_version: str | None = None) -> str:
        audit_id = str(uuid.uuid4())
        decision.audit_id = audit_id
        decision.prompt_version = prompt_version
        with self._connect() as con:
            self._save_policy(con, policy)
            self._save_claim(con, claim)
            con.execute(
                "INSERT INTO decisions (audit_id, claim_id, recommendation, confidence, "
                "requires_human, payout, fraud_score, stp_eligible, reason_codes, "
                "prompt_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    audit_id, claim.claim_id, decision.recommendation.value,
                    decision.confidence, int(decision.requires_human),
                    decision.payout.payout if decision.payout else None,
                    decision.fraud_score, int(decision.stp_eligible),
                    json.dumps(decision.reason_codes), prompt_version, _now(),
                ),
            )
            for r in decision.rule_results:
                con.execute(
                    "INSERT INTO rule_results (audit_id, rule_id, category, status, severity, "
                    "message, clause_ref, reason_code) VALUES (?,?,?,?,?,?,?,?)",
                    (audit_id, r.rule_id, r.category, r.status.value, r.severity.value,
                     r.message, r.clause_ref, r.reason_code),
                )
            for s in decision.fraud_signals:
                con.execute(
                    "INSERT INTO fraud_signals (audit_id, indicator_id, category, triggered, "
                    "weight, evidence) VALUES (?,?,?,?,?,?)",
                    (audit_id, s.indicator_id, s.category, int(s.triggered), s.weight, s.evidence),
                )
        return audit_id

    def record_human(self, audit_id: str, action: str, note: str) -> bool:
        with self._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM decisions WHERE audit_id = ?", (audit_id,)).fetchone()
            if not exists:
                return False
            con.execute(
                "INSERT INTO human_reviews (audit_id, action, note, reviewed_at) VALUES (?,?,?,?)",
                (audit_id, action, note, _now()),
            )
            return True

    def get(self, audit_id: str) -> dict | None:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            dec = con.execute("SELECT * FROM decisions WHERE audit_id=?", (audit_id,)).fetchone()
            if not dec:
                return None
            record = dict(dec)
            record["reason_codes"] = json.loads(record.get("reason_codes") or "[]")
            record["rule_results"] = [dict(r) for r in con.execute(
                "SELECT rule_id, category, status, severity, reason_code, clause_ref "
                "FROM rule_results WHERE audit_id=?", (audit_id,)).fetchall()]
            record["fraud_signals"] = [dict(r) for r in con.execute(
                "SELECT indicator_id, category, triggered, weight, evidence "
                "FROM fraud_signals WHERE audit_id=? AND triggered=1", (audit_id,)).fetchall()]
            review = con.execute(
                "SELECT action, note, reviewed_at FROM human_reviews WHERE audit_id=? "
                "ORDER BY id DESC LIMIT 1", (audit_id,)).fetchone()
            record["human_action"] = review["action"] if review else None
            record["human_note"] = review["note"] if review else None
            record["human_at"] = review["reviewed_at"] if review else None
            claim = con.execute("SELECT * FROM claims WHERE claim_id=?", (dec["claim_id"],)).fetchone()
            record["claim"] = dict(claim) if claim else None
            return record
