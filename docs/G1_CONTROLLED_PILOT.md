# G1 controlled verifier pilot

This is a small integration slice for W02–W04. The runtime is the verified
official ORBIT v1.0.3 release backed by Inspect AI 0.3.263. Worker and auditor
execute in separate scheduled Inspect agent sessions. The model is a local
`mockllm` scripted control and payment is a valueless `MOCK_LOCAL` ledger.

## Reproduce

Use Python 3.11 or later on the cloud machine. The setup script obtains the
official GitHub release wheel if absent, verifies its recorded SHA-256 before
installation, pins Inspect AI and JSON Schema validation, and runs `pip check`.
It does not install the unrelated PyPI package named `orbit`.

```bash
cd /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce
scripts/setup_g1_runtime.sh
scripts/run_g1_offline.sh \
  --output-dir artifacts/gates/G1/my-new-run \
  --created-utc 2026-10-15T05:00:00Z
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -v
```

Use a fresh output directory for every run. The shell runner sets the working
directory and XDG data/cache/config paths under `/workspace`. Neither runner
selects a remote model or payment endpoint. `PYTHON_DOTENV_DISABLED=1` prevents
Inspect from loading a nearby credential file.

## What executes

The public task specifies invoice line items and the reconciliation obligation.
The worker submits an amount through its only domain tool. The auditor views
that submitted artifact as untrusted tool data, may buy a one-unit check from a
two-unit budget, and issues a verdict. Tool factories bind role and sample ID
outside model arguments. A trusted scorer evaluates the artifact against its
private fixture; the mock settlement consumes only the recorded verdict.

The fixed fixtures produce oracle `PASS`, `FAIL`, and `INCONCLUSIVE`. Three
scripted policies run on each fixture: buy check and follow its result, always
accept, and always reject. The latter two are negative controls. An additional
test repeats a native check call to verify that the cached result costs zero
on replay. Another test asks the worker to invoke the auditor-only check and
observes Inspect reject the unavailable tool without charging the budget.

Each policy directory contains the native `inspect.eval`, `events.jsonl`,
`episode_outcomes.csv`, and `run_manifest.json`. The manifest records source
commits, execution tiers, code hashes, budget, fixed assignment, and artifact
hashes. `agent_economic_trust.evidence.verify_evidence(path)` checks all saved
hashes, event schemas, event IDs, causal parents, and outcomes. The native log
contains private scorer targets and should remain in the research evidence
area; no target marker or private target field reached any model-call input.

## Interpretation

These fixed worker artifacts do not measure worker competence. Their public
arithmetic lets an auditor infer the expected total without buying the check.
The scripted policy outcomes test plumbing and scoring, not LLM behavior or
economic influence. The artifact digest is a local SHA-256 identifier, not a
signature. The mock ledger is not ERC-8183, x402, or any native payment flow.
G1 behavioural claims remain untested until a bounded real local model run.
