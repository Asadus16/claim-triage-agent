# Insurance Claim Triage Agent

An AI agent that reads an auto-insurance claim, applies a written rule book, and
recommends **pay / investigate / deny / refer** — with a human making the final
call. Built as a hybrid: **n8n** orchestrates the workflow and the human-approval
step, while a **FastAPI** service holds the deterministic engine, the guardrails,
and the regression suite.

The design answers the questions a serious insurance client actually asks:
*can it invent a payout? can it be audited? what happens when it is unsure? how
do you know a change didn't break it?*

## What makes it different

Most public "AI claims" demos stop at a single LLM pass that reads a claim and
emits a verdict with a confidence number. This one is built the way a regulated
workflow has to be:

- **The model never decides or computes.** The LLM only extracts facts from the
  narrative (validated against a strict schema). Every rule outcome and every
  dollar figure comes from deterministic code. A narration guardrail rejects any
  number the model tries to introduce that the engine did not produce.
- **A readable 53-rule catalog** across coverage, exclusions, limits/quantum,
  documentation, and SIU fraud red-flags — each rule cites the exact policy
  clause and emits a machine-readable reason code. `GET /rules` returns the whole
  catalog for a client to review.
- **Deterministic payout math** (deductible, sublimits, per-occurrence and
  aggregate limits, coinsurance) with a step-by-step trace on every claim.
- **Calibrated confidence with an explicit abstain/refer band** — low-confidence
  extractions are routed to a human instead of forced into an answer.
- **A golden-sample regression suite** (`data/golden/cases.json`) replayed on
  every change; `POST /golden/run` and CI fail the build if a decision or payout
  silently changes. This is the piece almost no competing portfolio has.
- **Record/replay of LLM calls** so tests are fast, free and deterministic and
  the demo runs with no live key.
- **Normalized relational store + full audit trail** (SQLite, 10 tables) —
  policies with their perils/coverages/sublimits as child tables, claims,
  documents, decisions, per-decision rule results and fraud signals, and a
  human_reviews table. Every decision and its human override are reconstructable
  by `audit_id`, mapping to insurers' claim-file reconstruction obligations. See
  the schema in `docs/erd-real.png` (regenerate with `python3 docs/gen_erd.py`).
- **Human decides, system recommends** — the approval gate is built into the
  n8n workflow, not bolted on.

## Architecture

```
Claim intake (n8n webhook)
  -> FastAPI /triage/from-text
       - LLM extracts facts  -> validated schema (fail closed on bad JSON)
       - rule engine (53 rules) -> reason codes + clause citations
       - deterministic payout  -> step trace
       - fraud scoring          -> calibrated 0..1 + band
       - recommendation + confidence
  -> n8n IF: straight-through eligible?
       yes -> auto-approve -> respond
       no  -> human approval form -> POST /human/{audit_id} -> respond
```

n8n Cloud's Code node cannot import libraries or make network calls, so the
engine deliberately lives in the FastAPI service and is reached over HTTP. The
deterministic core (`app/models.py`, `app/rules/`) has **zero framework
dependencies** and is unit-tested in isolation.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set SERVICE_API_KEY; GEMINI_API_KEY optional (replay works without)
pytest                        # 42 tests, incl. the golden regression gate
uvicorn app.main:app --reload
```

Expose it to n8n Cloud for the demo with a tunnel:

```bash
ngrok http 8000               # put the https URL into the n8n HTTP nodes
```

Then import `n8n/claim-triage.workflow.json` into n8n (Import from File), set the
tunnel URL in the two HTTP Request nodes and `SERVICE_API_KEY` as an n8n env var.

## LLM modes

`LLM_MODE=replay` (default) uses cached responses — no network, no key. Set
`LLM_MODE=record` with a `GEMINI_API_KEY` to capture real responses into
`data/cassettes/`, then commit them so the demo and tests stay deterministic.

## Honest limits

- The policy, claims and fraud indicators are **synthetic** and modelled on
  publicly described adjudication mechanics and SIU red-flag checklists; they are
  not a specific insurer's rule book. The rule catalog is a realistic starting
  point to be tuned per carrier against the golden set.
- Fraud weights and the STP/abstain thresholds are calibrated against the golden
  set, not against real loss outcomes; on a real book they would be back-tested.
- Not legal or compliance advice.
