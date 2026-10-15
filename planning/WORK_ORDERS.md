# Ordered Codex work orders — implement small, verifiable slices

All work orders: preserve current baseline, write code/tests, produce PASS/FAIL/SKIP artifact and reason. Do not silently advance past a failed gate. `G#` refers to `STAGE_GATES.md`.

| Work | Gate | Concrete deliverable | Acceptance proof | Dependency |
|---|---|---|---|---|
| **W00 Inventory / G0** | G0 | Environment, legacy hashes, old unittest and wire-smoke reports | Captured commands/logs, no source mutation | None |
| **W01 Upstream pinning** | G0→G1 | ORBIT/Inspect/Colosseum releases SHA, license, API inspection | Pinned `upstream_versions.json`; ORBIT release installed correctly | W00 |
| **W02 First native ORBIT task** | G1 | Minimal ORBIT/Inspect worker + auditor; task/score | Real Inspect Task executes; no mock substitute for ORBIT label | W01 |
| **W03 Independent oracle/role isolation** | G1 | Restricted scorer, priced check tool, signed/hashed artifact and role-scoped session | Known-good/known-bad tests, no-oracle-leakage unit/integration test | W02 |
| **W04 Structured events and reproducibility** | G1 | Event JSONL, outcomes CSV, manifest, all exceptions | Schema validator, replay same seed, no secret material | W03 |
| **W05 Real local LLM pilot** | G1 | Optional real model worker/auditor, bounded tools and time | Actual model decisions and tool calls logged; separate from scripted controls | W04 |
| **W06 ERC-8183 local EVM** | G2 | Pinned native contract, fake token/chain, adapter | Success/reject/timeout/refund/wrong-role state+balance receipts | W04 |
| **W07 Fixed-decision ERC-8183 replay** | G2 | Same sampled auditor verdict, with/without application evidence guard | Same pre-state snapshots, raw tx evidence + statement about native vs app | W06 |
| **W08 x402 native loopback** | G3 | Official v2 SDK/facilitator local flow | Real scheme-valid authorization, verify/execute/settle, negative tests | W04 |
| **W09 Cross-flow consequence pilot** | G3 | Frozen same task/verdict on one escrow and one HTTP payment **where semantically legitimate** | Native state/receipt comparisons; no global ranking | W07,W08 |
| **W10 Economic offers and 2×2×2** | G4 | Randomized relationship/scarcity/persuasive evidence study with real agent | All 8 arms, correct assignment unit and positive/null controls | W05,W09 |
| **W11 Longitudinal agent marketplace** | G4 | Repeated agent identities, bid and auditor assignment, real ledger history | Peer/random/turnover/communication/crossover counterfactuals | W10 |
| **W12 Coordination metric adapter** | G4 | Colosseum action-based methodology adapted to explicit financial objective | Unit fixtures separating joint independent error and coordinated gain | W11 |
| **W13 Defense frontier** | G5 | Protected-budget, evidence bound, independent assignments, spot checks | Balanced cost, bad-paid & good-unpaid, CI and latency | W10–W12 |
| **W14 MPP charge/session native** | G6 | Official HTTP flow(s), local/mocked provider only if permitted SDK | Native credentials/validity tests; no 'native' on mock HMAC | W09 |
| **W15 AP2 v0.2 native** | G6 | Official SDK sampled mandate/authorization flows | Signed mandate fields, scope, valid/invalid authorization | W09 |
| **W16 Virtuals ACP v2** | G6 | Maintained `acp-node-v2` adapter or precise SKIP | SDK event-driven job role tests/test credentials and events | W06 |
| **W17 ACP/OpenAI–Stripe, UCP, A2A, ERC8004** | G6 | Spec-appropriate composed tests | Individual version pins, state and role invariants, SKIP where blocked | W14–W16 |
| **W18 Broad task/model generalization** | G7 | ORBIT task family + optional AgentDojo/AgenticPay realism | Data/source license verified, blinded oracle, independent evaluation | W10–W17 |
| **W19 Preregistered confirmatory run** | G7 | Frozen analysis plan + capacity/budget | Power analysis from real pilot, preregistration, no result-peeking | W18 |
| **W20 Final results/manuscript** | G8 | Reproducible figures/tables, limitations and paper | Every numerical claim linked to frozen evidence+script and correct tier | W19 |

## Work order template

Every work report must include:

```text
Work ID:
Source commit(s) + dependency lock:
Execution tier model / payment:
Command(s) actually run:
Tests PASS / FAIL / SKIP and reasons:
Delivered paths:
Threat-model assumptions:
Confounds and known limitations:
Evidence that protocol was native (or explicit MOCK):
Backwards compatibility or migration:
Decision or owner approval required:
Next eligible work order:
```

## Branch discipline

One branch or reviewable patch per work order. Do not rewrite `legacy/` or vendor entire third-party repositories. Keep `.env.example` safe. No test passes merely because a mocked return was substituted for an actual missing SDK.
