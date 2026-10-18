# Paper A A0 preparation gate — 18 October 2026

**Overall: PARTIAL / NOT RELEASED.** A fresh zero-model local native A0 control and a bounded zero-price benign model capability pilot ran. Neither is a confirmatory behavioral experiment. No prospective assignment is frozen; the historical positive-price billing hold remains unchanged. This report distinguishes the new controls from the older MPP010 evidence.

## What ran

From repository root, with `PYTHONPATH=src` and the existing pinned ORBIT/Inspect virtual environment:

```text
../upstreams/orbit-smoke/.venv/bin/python -m unittest \
  tests.test_journal_a_v1 tests.test_journal_a_schema \
  tests.test_journal_a_task_gate tests.test_journal_a_native_a0 \
  tests.test_market_assignment \
  tests.test_mpp010_offline_native -v
```

**Result: 29 tests, 27 passed, two skipped.** The two skips require historical isolated Tempo chains that are no longer running. The new Paper A tests cover integer compensation arithmetic and funding floor, exact-message comparison on normalized synthetic serialized requests, assignment-missingness bounds, synthetic null/effect/sign reversal, schema validity and negative cases, identical GOOD/BAD public booking presentation, and read-only native receipt tampering. Existing market-assignment and MPP010 offline tests provide regression coverage. A first attempt omitted `PYTHONPATH=src` and failed to import the existing package; rerunning with the repository's documented source path passed. Direct arXiv requests for the two newly named closest papers returned HTTP 403; their full texts remain unverified.

The [fresh local A0 control](../artifacts/exploratory/JOURNAL_A0_NATIVE_2026-10-18_002/evidence.json) completed five scripted cases and 37 native local TIP-20 transactions: three MPP charged calendar checks, one correct GOOD release, one deliberately permissive BAD release, a strict BAD release block, a BAD rejection, base/conditional compensation and timeout refunds. Every case prefunded the same 18-unit economic reserve before its scripted decision. A [separate read-only reviewer](../artifacts/exploratory/JOURNAL_A0_NATIVE_2026-10-18_002/independent-review.json) fetched the receipts and historical balances, decoded each transfer, checked saved MPP challenge/credential binding, and matched all 37 transfers. Six tamper classes were rejected by the reviewer test. The application’s wrong-task/stale/FAIL and duplicate guard checks were asserted in the runner; they are not independently replayed native state transitions. Gas reserves were provided separately from the modeled 20-unit check budget. This is no evidence of model collusion or a production payment. Initial development runs failed on the pinned image’s required block-time unit, insufficient local gas funding, and an incorrect negative expectation for the deliberately permissive rule; those were repaired on fresh chains before the archived control. The current source hash is bound in the archived evidence.

The [benign zero-price model pilot](../artifacts/exploratory/JOURNAL_A_CAPABILITY_2026-10-18_001/summary.json) indexed five of six planned tool calls: four complete, one technical failure, one unattempted. Three complete calls matched their tool schema exactly. The Dots model, acting as provider in the prespecified role reversal, submitted the wrong booking ID despite calling the tool; Gemma 4 31B hit a transport error. There were no retries or alternate routes under that plan. All four complete response envelopes reported USD 0; the read-only account counter was `4.0299155` before and after. Requested high reasoning and reported reasoning-token counts show route settings and usage, not good judgment. No booking or native payment was executed in this pilot.

## Gate status

| Subgate | Status | Evidence and remaining test |
| --- | --- | --- |
| A0.1 Task | **PARTIAL PASS** | Existing synthetic booking has identical public GOOD/BAD views and an independent PASS/FAIL calendar oracle; tested. Still inspect actual prospective model requests, IDs, balances, and message lengths for truth leakage. |
| A0.2 Exposure | **PARTIAL PASS** | [Exact-field helper](exposure_join.py) rejects withheld/exposed mismatch, altered message, system-role copy, and postdecision exposure in synthetic requests. It has not yet consumed raw ORBIT/Inspect requests under a frozen Paper A assignment. |
| A0.3 Money | **SCRIPTED LOCAL PASS; confirmatory path pending** | The [schedule helper](compensation_schedule.py) and five-case native control exercise predecision reserve, MPP check, approval/rejection/timeout, refund and buyer release on valueless local assets. Independent read-only transfer/balance reconstruction passed. This is not an LLM-selected payment or a contract-enforced escrow. |
| A0.4 State | **PARTIAL PASS** | Scripted wrong-job, stale-version, FAIL-proof and duplicate release guards; independent receipt reviewer detected amount/payee/hash/case/MPP tampering. Interrupted write recovery, concurrent release and alternate release route remain untested. |
| A0.5 Models | **PARTIAL / failed routes retained** | Five zero-price benign calls indexed; one Dots provider tool error, one Gemma transport stop, one unattempted. The prespecified role-reversal/three-configuration capability threshold was not met; model selection and exact source/version freeze remain pending. |
| A0.6 Analysis | **PARTIAL PASS** | Synthetic contrast means and assigned-outcome bounds recover null, effect, reversed sign, and missing-outcome extremes. Valid design-based interaction tests, Holm procedure, cluster interval, and realistic power simulation have not yet been implemented or validated. |

## Evidence and handover

**Source anchor:** remote `main` is `bce0dc982a4458d1dc2910b9b63ccbbe8c91f9ff`; the current working branch additionally contains the later canonical paper and exploratory manuscript commits. The old ORBIT005 native case remains historical exploratory evidence, not a row in this design. The draft [protocol](PROTOCOL.md), [claim registry](CLAIM_REGISTRY.json), [assignment template](ASSIGNMENT.template.json), [record schema](episode_record.schema.json), and [closest-work delta](RELATED_WORK_DELTA.md) have no observed endpoints.

**Independent verifier:** the new read-only native reviewer independently reconstructed scripted local transfers and balances, not a live-model research result. The next slice is raw ORBIT request exposure, interrupted-write/concurrency controls, complete benign model configuration selection, and valid design-based analysis with power simulation. Only after A0 passes should a complete model/budget/seed assignment be sealed and the owner execution gate considered. No positive-price call is authorized by this report; the USD 50 ledger retains zero positive-price headroom.
