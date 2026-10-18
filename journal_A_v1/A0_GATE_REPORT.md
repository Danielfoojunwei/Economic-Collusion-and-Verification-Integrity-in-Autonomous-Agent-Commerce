# Paper A A0 preparation gate — 18 October 2026

**Overall: PARTIAL / NOT RELEASED.** No new LLM calls or local native payment experiment ran. No prospective assignment is frozen, no confirmatory result exists, and the historical billing hold remains unchanged. This report distinguishes new offline design checks from older MPP010 evidence.

## What ran

From repository root, with `PYTHONPATH=src` and the existing pinned ORBIT/Inspect virtual environment:

```text
../upstreams/orbit-smoke/.venv/bin/python -m unittest \
  tests.test_journal_a_v1 tests.test_journal_a_schema \
  tests.test_journal_a_task_gate tests.test_market_assignment \
  tests.test_mpp010_offline_native -v
```

**Result: 27 tests, 25 passed, two skipped.** The two skips require historical isolated Tempo chains that are no longer running. The new Paper A tests cover integer compensation arithmetic and funding floor, exact-message comparison on normalized synthetic serialized requests, assignment-missingness bounds, synthetic null/effect/sign reversal, schema validity and negative cases, and identical GOOD/BAD public booking presentation with protected-oracle PASS/FAIL. Existing market-assignment and MPP010 offline tests provide regression coverage, not Paper A native validation. A first attempt omitted `PYTHONPATH=src` and failed to import the existing package; rerunning with the repository's documented source path passed. Direct arXiv requests for the two newly named closest papers returned HTTP 403; their full texts remain unverified.

## Gate status

| Subgate | Status | Evidence and remaining test |
| --- | --- | --- |
| A0.1 Task | **PARTIAL PASS** | Existing synthetic booking has identical public GOOD/BAD views and an independent PASS/FAIL calendar oracle; tested. Still inspect actual prospective model requests, IDs, balances, and message lengths for truth leakage. |
| A0.2 Exposure | **PARTIAL PASS** | [Exact-field helper](exposure_join.py) rejects withheld/exposed mismatch, altered message, system-role copy, and postdecision exposure in synthetic requests. It has not yet consumed raw ORBIT/Inspect requests under a frozen Paper A assignment. |
| A0.3 Money | **NOT RUN for Paper A** | The [schedule helper](compensation_schedule.py) verifies integer pay/refund identities and check affordability. No new prefunded native flat/contingent ledger, check, timeout, or refund was executed. Historic MPP010 charge evidence is not a substitute. |
| A0.4 State | **NOT RUN for Paper A** | Existing market tests cover some assignment identities; fresh Paper A duplicate, stale-proof, wrong-obligation, crash/recovery, and atomic release controls remain. |
| A0.5 Models | **NOT RUN** | No benign capability calls or model selection were performed. Exact routes, provider versions, context/output cap, and budget must be frozen after an authorized nonconfirmatory pilot. |
| A0.6 Analysis | **PARTIAL PASS** | Synthetic contrast means and assigned-outcome bounds recover null, effect, reversed sign, and missing-outcome extremes. Valid design-based interaction tests, Holm procedure, cluster interval, and realistic power simulation have not yet been implemented or validated. |

## Evidence and handover

**Source anchor:** remote `main` is `bce0dc982a4458d1dc2910b9b63ccbbe8c91f9ff`; the current working branch additionally contains the later canonical paper and exploratory manuscript commits. The old ORBIT005 native case remains historical exploratory evidence, not a row in this design. The draft [protocol](PROTOCOL.md), [claim registry](CLAIM_REGISTRY.json), [assignment template](ASSIGNMENT.template.json), [record schema](episode_record.schema.json), and [closest-work delta](RELATED_WORK_DELTA.md) have no observed endpoints.

**Independent verifier:** none has independently reconstructed a new Paper A native result; none exists. Unit test success is not such verification. The next engineering slice is Paper A native prefunding/check/release/refund plus a separate read-only receipt/balance verifier, followed by raw request exposure preflight and a nonconfirmatory benign model capability pilot. Only after A0 passes should a complete model/budget/seed assignment be sealed and the owner execution gate considered. No paid call is authorized by this report.
