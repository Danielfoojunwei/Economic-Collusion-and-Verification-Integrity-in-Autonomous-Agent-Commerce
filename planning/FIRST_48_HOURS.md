# First 48 hours — exact Codex execution order

These are sequential **work units**, not a promise of autonomous background execution. Complete only with actual tool actions and report blockers.

## 0–4h: inventory and freeze legacy reference (G0)

1. Run `python scripts/validate_handover.py` from package root.
2. Run `python -m unittest discover -s tests -v` in `legacy/paid-audit-bench-v0.2-source/`.
3. Run `python -m paidaudit wire-smoke` there; capture stdout/stderr, runtime, Python version, hashes and total tests.
4. Confirm legacy source unchanged via file digests; record no fake 'native' claims in report.
5. Inspect installed `python`, `uv`, `node`, `docker`, `forge`, `anvil`, `git`, `pytest` availability; classify uninstalled tools as blockers (do not synthesize outputs).
6. Write `artifacts/gates/G0/report.md` PASS/FAIL/SKIP and `upstream_versions.json`.

**PASS** only if package self-check + legacy source tests meet documented expectations, or clearly reported deviations exist (a failed legacy test means G0 not PASS).

## 4–12h: reuse-first upstream evaluation (G1 preparation)

1. Fetch `https://github.com/wlanderson0/orbit` and inspect the actual release/wheel/version & `multi_agent_task` example. Official GitHub sources only; `pip install orbit` forbidden.
2. Fetch Inspect AI compatible release, note pinned `uv.lock` or README constraint.
3. Fetch `https://github.com/umass-ai-safety/colosseum`, verify its tests/readme and whether metric reuse requires separate Terrarium (prefer formula adaptation and comparative baseline, no scheduler merge).
4. Create `UPSTREAM_PINNED.json` with SHA/license/actual source code availability. Include adverse or incompatible findings.
5. Choose one ORBIT coding or cooperative allocation task with deterministic objective verification, or adapt one archived toy task to native Inspect task if external data not fetchable.

**PASS** if real source inspection and an installable ORBIT runtime are documented. If not, mark `BLOCKED_ORBIT`, build minimal Inspect Task, and keep fallback clear.

## 12–24h: tiny real agent experiment (G1)

1. Create isolated worker and auditor roles through ORBIT/Inspect.
2. Give the auditor a priced `check` tool and an ACCEPT/REJECT action; log both independently.
3. The independent oracle resides behind a restricted scorer. Hidden labels never enter model prompts.
4. Add deterministic scripted controls (`always_accept`,`always_reject`,`truthful_tool_user`) only to validate instrumentation.
5. Add opt-in local LLM (model ID/endpoint from environment); if none exists, mark `REAL_LLM_LOCAL=SKIP` rather than fabricating.
6. Emit native Inspect event logs + `events.jsonl`, `outcomes.csv`, `run_manifest.json`, own costs, and errors.

**PASS** if one real ORBIT/Inspect episode completes and independent false-approval/check/scorer results can be verified from events. A mock only run passes integration plumbing but **not live-agent gate**.

## 24–48h: first native protocol gate (G2 preparation)

1. Install Foundry/Anvil if available, or record precise blocker.
2. Fetch/pin `erc-8183/base-contracts`, run upstream `forge test` untouched; record revision/ABI.
3. Deploy to local Anvil with fake ERC-20; create/fund/submit/complete/reject/expiry test cases, check balances and native logs.
4. Compose ORBIT frozen verdict with native evaluator role and separately label `application_receipt_guard` when used.
5. Produce at least one valid and one blocked/refunded native transaction trace under valueless assets.

**PASS** only with native contract receipts/balances and correct role/state checks; mock Python `Session` is not allowed evidence.

## End-of-period handover

Produce `artifacts/gates/G0-G2_status.md` listing commands, exact test counts, worker/verifier/payer authority, native source pins, provenance evidence, scoped failures, and whether model behavior was scripted or live. Wait for owner approval before remote paid calls or testnet expenditure.
