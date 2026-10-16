# Independent pre-view BILATERAL030 funding replay

**Gate: two v2 scripted public archives replayed offline; live pre-view funding attestation and scientific COMPLETE remain HOLD pending local integration and independent review.**

`bilateral030_funding_verifier.verify_funding_file(path, trusted_public_assignment)` verifies one public-only archive against an assignment supplied separately from the archive. Default status `FUNDING_ARCHIVE_REPLAYED` means the saved bytes are internally consistent. `confirm_live=True` additionally makes read-only JSON-RPC calls to the archive's `127.0.0.1:port` while its fresh Anvil job is still funded; only this mode can return `FUNDING_LIVE_CONFIRMED`. A caller-injected RPC returns the test-only `FUNDING_LIVE_TEST_REPLAY` and cannot satisfy the pre-view gate. The verifier never sends a transaction or calls a model.

The verifier checks the pinned official ERC-8183 checkout, compiled artifacts, bridge/exporter/hook source hashes, exact public assignment and model direction, canonical 350-cent report and `createJob` description, hook immutable digest/roles, and absence of private truth or buyer-record fields. It replays every setup/funding signer, calldata, block, raw receipt, decoded event, ERC20 transfer, and balance snapshot. It requires the client-funded 20,000,000-unit job and the assigned 5,000,000-unit bonus from the provider into the hook, or an assigned no-bonus hook with zero escrow. The `public_prefix_sha256` and funding transaction/receipt hashes come from this replay. The read-only live mode additionally compares every saved transaction/receipt to the still-live chain, exact compiled runtime code, the official job, hook state/digest, fee terms, all token balances and supply, and an unchanged funding-tip block. Its HTTP client connects directly to localhost with no proxy or redirect handling.

## Reproduce the archive and fake-RPC checks

```sh
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_bilateral030_funding_verifier -v
```

Result on 2026-10-16: **PASS, 8 tests**. Positive archive replay covers funded and no-bonus v2 branches; a deterministic fake RPC exercises the live comparison code without network access and receives only the test status. Negative tests alter trusted assignment, source pin, private fields, public description and prefix, create/fund/bind/bonus calldata, bonus source/provider/amount, no-bonus transaction shape, receipt identity/hashes, hook state, balances, live tip, live transaction/receipt/code/state/balance, and symlinked input.

| V2 public archive | SHA-256 | Transactions | Replay result |
| --- | --- | ---: | --- |
| `artifacts/prospective/ERC8183_BILATERAL030_PREVIEW_FUNDING_V2_001/funded.json` | `232bf3127a8ad1d94dd9b39a4e10733994dd1aa6f98aa72a6fc8b98212b6bb33` | 19 | Provider bonus 5,000,000 units in hook |
| `artifacts/prospective/ERC8183_BILATERAL030_PREVIEW_FUNDING_V2_001/unfunded.json` | `7ceffdc7c82c4367ac6db67182c44be348c64f4f25f2622ba719dbcce9aa6a6a` | 17 | Assigned bonus absent; hook balance zero |

Both were produced on disposable local chains from planner commit `725e70e` and remain scripted mechanism fixtures, not study rows. `tests/fixtures/bilateral030_native/v2_public_assignments.json` pins their public assignments independently from the planner's `c7` seed; the archive's own assignment is only a cross-check. The pre-v2 public archives remain untouched under `PREVIEW_FUNDING001`.

For a future live pre-view run, write a **separately trusted single public assignment** JSON with exactly `episode_id`, `obligation_id`, `provider_model_id`, `auditor_model_id`, and `assigned_bonus_minor`, then run while the bridge's Anvil process is still at the funding tip:

```sh
python scripts/verify_bilateral030_funding.py public-funding.json --assignment trusted-public-assignment.json --confirm-live
```

The output includes exact archive and verifier source SHA-256 hashes, the public prefix hash, episode/obligation/model direction, job/report/hook, job and bonus funding transaction/receipt hashes, and assigned bonus amount. The runner must bind this exact archive hash and prefix hash to what both models actually see. The localhost RPC endpoint is a local experimental trust boundary, not a cryptographic chain finality proof.

**SKIP:** no real localhost RPC was contacted by this verifier author, and no model input or paid call was examined. A native bridge agent must run both bonus branches through `--confirm-live` on fresh disposable jobs; an independent reviewer must approve those receipts and the model-input handoff. Until then, archive replay cannot establish that the bonus was funded at the instant of auditor exposure. Scientific COMPLETE additionally requires terminal native replay, Inspect trace provenance, and cost-ledger join. The preview archive contains no private invoice oracle and cannot establish report truth or collusion.

Files owned by this review: `src/agent_economic_trust/bilateral030_funding_verifier.py`, `scripts/verify_bilateral030_funding.py`, `tests/test_bilateral030_funding_verifier.py`, `tests/fixtures/bilateral030_native/v2_public_assignments.json`, and this report. The bridge exporter is a separate committed source file; this verifier does not call its funding assertion or archive builder.
