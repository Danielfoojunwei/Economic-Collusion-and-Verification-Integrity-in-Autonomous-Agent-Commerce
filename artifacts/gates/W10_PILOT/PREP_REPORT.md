# W10 protected-receipt real-model pilot — preparation

**Status:** runner and controlled private worlds ready for review. No W10
paid model call has been made in this record. `REAL_LLM_REMOTE_APPROVED` is a
planned execution tier, `NO_PAYMENT` is the task payment tier, and W10/G4
causal evidence remains `SKIP/PENDING`.

## Offline observations

The frozen authored claim is count `3`, amount `300`, digest
`1d8a11195cbf6609a5f64df9374457f32ea374f19eab9163f8c26b7993cc5fb8`.
Good/bad worlds have identical public-task SHA-256
`b448886284cd74fa4c99fe4ebc2c76d015d7c9a614b50ae54bb8e7386dd83449`
and provider receipt copy. Their protected warehouse outcomes are `PASS` and
`FAIL` for that same claim. An offline native Inspect negative test confirmed
the submission tool rejects a different claim rather than silently replacing
the authored artifact.

Both public-catalog dry runs exited 0. Each forecasts six maximum provider
calls, a USD 3.194880 reservation, and a ready shared budget ledger. At this
review the ledger had USD 0.095270 committed after the two earlier W05
samples, USD 19.904730 uncommitted, no active reservation, and no `UNKNOWN`
charge. The exact model is `openai/gpt-5.6-sol`, high reasoning, 4,096
completion tokens per call, with both retry layers disabled.

## Reproduce and limits

```bash
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest tests.test_w10_remote -v
scripts/run_w10_openrouter.sh --model-id openai/gpt-5.6-sol \
  --project-cap-usd 20 --world good
scripts/run_w10_openrouter.sh --model-id openai/gpt-5.6-sol \
  --project-cap-usd 20 --world bad
```

The five focused W10 runner tests passed offline. The previous W10 protected
receipt adapter calibration remains at
`artifacts/gates/W10_PREP/offline-run-002/` with two native scripted logs.
The actual good/bad real-model pair has not run; therefore there are no live
auditor precheck hashes or live good/bad verdicts to compare yet. The
existing W05 observations did not include a live defective artifact.

Independent verifier for preparation: native offline tool rejection, public
catalog model pin, shared ledger snapshot, and focused tests. No claim of
collusion, causal incentive effect, or native payment execution follows from
this preparation. The root agent must review the first live world and ledger
before deciding whether to execute the second world.
