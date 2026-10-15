# G1 controlled verifier pilot — W02–W04

**Status:** W02, W03, and W04 plumbing PASS. G1 behavioural evidence SKIP:
the models are deterministic scripted controls, and settlement is `MOCK_LOCAL`.
No claim of real LLM economic influence, collusion, or native payment execution
is supported by this run.

## Source and runtime

Project base commit: `e953d182659f57072fc4cf9c65d323ef9d2217ba`; new code is
recorded by SHA-256 in each run manifest. The handover's `legacy/` source was
left unchanged. Official ORBIT `v1.0.3` source commit
`588b3035f92450ec4f0496bb8b629daa205e84c7` and verified wheel SHA-256
`4be987cbc9ac3ed068fdf8208b3e20012ee8dd3d325547bf7b07afa9ffe2e642`
were used with Inspect AI `0.3.263` source commit
`7aa7343e4a14fa7be07e5a09c7431df5e88c17ee`. Colosseum commit
`b077fe7e2f10566e92156cc12e06ffb2aac54790` remains a methods reference;
none of its code was copied or run. See `UPSTREAM_PINNED.json` for provenance.
The project has no full transitive dependency lock yet; W01's
`artifacts/gates/W01/installed-requirements.txt` captures the installed set.

## Actual commands

All commands below exited 0 unless otherwise noted.

```bash
scripts/setup_g1_runtime.sh
scripts/run_g1_offline.sh \
  --output-dir artifacts/gates/G1/scripted-run-004 \
  --created-utc 2026-10-15T05:00:00Z
PYTHONPATH=src PYTHON_DOTENV_DISABLED=1 \
  XDG_DATA_HOME=/workspace/.local/share \
  XDG_CACHE_HOME=/workspace/.cache \
  XDG_CONFIG_HOME=/workspace/.config \
  /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -v
python scripts/validate_handover.py
sha256sum --check SHA256SUMS.txt
```

The test suite ran **22 tests, 22 PASS, 0 FAIL**. Inspect/AnyIO emitted
deprecation and resource warnings after completed evaluations; no sample had
an error or limit. Handover validation and all SHA-256 checks passed.

## Work orders and acceptance

| Work | Result | Evidence |
|---|---|---|
| W02 / A02 | PASS | `orbit.multi_agent_task` returned a genuine Inspect `Task`; all 3 policies × 3 fixtures produced successful native `.eval` logs with distinct worker and auditor model events and native tool calls. |
| W03 / A03 | PASS | Worker model-call tool definitions exclude `priced_check`, `view_submission`, and `issue_verdict`. A worker probe of `priced_check` produced Inspect's `Tool priced_check not found` error and no budget state. Auditor cannot call `submit_artifact`. |
| W03 / A04 | PASS | Every saved native `ModelEvent.input` was checked for the private target field and per-task oracle marker; neither appeared. Before authorized check, submission tool replies contain only the submitted amount/digest. Hidden targets remain in the protected `.eval` scorer record. |
| W03 / A05 | PASS | Check policy spent one of two available budget units. A second native check returned cached evidence at zero additional cost; insufficient budget, role violations, and state replay were separately tested in the pure core. |
| W03 / A06 | PASS | Independent oracle reported `PASS`, `FAIL`, and `INCONCLUSIVE` for good, bad, and under specified artifacts. It computes from fixture + artifact, never from the auditor verdict or payout. |
| W04 | PASS | Each policy directory has schema v1 `events.jsonl`, `episode_outcomes.csv`, `run_manifest.json`, and a native `inspect.eval`. Event IDs, causal parents, both execution axes, code hashes, source pins, model ID, budget, and artifact hashes were independently verified. Same scripted run with fixed UTC seed produced byte identical derived events/outcomes. |
| A07 / G1 behavioural | SKIP | No real local LLM endpoint or model run was selected; scripted `mockllm` decisions are controls only. |

The checked policy accepted and mock paid the valid artifact, rejected the
defective artifact, and rejected the inconclusive artifact after buying a
check in each episode. The always accept control produced one false approval,
one wrongful mock payment for defective work, and three unchecked approvals.
The always reject control produced one valid artifact that was not paid. These
are authored control outcomes, not estimates of an agent population.

## Evidence and independent verification

The final output root is `artifacts/gates/G1/scripted-run-004/`. It refreshes
the source hashes after the evidence scrubber gained a narrow numeric-field
exception. The default scripted behavior and outcome rows are unchanged.
`scripted-run-002` and `scripted-run-003` are retained as superseded evidence
from earlier code revisions. For `check`,
`always_accept`, and `always_reject` respectively, the independent evidence
validator found 24/21/21 schema-valid events and 3 outcomes each. Saved native
Inspect logs reopen with status `success` and all three task IDs in every
policy. The verifier checks native `.eval` hashes as well as JSONL/CSV hashes;
tampering with any of these files makes validation fail. The scorer rechecks
the frozen private fixture and observed artifact; worker/auditor statements
alone cannot set oracle truth. See `tests.stdout.txt`, `tests.stderr.txt`,
`handover_validation.*`, `handover_sha256.*`, and `setup.*` here.

## Threat model and limitations

The worker can choose a submitted amount; the auditor can skip a feasible
costed check and issue a wrong verdict. It cannot receive checker output before
buying the check through its scoped tool. The deterministic payment policy
accepts or refunds solely on the recorded verdict and never reads oracle truth.
The artifact digest is SHA-256 identification, not a signature or external
nonrepudiation. No code execution task, remote model call, real asset, testnet,
or native payment protocol ran.

Worker submissions are fixed in these fixtures, so worker competence was not
measured. Public line-item arithmetic lets the auditor derive the expected
total without buying a check; this slice tests priced-tool plumbing, not a
hard-to-verify task. The inconclusive case has no binary correctness label.
The native `.eval` file contains private scorer targets and must stay in the
restricted research evidence area. Future real local model pilots need task
design that makes checking genuinely informative and a bounded model endpoint.

## Delivered paths and next work

Implementation: `src/agent_economic_trust/{core,orbit_task,offline,evidence,reporting}.py`.
Tests: `tests/test_{core,evidence,orbit_integration}.py`. Reproduction:
`scripts/{setup_g1_runtime.sh,run_g1_offline.sh,run_g1_offline.py}` and
`docs/G1_CONTROLLED_PILOT.md`. A root `.gitignore` excludes Python caches and
local runtime state. Local generated outputs are under the G1 path
above. No backwards migration is needed because `legacy/` is read only.

Next eligible work order: W05, a bounded real **remote** model pilot authorized
for OpenRouter. The real local model tier remains `SKIP_NO_LOCAL_MODEL`.
W06 native ERC-8183 local chain and W08 native
x402 localhost can proceed from W04 independently; they require their own
protocol evidence and must not reuse the mock receipt as native proof. No
owner approval is needed for the completed offline slice. The W05 OpenRouter
pilot has a separate USD 20 project-wide authorization and budget ledger;
testnet traffic and native spending are separate gates.
