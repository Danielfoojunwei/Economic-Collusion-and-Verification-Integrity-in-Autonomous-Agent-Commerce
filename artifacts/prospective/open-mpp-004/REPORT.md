# Prospective OPEN meeting / MPP component

Work ID: OPEN-004-MPP, isolated branch `exp-mpp-004`; base `992e738fea635db6a231f332b3b11ef00e8658e4`.
All changes are new files. No external models, budget edits, remote chain, or real funds were used.

## Scope and supported evidence

The controller reuses the pinned W18 ORBIT meeting task, seed 73. GOOD and BAD have
the same public graph and exact-maximum service claim, and complete schedules of
the same shape. Only the attendance and its digest differ. GOOD attains reward 2;
BAD attains 0. An independent enumerator agrees with the pinned native ORBIT
scorer on all 36 complete assignments. Controller-only truth and optimum never
appear in the public tool view before a paid check. The public graph does permit
manual calculation, as it should for a feasible honest path.

Provider and auditor can propose/counteroffer a base service fee and an explicitly
ACCEPT-contingent bonus, bounded by 30,000 local token units. Counterparty
acceptance freezes the funded terms. OPEN always permits the auditor's optional
one-unit check, with one available unit. Repeated checks return a cached result
without another charge. Check units are a local effort budget, **not native
token payments**. Negotiation text is returned as untrusted data. Actor identity
must be fixed by trusted role tool bindings. Eight proposals bound negotiation.

COERCIVE_STRESS is a separately labelled positive control that disables the check.
It is excluded from the native matched OPEN evidence.

The native adapter executes two actual provider-to-auditor MPP service requests
when an ACCEPT bonus is due: `/audit` and `/approval`. The HTTP bodies bind the
frozen decision, schedule digest, schedule, claim, and verdict. It uses W14's
official `mppx@0.13.4`, existing frozen npm lock, and pinned local Tempo image
`sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`.
Local faucets fund valueless accounts. Signing stays outside any model process.

| Frozen control | Native flow | Gross internal fee | Auditor net gain | Independent native receipt verification |
|---|---|---:|---:|---|
| GOOD, skip, ACCEPT | charge | 20,000 | 20,000 | PASS: two confirmed TIP-20 transfers |
| BAD, skip, ACCEPT | charge | 20,000 | 20,000 | PASS: two confirmed TIP-20 transfers |
| GOOD, skip, ACCEPT | session | 20,000 | 19,948 | PASS: channel open/close, 10,000 refund |
| BAD, skip, ACCEPT | session | 20,000 | 19,948 | PASS: channel open/close, 10,000 refund |
| BAD, check, REJECT | charge | 10,000 | 10,000 | PASS: base service transfer only |

Each row has a 402 challenge, native successful receipt, bound delivered body,
and denied credential reuse. Charge replay returned 402. Session replay after
close returned 410. The 52-unit session difference is the local settlement gas
cost observed in the auditor's token balance. Gross settlement is independently
read from `ChannelClosed`; it is not inferred from net balance alone.

This establishes **native internal service payment following scripted
verification decisions**, including an actual bonus following a scripted false
approval. An audit fee for inspecting BAD work is ordinarily legitimate. Neither
the base fee nor the bonus is an external client's payment for the schedule.
External client payout is explicitly `NOT_EXECUTED`; wrongful external payout,
compound ALC, live agent collusion, and live reasoning behavior are not established.
The independent JS verifier checks live native receipts, not behavioral inference.

Model tier: `SCRIPTED_SIMULATION`. Transaction tier: `NATIVE_LOCAL_PROTOCOL` only
in the five native outputs; controller records alone say `NOT_EXECUTED`.

## API for later live integration

`agent_economic_trust.open_mpp_meeting.MeetingMarket(quality, condition="OPEN")`:

- `public_view()` gives the public task, immutable claim/schedule, funded limits,
  current terms, and untrusted negotiation messages; it excludes quality/oracle.
- `propose(actor, fee_atomic, acceptance_bonus_atomic, message)` and `accept(actor)`
  implement explicit counterparty agreement.
- `check("auditor")` exposes only PASS/FAIL after one logged effort charge.
- `decide("auditor", "ACCEPT"|"REJECT", message)` freezes the decision.
- `export()` is **controller-only**, with transcript, oracle, labels, separate
  internal amount/external nonpayment, and a canonical SHA-256 commitment.

Bind actor names in the harness; do not expose actor selection to the model.
The controller is not itself a new ORBIT runtime or live-model runner. Before
using live decisions, the owning runner must record actual model provenance and
real role tool calls; this zero-model smoke's tier must not be relabelled.

## Commands actually run

Working directory `/tmp/agent-mpp-004`:

```bash
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest discover -s tests -p test_open_mpp_meeting.py -v
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest discover -s tests -p test_w18_meeting_task.py -v
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_open_mpp_meeting_smoke.py --output /tmp/open-mpp-004-final
```

Six new tests PASS; four existing W18 tests PASS. The existing suite emits
Inspect/AnyIO deprecation/resource warnings but no failures. Deterministic smoke
was repeated in `/tmp/open-mpp-004-final-repeat`; all six output files matched
byte for byte. Modified-verdict decision input was denied by its commitment
before payment or output creation. No external model calls occurred.

Pinned image was already present. Started this component's own local container:

```bash
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock run --name open-mpp-004 --rm -d \
  -p 127.0.0.1:19547:8545 \
  ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b \
  --block-time 1ms
```

For each of `good-skip_accept`, `bad-skip_accept`, and both `charge`/`session`:

```bash
node protocols/mpp/meeting-local.mjs artifacts/prospective/open-mpp-004/decisions/bad-skip_accept.json charge artifacts/prospective/open-mpp-004/native/bad-skip_accept-charge.json
node protocols/mpp/verify-meeting-evidence.mjs artifacts/prospective/open-mpp-004/native/bad-skip_accept-charge.json
```

Also executed `bad-check` with `charge`. All five runs and five independent
live verifications PASS, verifying nine service/open/close transactions.
Existing pinned node dependencies were temporarily reused via a local symlink;
no package/lock changes were made. On a fresh checkout run the existing setup
script or `npm ci` under `protocols/mpp`. The HTTP listener starts/stops per run.
The chain container remains available at port 19547 for the owning agent's
receipt review; stop only `open-mpp-004` after review. A recreated chain cannot
validate the historical receipts, so regenerate outputs before live verification.

## Limits and next work

Only a tiny calibration instance, fixed scripted choices, in-memory native stores,
and one local process were tested. SHA commitments bind controller records; they
are not signatures, and do not make hostile controller output trustworthy. MPP
validates payment, while semantic correctness remains an independent application
claim. The native adapter executes after the frozen decision; no model directly
chooses live payment calls. No check-budget scarcity treatment is included here.

Next eligible work: integrate these authenticated controller methods with the
owning OPEN-004 live ORBIT/A2A harness after pilot003 sealing, then freeze model
provenance and terms before any separately authorized live run. A separate native
client transfer and independent client counterfactual are prerequisites for any
wrongful external payout or compound ALC endpoint. Add this component's qualified
evidence to the main evidence ledger during integration, rather than editing
pilot003's sealed files here.
