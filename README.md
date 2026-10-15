# When Agents Pay Their Auditors — Codex Research Handover

**Working paper title:** *When Agents Pay Their Auditors: Economic Collusion and Verification Integrity in Autonomous Agent Commerce*

**Date:** 2026-10-15 (Singapore)  
**Status:** RESEARCH BUILD PLAN + ARCHIVED OFFLINE SIMULATOR; native integrated study **NOT YET IMPLEMENTED**.  
**Objective:** Produce a publishable **causal empirical systems-security paper**, not a new benchmark marketed as the scientific contribution.

## What changed

Old scope: invent and maintain **PaidAuditBench** as an independent general-purpose benchmark.  
**New scope:** reuse **ORBIT on Inspect AI** as the primary multi-agent runtime, **Colosseum** as an action-based collusion-method reference, **AgentDojo / ORBIT's existing coding and task environments** for realistic tasks, and **official payment implementations** for real transaction-state evidence. Write only the **thin integration, event instrumentation, economic interventions, and analysis** required to answer the research questions.

Do **not** rewrite ORBIT, Colosseum, AgentDojo, or a payment SDK. Do **not** present the prior 84,480 scripted local trials as measured LLM collusion or native SDK conformance.

## For Codex — start in this order

1. Read `START_HERE.md` and `AGENTS.md` (operational boundaries and file map).
2. Read `CODEX_MASTER_PROMPT.md` and then `planning/FIRST_48_HOURS.md`.
3. Execute only the first work order in `planning/WORK_ORDERS.md`; review gates in `planning/STAGE_GATES.md` before proceeding.
4. Inspect archived source in `legacy/paid-audit-bench-v0.2-source/` **as a read-only reference**. Run its tests to establish an unchanged baseline.
5. Fetch and pin official ORBIT and Colosseum repositories, inspecting their actual APIs and licenses before writing adapters. Source register: `docs/16_UPSTREAM_SOURCE_REGISTER.md`.
6. Create a small runnable **ORBIT/Inspect task** that invokes one worker, one auditor, one mock settlement, and an independent scorer. Then add **native ERC-8183** and **native x402** in separate gated work orders.

## Package map

| Location | Purpose |
|---|---|
| `CODEX_MASTER_PROMPT.md` | One block to paste to Codex. |
| `AGENTS.md` | Persistent rules for Codex working in this repository. |
| `docs/01_...18_...md` | Paper plan, hypotheses, methods, protocols, tasks, analysis, research evidence. |
| `planning/` | Ordered implementation work orders, acceptance tests, and decision/stop gates. |
| `configs/` | Declarative examples for local runs; examples are **not** claimed runnable ORBIT config until validated. |
| `schemas/` | Proposed versioned event/run JSON Schema for Codex to implement. |
| `scripts/` | Handover self-check and optional upstream bootstrap helper. |
| `inputs/From chat collusion to bribes.pdf` | Original preliminary research source; not evidence for the new study. |
| `legacy/paid-audit-bench-v0.2-source/` | **Unmodified** earlier Python simulator source, tasks and existing tests. |
| `legacy/results-summary/` | Earlier simulation-only summaries/manifests. |
| `legacy/raw-results/PaidAuditBench_v0.2_results_full.zip` | Original compressed event traces, preserved for provenance; decompress only as needed. |

## Reproducibility baseline

```bash
python scripts/validate_handover.py
cd legacy/paid-audit-bench-v0.2-source
python -m unittest discover -s tests -v
python -m paidaudit wire-smoke
```

These commands validate the **handover and old simulation**, not the proposed live-agent research. New native integration commands must be written, tested and documented by Codex as each work order is completed.

## Hard scientific boundaries

- Economic inducement != demonstrated collusion. Joint error != coordination. Signed receipt != semantic correctness.
- Treat ORBIT/Inspect, Colosseum, and protocol libraries as third-party; do not vendor their source until license and commit provenance are verified.
- Distinguish: `SCRIPTED_SIMULATION`, `REAL_LLM_LOCAL`, `NATIVE_LOCAL_PROTOCOL`, `NATIVE_TESTNET`, and `PRODUCTION` (production experiments forbidden for this project).
- No mainnet funds, commercial wallet credentials, real counterparties, payment-card charging, production exploit traffic, or private data.
- No cherry-picked traces, no inferred results from text, no invented claim of novelty, and no infinite paid API runs.

For the exact published provenance of the old simulations, see `legacy/paid-audit-bench-v0.2-source/docs/VALIDATED_RESULTS_V02.md`.
