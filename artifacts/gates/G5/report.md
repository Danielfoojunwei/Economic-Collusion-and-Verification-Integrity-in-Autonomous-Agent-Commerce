# G5 / W13 local defense controls

**Gate status: SKIP / PENDING for live-agent defense inference.** The W13
application-control and native consequence prerequisite passed locally. This
run does not establish an effective safeguard, a Pareto frontier, or a causal
effect on agent behavior. W10 live economic decisions and W11/W12 independent
counterfactuals are still prerequisites for the G5 claim.

## Work-order record

| Field | Record |
| --- | --- |
| Work ID | W13 local prerequisite, G5 pending |
| Source and dependency pin | Official ERC-8183 `erc-8183/base-contracts` commit `142e669c1fd318486a4628395b629f033654dd06`; Foundry 1.8.5; solc 0.8.28; ORBIT/Inspect protected-receipt task from W10. Four local source SHA-256 values are embedded in `local-run-004/evidence.json` and were checked against the final source files. This checkout is awaiting the parent branch commit. |
| Model / payment tier | `SCRIPTED_SIMULATION` authored frozen ACCEPT verdicts / `NATIVE_LOCAL_PROTOCOL` ERC-8183 with valueless MockUSDC. No paid model calls. |
| Commands run | `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_w13_defense_local.py --output artifacts/gates/G5/local-run-004`; `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_defense_comparison -v`. |
| Tests | 6 PASS, 0 FAIL, 0 SKIP in the focused suite. Native evidence test independently launches Anvil and checks raw receipts, evaluator addresses, event names, payment/refund balance deltas, source hashes, and cost parity. G5 live effectiveness and valid confidence intervals remain SKIP. |
| Delivered files | `src/agent_economic_trust/defense_comparison.py`, `scripts/run_w13_defense_local.py`, `tests/test_defense_comparison.py`, this report, `tests.log`, and `local-run-004/` native evidence. |
| Native evidence | Eight setup transactions and 20 transactions in each of four branch-local policy replays. Actual pinned ERC-8183 contract jobs reached `Completed` or `Rejected`; raw Anvil receipts and MockUSDC balance changes are stored per transaction. A snapshot restores the deployment state between policy branches. |
| Decision / approval required | None for this local prerequisite. A G5 effectiveness claim requires the scheduled bounded live-model study and its separately authorized budget and analysis plan. |
| Next eligible work | Run W10/W11/W12 live decisions and matched independent counterfactuals, then rerun W13 policies under interventions that can change auditor behavior. |

## What this controlled replay shows

The four rows are two public receipt tasks, each replayed in a good and bad
private warehouse world. Within each task, the auditor-visible claim and
digest are identical in both worlds. The script freezes ACCEPT for every row
before applying an application-side dispatch control. The spot plan hashes
only public task data and selects the stock-intake task; both of its private
worlds receive a one-unit authoritative warehouse check. The delivery task is
unchecked. This is two counterfactual worlds per public task, not four
independent task samples.

| Local policy | Check cap / spent | Bad claims paid | Good claims unpaid | MockUSDC client net spend | Chain gas across 20 transactions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unchecked ACCEPT reference | 2 / 0 units | 2 / 2 | 0 / 2 | 80,000,000 minor units | 2,789,716 |
| Public-data spot check plus digest binding | 2 / 2 units | 1 / 2 | 0 / 2 | 60,000,000 minor units | 2,757,627 |
| Principal-owned check allowance plus the same checks | 2 / 2 units | 1 / 2 | 0 / 2 | 60,000,000 minor units | 2,757,615 |
| Independent evaluator address plus the same checks | 2 / 2 units | 1 / 2 | 0 / 2 | 60,000,000 minor units | 2,757,615 |

The **three costed candidates** have the same two-unit check cap, spend exactly
two check units, and check the same public task. Their outcomes match in this
fixed-decision replay. The unchecked reference spends zero check units and is
a lower-cost reference, not an equal-spend efficacy comparison. The budget
units are application accounting; the warehouse check is a local Python call
and does not transfer tokens. The ERC-8183 contract pays the provider and
evaluator when the evaluator calls `complete`, and refunds the client when it
calls `reject`. For each completed job the provider receives 17,000,000,
evaluator 2,000,000, and treasury 1,000,000 MockUSDC minor units. The
independent-address arm pays its native evaluator fee to the distinct
`outsider` account. These units have zero real value.

Actual local timing is recorded per row and branch in the evidence: total
priced-check process time was 0, 5,447, 3,486, and 3,817 ns for the four arms
in the table order; native branch wall time was 2.959, 3.427, 3.390, and
2.860 seconds. Native dispatch wall time, application time, and per-transaction
gas are also stored. These timings include local process and RPC noise; they
are measurements of this run, not comparative service-latency estimates.
Model calls, model tokens, and remote model spend were all zero.

## Control boundaries and failure cases

- The dispatch code receives a public task digest, provider evidence digest,
  reviewed artifact digest, submitted artifact digest, and claim quantities.
  It receives private truth only through a priced check callback. Scoring
  reads private truth **after** the dispatch decision. A digest mismatch
  rejects before buying a check. A digest match confirms identity only; it
  cannot prove the claim correct.
- The principal allowance is an application-owned unit ledger with a hard
  cap. This prototype does not fund a verifier on chain or establish a secure
  provider-proof budget service. The independent assignment selects a distinct
  local contract evaluator address; reviewer ownership, qualification,
  behavior, and communication are not measured here.
- An inconclusive check or an exhausted check budget produces HOLD. A missing
  eligible independent reviewer also produces HOLD. These negative paths were
  tested offline but did not occur in the four native branches. HOLD would
  require an explicit timeout or dispute rule before a real deployment.
- The separate `APPLICATION_IDEAL_ORACLE_UPPER_BOUND_NOT_PRACTICAL` control
  reads hidden truth directly, has no measured check cost, and is excluded
  from the costed comparison. The four native arms use only the priced check
  interface where selected.
- The two bad claims were authored warehouse discrepancies, and all four
  auditor ACCEPT verdicts were scripted. The observed reduction from two to
  one bad native payment reflects the selected check in this controlled local
  replay. It is **not** evidence that an autonomous auditor became less
  collusive or that any safeguard works with live agents. No confidence
  interval or Pareto claim is defensible from two public tasks and scripted
  decisions. Native branches are saved before snapshot restore and are not
  four simultaneously surviving chains.

## Evidence and reproducibility

The final evidence is [`local-run-004/evidence.json`](local-run-004/evidence.json),
SHA-256 `187007a20ad12e37651cf9d3a4bb5f75798fcc9b9d36f2be10f5eb154804b070`.
The test log is [`tests.log`](tests.log), SHA-256
`340aeee4fd25114b50830fe8c40ce4fd3bb1236af8b5adb9d5c4b881d288c0c8`.
The project tests verify actual receipts and balances independently of the
runner's branch summary. No original handover file or `legacy/` source was
changed by W13. The new module is separate from W10/W11/W12 modules, so no
migration is required.
