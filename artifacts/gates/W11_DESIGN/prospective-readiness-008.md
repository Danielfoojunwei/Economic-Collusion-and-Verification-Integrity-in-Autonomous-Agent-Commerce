# W11 prospective offline readiness: assignment-008

Status: **OFFLINE_PASS; LIVE_UNRUN**. This is a fresh prospective W11 market assignment, not a causal result. The earlier assignment-006 remains stopped and incomplete. Assignment-007 is preserved as `INVALID_SOURCE_SEAL` in `assignment-007-invalidation.json`; its scripted smoke is a technical control only.

## Freeze and source evidence

- `scripts/freeze_w11_market.py freeze --output artifacts/gates/W11_DESIGN/assignment-008 --blocks 1` ran once with its default fresh random seed; no seed was supplied or rerolled. Assignment-007's seed and order were not inputs to this draw.
- Assignment manifest SHA-256: `7695ff9572d7bcd67838a18a6ed7e3f7e84571b4aa5fce62b6339ab31b820ebd`; 12 markets, 48 assigned episodes, 30 sealed source/data inputs. `freeze_w11_market.py verify` passed.
- Active freezer SHA-256: `b1316734c841d872286a292fad8cfbfe4e5d0bb7a9d81f19d0936c92804e43dc`. Exact assignment-006 freezer preimage SHA-256: `ee67cfae0a0cc4cd028ebdebe31132144629cb12fd4f552a80747bd8f56b9da1`; it matches the original assignment-006 manifest. The historical source verifier accepts only this preimage and the archived runner preimage.
- The seal covers all local Python imports in the W11 runner/collector/smoke closure, the smoke model fixture, `src/agent_economic_trust/__init__.py`, and `schemas/event.schema.json` plus `schemas/run_manifest.schema.json`. The assignment manifest lists every input and hash. Upstream ORBIT/Inspect and ERC-8183 pins are checked separately.
- Assignment-007 verification now rejects its changed source, as required; its manifest and saved smoke were not edited.

## Offline execution and tests

- `scripts/run_w11_market_scripted_smoke.py` on assignment-008 passed: 10 Inspect scripted episodes with actual local ERC-8183 test-token transactions, including no-channel and direct-channel controls. Summary SHA-256: `2a730104b00c21f4e554f79e68b00655ca4d738c5e94094a91dbd6ef97824145`. Two assigned promise opportunities were retained, one assigned promise was read, and an altered-promise negative control was not counted as exposure.
- Focused source-seal, schedule, task, native market, attachment-integrity, saved-score and credential-scan tests: **18 passed, 0 failed**. A tampered archived freezer is rejected. No external model call or nonlocal payment was made in this setup.

## Budget and execution order

- Frozen first market: `market-3189ff03fda50e7f5379`, `REPEAT_NONE`, provider-funded audit fee (`R=1`), four required rounds. Full execution order is in the assignment manifest; no market was selected after seeing an outcome.
- Shared ledger at freeze: USD 20 cap, USD 2.581642 settled, USD 0 reserved, USD 17.418358 available, unblocked; last hash `fba9976633f7be4d4addaeea51e8f2d6a7d39289ac45e73bdbcbb598a944015f`.
- Using the **saved** 2026-10-15 07:19:51 UTC public catalog snapshot from prior W11 evidence and existing per-call bounds, a six-call no-channel round needs USD 3.194880 reserved. Four mandatory first-market rounds need USD 12.779520 worst-case, leaving USD 4.638838 nominal headroom. This is an offline estimate; the live preflight must fetch fresh public pricing, recheck the canonical ledger, require the entire next market to fit, and verify source/assignment hashes before any request. The frozen 48 rounds comprise 40 `NONE` rounds and eight `DIRECT` intervention rounds; the sum of their worst-case reservations is USD 161.873920 at those saved rates, beyond the current cap if every request reached its limit. Later markets remain assigned but pending until each full-market gate passes.
- One feasible market cannot establish an arm contrast or collusion effect. Keep all 12 assigned markets and 48 episodes in the denominator. No model behavior claim follows from the scripted smoke.

Offline budget reproduction (uses the saved catalog snapshot; no network or ledger write):

```bash
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python - <<'PY'
from pathlib import Path
import json
from decimal import Decimal
from agent_economic_trust.remote import MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS
from agent_economic_trust.remote_pricing import reserve_worst_case

root = Path('artifacts/gates')
rows = json.loads((root / 'W11_DESIGN/assignment-008/private_rounds.json').read_bytes())
rates = json.loads((root / 'W11_LIVE/market-runs-001/market-3e26430327c99e21c05c/episodes/episode-1e71fe47154315db66c8/run_manifest.json').read_bytes())['pricing_snapshot']
def reserve(row):
    calls = 8 if row['communication_mode'] == 'DIRECT' else 6
    return reserve_worst_case(rates, calls, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
counts = {mode: sum(row['communication_mode'] == mode for row in rows)
          for mode in ('NONE', 'DIRECT')}
first = json.loads((root / 'W11_DESIGN/assignment-008/assignment_manifest.json').read_bytes())['market_execution_order'][0]
print('counts', counts)
print('first_market_usd', sum((reserve(row) for row in rows if row['market_id'] == first), Decimal(0)))
print('all_worst_case_usd', sum((reserve(row) for row in rows), Decimal(0)))
PY
```

Next gate: independent review of the final source seal and a fresh **read-only** W11 preflight. Any live execution remains one supervised episode at a time under the owner's existing GPT-5.6 Sol high-thinking, USD 20 project-wide authorization.
