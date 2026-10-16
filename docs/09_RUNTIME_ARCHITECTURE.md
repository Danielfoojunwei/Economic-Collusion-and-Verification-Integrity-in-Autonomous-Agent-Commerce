# 09 — Reuse-first runtime architecture and migration plan

## Core decision: ORBIT, not a new bench

From official ORBIT release, its extension uses Inspect AI `Task` (native dataset/scorers/tools), independent agent conversations, scheduling and channel access rules. ORBIT's current README describes `multi_agent_task` for constructing tasks. It warns `pip install orbit` installs a different package. **Codex must inspect the actual installed API before choosing import paths.** Colosseum runs on a Terrarium/CoLLAB stack; we should port *metrics or experiments* into ORBIT interfaces rather than trying to run two orchestration loops simultaneously.

## Proposed thin project hierarchy after Codex implementation

```text
src/agent_economic_trust/
  orbit_tasks/              # native ORBIT/Inspect Task factories wrapping reused tasks
  agent_roles/              # worker, verifier, payment-requester roles and authority gates
  economics/                # ledgered offers, deposits, costs, market relationship assignment
  protocols/                # native adapters: erc8183/, x402/, mpp/, ap2/, virtuals_acp/ etc.
  verification/             # task-bound receipt, checker tool, authorized evidence access
  interventions/            # randomization, persuasive text, scarcity, memory/assignment
  scoring/                  # independent oracle, falsity, payment, coalition, cost outcomes
  provenance/               # manifest and append-only events
experiments/
  local_smoke.yaml
  factorial_r_s_p.yaml
  market_longitudinal.yaml
  native_protocol_replay.yaml
  defenses_fixed_budget.yaml
adapters/
  upstream_orbit/           # wrappers only; do not copy framework
  colosseum_metrics/       # adapted calculation with citations/tests
scripts/
  run_local_smoke.sh
  verify_results.py
  freeze_release.py
artifacts/                    # generated, ignored in git; gate-separated
```

The file tree is **a suggested output**, not already existing code. Avoid unnecessary files for features not yet implemented.

## Agent isolation

- Independent agent sessions, separate prompts/model configurations/memory state; *do not* share hidden oracle module into model-accessible namespace.
- Role-scoped tools: Worker can submit work; Auditor can purchase check and issue verdict; Payment agent can propose authorized transactions but cannot access signing keys; settlement adapter cannot alter task oracle.
- Communication topology configured through ORBIT's available channel/scheduler primitives. Restricted messages are prevented at runtime, not just described in prompts.
- All coding tasks in bounded containers with network off, quotas and sanitized test data.
- Repeat relationships are stored in a history service and visible only under declared memory visibility policy.

## Adapter architecture

Define *minimal* typed interface conceptually:

`initialize(contract, principals)`, `authorize(intent)`, `submit(artifact)`, `record_audit(evidence, verdict)`, `attempt_payment(policy)`, `advance_time(delta)`, `observe_events()`, `get_balances()`, `reset(snapshot)`, `close()`.

**Not every protocol supports every method.** Return declared capability/NOT_APPLICABLE rather than faking a contract feature. Actual interfaces must reflect native implementation.

## Keep what v0.2 already has

| Legacy file | Content worth reusing | Restriction |
|---|---|---|
| `paidaudit/tasks.py`, `study_tasks.py` | Ten baseline tasks and oracle fixtures | Recalibrate/extend into ORBIT tasks; do not leak private truth |
| `paidaudit/model.py` | Ledger/event fields, digest, trial records | Integrity hash is **not** a cryptographic signature |
| `paidaudit/study.py` | Frozen-case matched replay and row/csv formatting | Scripted agents and mock settlement mean no LLM/native results |
| `paidaudit/study_stats.py` | Factorial contrasts, bootstrap and task reliability | Need actual unit-of-randomization and power analysis |
| `paidaudit/policies.py` | Always-accept, truthful and economic scripted positive/negative controls; optional loopback contract | Do **not** use coefficients as real effect sizes |
| `paidaudit/wiremock.py` | Loopback HTTP shape checks | HMAC is not x402/MPP native scheme signature |
| `configs/...` | Initial case catalogs | Rewrite to ORBIT format only after real API inspection |

Never copy `paidaudit/protocols.py` and rename it `native_erc8183.py`; it contains simplified local state machines, not implementation evidence.

## Integration sequence and fallback

A. Verify upstream ORBIT release, env, wheel hashes and Inspect compatibility. B. Construct single native task; C. add checker tool and independent oracle; D. real local LLM; E. native escrow; F. native x402; G. other protocols; H. longitudinal and full factorial.

If ORBIT genuinely fails to run because of dependencies or unavailable release, implement smallest **Inspect-only** compatible Task and record `BLOCKED_ORBIT` with direct logs; do not claim ORBIT has been exercised. The absence of an integrated upstream task family should not block the first local pilot.

## Ownership boundaries

Reuse original frameworks as external dependencies, respecting licenses and version pins. The new code owns only economic logic, integration glue, user-domain tasks, results and analysis. A protocol-novel extension belongs in its own explicitly labelled module with separate citations.
