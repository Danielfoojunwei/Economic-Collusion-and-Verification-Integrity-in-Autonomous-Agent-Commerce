# BILATERAL030 planner and analysis: independent source review

Reviewed commits: `842633c` (prospective planner and analysis) and `737abad` (WAIT alignment and publication gate). This is a review of source and synthetic fixtures, not a review of completed model episodes.

## Result

**GO for source-only planning and analysis diagnostics. HOLD for scientific inference or publication.** From the repository root, with `OPENROUTER_API_KEY` unset and external calls disabled, I independently ran:

```text
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest tests.test_bilateral030_analysis tests.test_bilateral030_plan -q
Ran 16 tests — OK
```

The planner creates 15 anonymous slots per role direction and assigns fixed arm counts through a separate seed-driven permutation. Given a prospectively sealed assignment and no cross-row interference, the complete 30-row schedule supports the stated conditional blocked randomization analysis. The implementation enumerates 36 × 36 = 1,296 conditional allocations. It retains all assigned rows in the denominator, withholds permutation p-values when any row is incomplete, and does not count STOPPED or missing outcomes as negative observations. Descriptive confidence intervals are model-based rather than randomization intervals.

The analyzer's non-WAIT receipt fields match the current local bridge schema. The corrected WAIT branch requires the bridge's `WAIT_NO_CLAIM` receipt and rejects a WAIT transaction. It also keeps induced auditor stress distinct from spontaneous bilateral assent. Result objects explicitly say `SOURCE_ONLY_UNVERIFIED_REVIEWS`, `HOLD_EXTERNAL_AUDITED_REPLAYER_AND_SOURCE_SEAL_PENDING`, and `ALGORITHM_DIAGNOSTIC_NOT_PUBLISHABLE_FROM_THIS_CLI`.

## Remaining evidence boundary

The analyzer reads caller-supplied `independent_checks` booleans. Its tests intentionally supply synthetic receipts and review flags; passing tests do not authenticate raw Inspect model calls, delivery of contact text, first-claim ERC-8183 receipts, private oracle timing, model-authored assent, billing, or pre-outcome assignment/source sealing. An external audited replayer must verify these against immutable raw artifacts, and all 30 assigned rows must be complete before inferential claims. The budget ledger currently does not permit hosted execution. No live bilateral collusion result follows from this source review.
