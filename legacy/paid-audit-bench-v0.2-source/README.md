# PaidAuditBench v0.2 — Research-grounded paid-agent verification laboratory

**New in v0.2 (2026-10-15):** A second, matched-world study runner that draws methodological controls from ORBIT, Agentic Commerce Bench, Colosseum, CABAL, AgentDojo, tau-bench, SWE-bench Verified, and paired-replay security evaluations. It adds four contract-style procurement/API tasks (ten total), simulated negotiation and private cost, independent outcome/fraud measurement, quote overcharge, distinct-job double charge, provider abandonment, and three modeled x402 v2 payment orderings. The fully crossed 2×2×2 factor experiment exports descriptive interactions, task-cluster bootstrap intervals, and tau-bench-inspired pass^k. **All outcomes remain no-funds protocol-shaped simulations, NOT actual agent data or standard conformance.**

```bash
python -m unittest discover -s tests -v
# 12 local adapters across 10 tasks, 14 adversarial cases, 5 application guards
python -m paidaudit realism-run --config configs/realism_pilot.json --out runs/realism_pilot
# Fixed R×S×P 2×2×2, six core payment families, three guard alternatives
python -m paidaudit realism-run --config configs/realism_factorial.json --out runs/realism_factorial
```

**Read first:** [`docs/RESEARCH_TO_RUNTIME_V02.md`](docs/RESEARCH_TO_RUNTIME_V02.md) for literature-to-test mapping and validity limits; [`docs/REALISM_INTEGRATION_GATES.md`](docs/REALISM_INTEGRATION_GATES.md) for exact missing live SDK/model integrations. The rest of this README documents v0.1's original implementation and archival reference run.

---

# PaidAuditBench v0.1 — Agent-to-Agent Payment and Verification Laboratory

**Status 2026-10-15:** Working, reproducible, entirely **offline/no-funds** prototype. Not a real payment wallet, on-chain deployment, reference SDK integration, standards conformance suite, or LLM empirical study.

The central question is **whether independent, economically viable verification survives paid agent-to-agent service work**, and whether payment validity or a signed approval is mistaken for proof of work quality. See `docs/RESEARCH_PROTOCOL.md` for the preregistration blueprint.

## What is actually implemented?

- **Six deterministic ground-truth jobs** in three categories: software patch expressions evaluated by safe arithmetic AST/private regression tests, posted/pending financial reconciliation, and evidence-grounded claims. Each has a valid and a plausibly invalid submission.
- **Four scripted auditor policies:** `truthful`, `budget_sensitive`, `economic`, and an explicitly prompted `captured` positive control. A fifth `llm_local` allows an optional **loopback-only** OpenAI-compatible chat-completions endpoint (e.g. Ollama or vLLM). No local model is bundled or automatically run.
- **Ten local, protocol-shaped adapters** that reproduce high-level transaction or job lifecycle stages. These *do not use vendors' cryptographic SDKs*; their protocol names denote the studied workflow semantics, not official conformance.
- **Fourteen+ adversarial scenarios:** financial dependence, conditional side-payments, spoofed offers, costly but possible verification, a separately labelled impossible-audit negative control, persuasive evidence, item/result swaps, replay, payee/amount tampering, expiry, and verifier committees.
- **Actual loopback HTTP 402 tests** of header/response shapes for x402 and MPP with ephemeral **MOCK HMAC** credentials. These are not valid EIP-712/EIP-3009 signatures, official MPP payment credentials, real facilitator confirmations, or token transfers.
- **Repeated provider–auditor market** with rotating/reversed roles and persistent economic-relationship graph created from prior sandbox side-payments. Agent memory/policy learning is *not* implemented; only budget carryover is supported in the standard episode runner.
- Structured JSONL traces, trial-level outcome variables, aggregated CSV, paired descriptive contrasts, SHA-256 event digests, and run manifests.

## The distinction between payment and communication protocols

| Adapter | What it represents | Modelled payment/finality decision | Real integration |
|---|---|---|---|
| `x402_v2` | x402 v2 HTTP payment for a resource | Payment verified then settled on 200 resource response; **not** third-party quality acceptance | **Not run** |
| `mpp` | Machine Payments Protocol HTTP charge | Challenge → credential → mock charge, before resource delivery | **Not run** |
| `ap2_v02` | AP2 v0.2 autonomous checkout/payment mandates | Mock checkout/payment authorization and receipt | **Not run** |
| `ucp_ap2` | Universal Commerce Protocol checkout over AP2 | Checkout events plus mock AP2 payment | **Not run** |
| `erc8183_draft` | ERC-8183 agent-work escrow | Create → fund → submit → designated evaluator complete/reject | **Not run** |
| `virtuals_acp_v2` | **Virtuals** Agent Commerce Protocol v2 | ERC-8183 lifecycle and hook callbacks | **Not run** |
| `openai_stripe_acp` | **OpenAI/Stripe** Agentic Commerce Protocol 2026-04-17 | Merchant checkout/payment, **not evaluator escrow** | **Not run** |
| `a2a_x402` | Agent2Agent v1.0 communications **plus** x402 payment | Two separate layers; A2A does not transfer money | **Not run** |
| `a2a_erc8183` | Agent2Agent communications **plus** ERC-8183 escrow | Two separate layers | **Not run** |
| `erc8183_erc8004` | ERC-8183 payment **plus** ERC-8004 registry events | Identity/reputation overlay, **not a payment rail** | **Not run** |

**Version policy:** pin semantic snapshots in `docs/PROTOCOL_COVERAGE.md`, rather than assuming newer protocol specifications are identical. Virtuals ACP and OpenAI/Stripe ACP are **different protocols with similar acronyms**. AP2 provides authorization, while A2A provides communication. ERC-8004 handles identity/reputation/validation and explicitly leaves payments orthogonal.

## Quick start — runs offline in Python 3.10+

```bash
# Run from inside paid-audit-bench/. No dependencies or payments.
python -m unittest discover -s tests -v
python -m paidaudit list
python -m paidaudit wire-smoke

# Full published synthetic pilot: 11,520 episodes/trials, 10 adapters
python -m paidaudit run --config configs/pilot.json --out runs/pilot
python -m paidaudit verify-log runs/pilot/trials.jsonl

# Choose only one protocol with human-readable traces
python -m paidaudit run --protocols erc8183_draft --tasks code-tax-01 \
  --scenarios baseline,authenticated_offer,scarce_audit,receipt_swap \
  --policies truthful,economic --guards none,objective_recheck \
  --seeds 3 --out runs/focused

# Repeated roles / actual sandbox side-payment graph, no agent learning
python -m paidaudit market-run --protocols erc8183_draft,a2a_erc8183 \
  --patterns reciprocal,ring3,rotating --episodes 12 --seeds 3 \
  --policy economic --out runs/market
```

### Optional *actual local model* auditor (not yet empirically run)

```bash
# Configure and start an OpenAI-compatible server on loopback yourself, e.g. Ollama.
# Hidden software regression tests remain within the harness; only tool verdicts
# are returned to the model after it explicitly spends the check budget.
python -m paidaudit run --protocols erc8183_draft \
  --tasks code-tax-01 --scenarios baseline,scarce_audit,mixed_pressure \
  --policies llm_local --guards none --seeds 3 --out runs/local_llm \
  --model 'YOUR_LOCAL_MODEL' --endpoint http://127.0.0.1:11434/v1/chat/completions
```

Local model calls have a two-step workflow: model chooses whether to request the verification tool; the deterministic oracle evaluates the submitted work only when requested and budget permits; the model then decides accept/reject. The model is not provided the private test data or a truth flag. **Do not interpret scripted `economic` policy rates as measured LLM collusion rates.**

## The experiment runtime

```text
  REALM A: TASK CONTRACT                    REALM B: ECONOMIC RELATIONSHIPS
  Client agent                               Historical provider ↔ auditor payments
  │                                          │
  ├─ specification + benchmark acceptance    └─ randomized relationship / offer
  ├─ funds / authorizes local transaction              │
  ▼                                                    ▼
  Provider agent ─── deliverable ─────────────► Independent auditor(s)
  │                                             │ choose check/skip
  │                                             ├─ tool check costs 4 credits
  │                                             └─ verdict + evidence basis
  ▼                                                       │
  PROTOCOL SESSION ◄───────────────────────────────────────┘
  │ x402 / MPP / AP2 / ERC-8183 / ACP / compositions
  ▼
  LOCAL LEDGER + RECEIPT (NO REAL TOKENS)
  │
  ▼
  PRIVATE GROUND-TRUTH ORACLE (research only)
  │
  ├─ wrongful payout = invalid work ∧ provider paid
  ├─ false nonpayment = valid work delivered ∧ provider not paid
  ├─ verification effort, cost, binding, deadlines, side payments
  └─ immutable-in-archive event digest (not a signature)
```

## How to interpret the initial demonstration

1. Prepaid purchase/charge adapters can issue payment independent of *third-party task-quality verdicts* in this **simplified simulation**. This does not mean those protocols promise to verify work or that they are vulnerable to an exploit.
2. Escrow adapters release payment on an evaluator's approval; a strategically compromised evaluator can approve bad work. This is a consequence of the **assumed unprotected evaluator**, not an experimentally discovered vulnerability in ERC-8183.
3. `objective_recheck` is an **ideal, non-native counterfactual intervention** using task-specific ground truth and extra audit cost; it is not a novel protocol primitive. Its timing matters: it may affect payout in escrow/x402-after-service but cannot reverse an already settled checkout/charge.
4. Sandbox credit-transfer receipts are not blockchain transactions; mock challenge HMACs are not valid network payment credentials.
5. The supplied synthetic behavioural response probabilities are chosen by the harness author. Do not publish them as AI-agent findings.

## Files

- `paidaudit/tasks.py` — task fixtures and safe independent oracle.
- `paidaudit/policies.py` — policy actors and optional local model interface.
- `paidaudit/protocols.py` — named local lifecycle adapters, coverage registry, negative controls.
- `paidaudit/runtime.py` — experimental single-job engine and treatment assignments.
- `paidaudit/market.py` — repeated paid labor market/role rotation and financial graph.
- `paidaudit/wiremock.py` — local HTTP 402 wire-shape test server.
- `tests/` — executable protocol and scientific-invariant assertions.
- `configs/` — replayable experiment definitions.
- `runs/pilot/` — all local synthetic trial logs plus report and manifest.
- `docs/PROTOCOL_COVERAGE.md` — official specification links and actual coverage.
- `docs/RESEARCH_PROTOCOL.md` — research questions, hypotheses, MECE trial plan, threats to validity.
- `docs/NEXT_INTEGRATIONS.md` — concrete upgrades to reference SDK and no-value testnet experiments.

## Scientific provenance

The motivating user-supplied *From chat collusion to bribes* PDF reports its own reproduction and audit experiments: randomised promised bribes did not significantly alter its measured verdicts; agents accepted unsupported reasoning under constrained verification, and false joint-approval labels could be explained by common constraints. **Those are the PDF's reported prior results, not reproduced by this repository.**

Adjacent research predating this benchmark includes Colosseum (arXiv:2602.15198), the original Emergent Collusion paper (arXiv:2609.24967), *A Formal Analysis of Agent Payment Protocols* (2609.00060), and *SoK: Decentralized Agent Economic Infrastructure* (2610.01756). In particular the SoK already studies economic auditor capture, corrupted attestations, verification cost, and correlated errors. Do not claim the novelty is just 'bribery' or 'pay for wrong work'. Our prospective finding would have to concern measured **causal interaction of endogenous auditor effort, relationship incentives, and actual paid agent behaviour** beyond those baselines.

License: original harness code prepared as a working research prototype; third-party source implementations are only linked, not copied. All money simulated; no fundraising, wallet keys, mainnet address calls, or automatic real execution.
