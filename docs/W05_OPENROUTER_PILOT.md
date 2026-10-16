# W05 bounded OpenRouter pilot

W05 reuses the G1 ORBIT/Inspect reconciliation task. The selected real model is
`openai/gpt-5.6-sol` on OpenRouter with high reasoning effort. Payment remains
`MOCK_LOCAL`; native payment protocols are separate work orders. One sample is
run serially at a time. These fixtures are a controlled verifier pilot, not a
collusion experiment: the worker computes a public total and the auditor can
infer it without buying the check. The real worker's submitted amount, rather
than the earlier scripted artifact label, determines the oracle result.

## Runtime and dry run

Use the [G1 setup](../scripts/setup_g1_runtime.sh) to install the verified
official ORBIT v1.0.3 wheel, Inspect AI 0.3.263, and JSON Schema validator.
The W05 shell wrapper sets cwd, XDG paths under `/workspace`, and disables
dotenv loading. A default invocation fetches the public, unauthenticated
OpenRouter model catalog and reads the project budget ledger. It does not call
the inference endpoint.

```bash
cd /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce
scripts/run_w05_openrouter.sh \
  --model-id openai/gpt-5.6-sol --project-cap-usd 20 \
  --sample-id reconcile-002 \
  --output-dir artifacts/gates/W05/real-run-001
```

The project-wide ledger is `artifacts/budget/openrouter-ledger.jsonl` and its
`.anchor` sidecar. They were initialized once with USD 20 cap and USD 0 opening
spend; both files must be retained for all future remote runs. The CLI can
initialize a missing ledger explicitly using `--init-ledger
--opening-spent-usd <known prior project charges>`, but it refuses to reset an
existing ledger. Paid execution accepts only the canonical project ledger.

## Paid execution boundary

The runner requires all of these: exact model ID and USD 20 project cap,
`--execute`, `ALLOW_EXTERNAL_MODEL_CALLS=true`, `MAX_REAL_SPEND=20`, an
`OPENROUTER_API_KEY` supplied by the managed environment, and a valid ledger
with enough uncommitted budget. It rejects `ALLOW_MAINNET=true`. The key is
never printed, stored in the ledger, or embedded in derived evidence. Native
Inspect files are mode 0600 and scanned for the exact credential before use.
The first paid call is coordinated by the root agent to avoid duplicate spend.

For one sample, the public catalog's highest price tier gives a USD 2.662400
worst-case reservation: at most five provider calls, 32,768 serialized input
bytes plus 8,192 framing tokens per call, and 4,096 completion tokens per call
including reasoning. Inspect and OpenAI SDK retries are both disabled. The
ORBIT scheduler stops at five turns or 240 seconds; each request times out at
180 seconds. Serial sample execution stops on the first error.

The runner reads `/api/v1/auth/key` usage before and after the sample. Ledger
settlement uses the greater of the positive account usage delta and a
conservative high-tier catalog estimate from Inspect's token counts. This is
an estimate for budget control, not a provider invoice. If accounting is
missing, inconsistent, or above reservation, the ledger retains an `UNKNOWN`
hold and refuses further requests until reconciled. The public catalog
snapshot, raw Inspect token counts, usage delta, and estimated cost are saved
with the run when complete.

## Evidence and status

A complete run requires a native approved-model Inspect log, separate worker
and auditor ModelEvents, a worker submission, final auditor verdict, trusted
mock settlement, and independent oracle score. It exports `inspect.eval`,
`events.jsonl`, `episode_outcomes.csv`, and `run_manifest.json` with tier
`REAL_LLM_REMOTE_APPROVED` and `MOCK_LOCAL`. The exporter checks native log
contents, model/tool provenance, role isolation, target secrecy, event schemas,
and artifact hashes. Missing actions or any error leave the native log when
available and a `STOPPED.json` marked `PARTIAL`; no COMPLETE outcome is
exported. The local-model tier remains `SKIP_NO_LOCAL_MODEL`.

Before the first paid call, W05 is a tested execution path with no real-model
behavioral evidence. Any pilot outcome will describe only the tested fixture
and does not support a causal economic collusion claim.
