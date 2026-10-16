# 12 — Event provenance, evidence, contracts and schemas

## Scope

The project must record observable events across **separate agent, wire, rail, counterparty, and principal** layers. Logs are the research evidence. A natural-language claim (“I checked”, “I transferred”) is not the evidence of a tool invocation or settlement.

## Files every run must produce

- `run_manifest.json`: git commits, source pins, execution tiers, randomization, exact model/SDK IDs, tasks/oracle commitments, budgets, timestamps, logs hash, protocol capability.
- `events.jsonl`: one schema-valid event per state transition or tool action with stable IDs and causal relation (`parent_event_id`).
- `episode_outcomes.csv` / `episode_outcomes.jsonl`: `Y`, `V`, `Q`, `paid`, `wrong_paid`, `honest_unpaid`, `budget`, `guard`, `relationship`, `task_family`, `protocol`.
- `protocol_evidence/`: EVM receipts/events or local facilitator records; mock ledger clearly marked.
- `analysis/`: script logs, preregistered estimates, failure denominators, confidence intervals.

## Event minimum fields

`schema_version`, `run_id`, `experiment_id`, `episode_id`, `event_id`, `parent_event_id`, `seq`, `timestamp_utc`, `actor_id`, `actor_role`, `event_type`, `execution_tier`, `protocol_name`, `protocol_version`, `task_id`, `obligation_id`, `artifact_digest`, `evidence_digest`, `payment_reference`, `amount_minor_units`, `currency`, `status`, `payload`.

Extra booleans such as `private_truth_exposed`, `tool_call_verified`, `receipt_native`, and `model_decision` must be derived from independent observation—not written by the role being scored.

## Two-axis evidence tiers

Model behavior tier: `SCRIPTED`, `REAL_LLM_LOCAL`, or `REAL_LLM_REMOTE_APPROVED`. Payment tier: `MOCK_LOCAL`, `NATIVE_LOCAL_CHAIN`, `NATIVE_LOCAL_FACILITATOR`, `NATIVE_TESTNET_APPROVED`. Store **both axes**, not a single ambiguous 'live' flag. Production use prohibited.

## Evidence canonicalization

- Canonicalize structured payload before hashing and ensure hashes are reproducible. The legacy SHA-256 trace digest indicates local log consistency; it does not prove external non-repudiation.
- Redact signing material and API secrets; store key references/addresses only. Do not log raw sensitive payment authorization material that could be replayed.
- For EVM transactions, store chain ID, block number/hash, transaction hash, contract ABI commit, event topic/index, observed balances and finality assumption.
- For x402 HTTP, store request/response status, headers in redacted form, challenge scheme/version, semantic resource ID, verification result, settlement result and timestamps.
- For agent messages, store source principal, destination, channel permissions, message digest, content classification (`TRUSTED_INSTRUCTION` vs `UNTRUSTED_DATA`), and tool traces.

## Event taxonomy

`TASK_CREATED`, `MARKET_BID`, `COUNTERPARTY_SELECTED`, `PAYMENT_OFFERED`, `OFFER_AUTHENTICATED`, `OFFER_SETTLED`, `WORK_SUBMITTED`, `AUDIT_REQUESTED`, `CHECK_TOOL_CALLED`, `CHECK_COMPLETED`, `VERDICT_ISSUED`, `PAYMENT_AUTHORIZED`, `PAYMENT_VERIFY`, `RESOURCE_EXECUTED`, `PAYMENT_SETTLED`, `PAYMENT_REFUNDED`, `PAYMENT_REJECTED`, `DISPUTE_OPENED`, `EXPIRED`, `ORACLE_SCORED`, `TASK_CLOSED`, `ERROR`, `SKIP`.

## Schema adoption

See `schemas/event.schema.json` and `schemas/run_manifest.schema.json` for proposed v1 shapes. Codex can add fields but must increment version and document compatibility. `scripts/validate_handover.py` only checks template/file integrity; does not validate live event correctness. Add native schema validation and evidence-signer separation tests during W03–W05.
