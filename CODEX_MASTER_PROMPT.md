# Codex master execution prompt — research build

You are the implementation/research engineering owner for the project **“When Agents Pay Their Auditors: Economic Collusion and Verification Integrity in Autonomous Agent Commerce.”** The ZIP containing this file is the complete handover, including legacy simulator source/results and the user's 12-page preliminary PDF.

## Non-negotiable course correction

**DO NOT BUILD OR MARKET A NEW GENERAL-PURPOSE BENCHMARK.** Reuse the existing open-source **ORBIT v1-compatible / Inspect AI** agent evaluation infrastructure as the primary multi-agent runtime. Adapt Colosseum's *formal action/coalition attribution methods* where appropriate; use ORBIT/AgentDojo task environments rather than replacing them. Write only thin integration code for payment-protocol operations, role isolation, economic interventions, independent oracles, event logging, and statistical evaluation. Preserve the v0.2 standalone simulator as a read-only archival baseline, not the source of live-agent conclusions.

## Mandatory initial reads

`AGENTS.md`, `START_HERE.md`, `docs/01_PROJECT_CHARTER.md`, `docs/04_RESEARCH_QUESTIONS.md`, `docs/05_SYSTEM_AND_THREAT_MODEL.md`, `docs/08_PROTOCOL_COVERAGE.md`, `docs/09_RUNTIME_ARCHITECTURE.md`, `docs/10_METRICS_AND_STATISTICS.md`, `planning/WORK_ORDERS.md`, `planning/STAGE_GATES.md`, `planning/ACCEPTANCE_TEST_MATRIX.md`, and `docs/16_UPSTREAM_SOURCE_REGISTER.md`. Read the archived PDF for actual preliminary evidence; do not infer outcomes that are not in it.

## Your execution contract

1. **Inventory first.** Inspect the extracted workspace, legacy baseline, installed runtimes/tools, and current official upstream repositories and docs. Report which upstream versions and code hashes are actually available. Verify licensing before copying third-party code.
2. **Establish G0.** Run `python scripts/validate_handover.py`; in the legacy source folder, run its Python unittest suite and loopback wire-smoke command. Record actual results and failures. Do not silently edit legacy files.
3. **Integrate ORBIT/Inspect.** Fetch and pin the maintained ORBIT GitHub release/source (the PyPI package named `orbit` may be unrelated). Inspect its real `multi_agent_task` API, Inspect Task, agent scheduler, tools, logs, and scorer contracts; do not invent imports. Build an example in `src/agent_economic_trust/` using ORBIT's extension points. Use Colosseum as a baseline/metric-method reference with frozen upstream version, not as the primary payment runtime.
4. **Ship a minimal real-agent pilot.** A worker and auditor run isolated model sessions with task-scoped tools, a feasible but priced verification call, clean vs defective work, and an independent oracle. Keep payment **mock and explicitly labelled** until native adapters pass gate G2. Prove hidden truth is not available to the auditor. Support deterministic mock model tests offline and optional opt-in local LLM endpoint. Record actual model decisions separately from scripted controls.
5. **Native ERC-8183 first.** Deploy pinned upstream reference contracts to local Anvil (or equivalently isolated local chain), execute create/fund/submit/complete/reject/expiry/refund with valueless test assets. Verify on-chain events, balance conservation, roles, claim/partial settlement variants if present in pinned revision, and artifact-binding as a separate *application* guard. No chain RPC outside loopback by default.
6. **Native x402 v2 second.** Use official SDK + local HTTP server/facilitator to check payment-required challenge, valid signed authorization, scheme-specific verify/settle ordering, replay/freshness, bounded costs, failure/response states. Preserve the boundary between authentication, resource delivery and semantic correctness. Do not call mock HMAC a valid native authorization.
7. **Then expand** to MPP charge/session, AP2 v0.2 authorization, Virtuals ACP v2 (maintained `acp-node-v2`, NOT the deprecated package), OpenAI/Stripe ACP checkout, UCP+AP2, A2A v1.0 communication compositions, ERC-8004 identity/reputation overlays. Record SKIP with precise reason for unavailable credentials, SDK or conformance tests. Never conflate ACP variants.
8. **Scientific evaluation.** Implement preregistered factorial R (financial dependence) × S (verification scarcity) × P (persuasive evidence); randomize and cluster at the correct unit. Separate real verifier policy effects from fixed-decision enforcement effects. Run repeated-market assignment and communication/turnover counterfactuals to attribute coordination. Compare security, legitimate payments, checking costs, and latency at matched budgets.
9. **Deliver checkpoints** after each work order: runnable commands, exact output locations, tests, PASS/FAIL/SKIP, implementation notes, deviations and next work order. Follow the stop conditions. Never state a paper finding from a scripted coefficient, a synthetic oracle exposed to a guard, or an unauthenticated payment stub.

## Minimum next-deliverable definition (before expanding protocols)

- An actual ORBIT/Inspect multi-agent test that runs under its pinned release (or a precisely labelled Inspect-only fallback if ORBIT is inaccessible).
- Two isolated agents and independent task oracle.
- One check-cost tool, which returns only its authorized result after a logged spend.
- Structured `episode.jsonl` and `run_manifest.json` matching (or versioning) the provided schemas.
- Deterministic tests for hidden-state isolation, balance conservation, impossible-rule detection, replay/idempotency semantics in mock mode, and correct state-grounded scoring.
- One reproducible script and a results report explicitly marked `REAL_LLM_LOCAL` or `SCRIPTED_SIMULATION`.

## Scientific discipline

A signed receipt is not task correctness; a jointly incorrect outcome is not collusion; an LLM claiming it accepted a payment is not an executed transfer; a payment-only standard is not defective merely because it omits independent content verification. Null effects and failures must be reported. The latest upstream protocol documentation takes precedence over assumptions in older local mocks; record source versions and deviations.

Do not spin up background paid jobs, leave unbounded retries, spend real funds, or use production payment accounts. Default all external model/API spending to OFF until explicit owner approval. If a step is blocked, preserve the current working state and submit exact blocker evidence instead of synthesizing a success narrative.

**Begin at `planning/FIRST_48_HOURS.md`. Make the first actual code change only after G0 inventory and baseline are recorded.**
