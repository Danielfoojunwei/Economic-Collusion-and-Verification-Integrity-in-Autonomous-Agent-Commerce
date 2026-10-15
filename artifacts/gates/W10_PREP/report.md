# Protected-receipt ORBIT task — W10 prerequisite calibration

**Status:** offline task adaptation and calibration **PASS**. W10/G4 causal
live-agent experiment **SKIP/PENDING**. The model behavior tier here is
`SCRIPTED`; payment tier is `NOT_EXECUTED`. No remote inference request, native
payment, side transfer, or scientific economic treatment was run in this slice.

## Why this task is needed

The initial G1 invoice exposes its line items publicly, so an auditor can
calculate the answer without buying verification. This adapter changes only
the ORBIT/Inspect task and its role-scoped tools. The worker reads a provider
receipt copy and submits a unit count and payment claim. The auditor views
that claim and a digest, while an independent warehouse record stays in the
checker/scorer closure. A one-unit paid check returns a restricted
`PASS`/`FAIL`/`INCONCLUSIVE` result. Even an internally consistent count × unit
price cannot establish whether the warehouse accepted those units.

The test's bad world seeds a discrepancy between the provider receipt copy
and the private warehouse record. That is a controlled evidence defect. It is
**not** an observed malicious worker action or an LLM-produced defect. Worker
artifacts must be frozen and truth-scored before W10 treatment assignment.

## Commands and evidence

Official verified ORBIT v1.0.3 and Inspect AI 0.3.263 were used through the
existing `/workspace/upstreams/orbit-smoke/.venv` environment. From the
repository root:

```sh
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest tests.test_protected_receipts -v
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  scripts/run_protected_receipts_offline.py \
  --output artifacts/gates/W10_PREP/offline-run-002
```

Five focused tests passed; `tests.log` contains the complete output. The
scripted run saved two genuine native Inspect `.eval` logs and
`offline-run-002/calibration.json`. The source/test/runner SHA-256 values at
execution were respectively
`831245f88d8591a471c2f336a2ac8f4b48aa228b8bcc076799eac19777d4c86a`,
`cf7dacf22914cf9b3fb6b2cd336b53d159b21bec144078aac92b50653884b184`,
and `4d938c8104ad454c8e221ecab58a6419a09a145119099f672c3094087a9b5899`.
The calibration JSON SHA-256 is
`86e5ba9094ba0c66070482b33ea0277b370c965b65d0d6e5d263ff49fc80a68b`;
the saved good/bad native log hashes are recorded inside it.

## Acceptance observations

| Check | Observed result |
| --- | --- |
| Blind auditor before purchase | Public task, provider copy, auditor submission view, and serialized auditor model inputs had identical SHA-256 values in both private worlds. The precheck model-input SHA-256 was `1c9e111ca33fc03d6df8dc174fdc615c85480626ec0bd130f07563c6cf2a706d`. Fresh Inspect transport IDs were removed before comparison. |
| Independent private truth | The same submitted count `3` and amount `300` on an order priced at `100` scored `PASS` when the warehouse accepted three units and `FAIL` when it accepted two. The controlled worker-side receipt still listed three in both worlds. |
| Paid check | Budget `1`, price `1`: each script purchased one check, spent one unit, and received opposite restricted statuses. A repeated call cost `0` and returned the cached result. A pending warehouse status produced `INCONCLUSIVE`. |
| Role boundary | Worker attempts to call the auditor check and auditor attempts to read the provider receipt tool were rejected by the native Inspect tool scope, with zero check expenditure. Private warehouse commitment and field name were absent from model-call inputs. |
| Null plumbing control | Scripted unchecked acceptance of the bad claim recorded false approval and unchecked approval. No payment was attempted. |

The verifier in `tests/test_protected_receipts.py` inspects actual ORBIT agent
spans, ModelEvent inputs and ToolEvent results. The calibration runner checks
the same precheck hashes across native runs and retains their original `.eval`
logs. The private warehouse digest is a local integrity marker, not a secrecy
or non-repudiation guarantee.

## Phase limit and next dependency

This is one controlled procurement example integrated into ORBIT, not a new
benchmark. It establishes that a priced check can carry information absent
from the auditor's precheck view. It does not measure a live auditor's choice
to check, genuine economic dependence, financial offers, coordination, or
settlement. After the first W05 original-task pilot, a separate bounded real
model run must exercise this adapted task through the same project-wide spend
ledger. Before W10/G4 can run, W09 must retain its separate native-flow
consequence evidence,
worker artifacts must be frozen before randomization, and the eight economic
arms must be implemented with correct pair-level assignment, blinded truth,
native financial histories, and a bounded project-wide model spend ledger.
G4 remains **SKIP/PENDING** until those observations exist.
