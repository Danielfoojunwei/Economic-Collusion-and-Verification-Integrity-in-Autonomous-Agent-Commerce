# 14 — Reproducibility protocol and artifact structure

## Required repo state

Pin ORBIT GitHub tag/wheel checksum, Inspect AI release, Colosseum commit, payment SDK repos and contract commits, Docker base image hashes, Python/Node/Foundry versions, model IDs/snapshots, and dataset/task revisions. Compare installed software to recorded constraints before every run.

## Experiment artifact directory

```text
artifacts/<gate>/<timestamp_run_id>/
  run_manifest.json
  environment.txt
  upstream_versions.json
  treatment_assignments.csv
  events.jsonl
  outcomes.csv
  protocol_evidence/
  statistical_analysis/
  failures_and_skips.json
  checksums.sha256
  report.md
```

Missing files must be listed in the report with reasons. `report.md` must state the inference tier and protocol tier and cannot claim native success without cryptographic/chain/facilitator evidence.

## Reproduce v0.2 legacy simulation

```bash
cd legacy/paid-audit-bench-v0.2-source
python -m unittest discover -s tests -v
python -m paidaudit wire-smoke
```

To avoid decompression of >500 MB of JSONL, inspect archived full traces in `legacy/raw-results/PaidAuditBench_v0.2_results_full.zip` only when needed; summary files are in `legacy/results-summary/paid-audit-bench/runs/`. Full simulation is still **SCRIPTED**, no native settlement or independently sampled real LLM outcome.

## Reproduce new project (Codex must implement)

1. `scripts/pin_upstreams.sh` or documented manual instructions produce an exact source+wheel lock with immutable digests.
2. `scripts/run_local_smoke.sh` builds a fresh environment and executes at least one ORBIT task with a deterministically mocked model and independent scorer.
3. Additional optional local-model run through explicitly configured endpoint; emits independently observed check actions and verdicts.
4. Native local ERC-8183 and x402 integrations execute test-only transactions. Store original RPC/event/protocol evidence.
5. Analysis script recomputes claims from event logs without relying on a model-generated summary.

Until these scripts exist and are tested, do not invent their invocation in a user-facing success report.

## Regression strategy

- Stable known-good/known-bad fixture tests.
- No-oracle-leakage tests.
- Unit balance conservation tests.
- Native protocol positive/negative spec tests.
- Matched replay restores identical initial state.
- Factorial contrast estimator recovered on synthetic toy fixture with analytically known interactions.
- Robust missing/timeout statuses preserved in denominators.

## Statistical notes

Power analysis from real pilot only. Register exact primary test, hierarchical/cluster uncertainty method, model/task/pair randomization, and planned sensitivity analyses before main run. Do not overfit on exploratory p-values, and always report estimated effects with intervals.
