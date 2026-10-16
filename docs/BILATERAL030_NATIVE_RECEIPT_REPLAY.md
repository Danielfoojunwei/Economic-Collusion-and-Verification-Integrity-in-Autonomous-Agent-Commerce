# Independent BILATERAL030 terminal native receipt replay

**Gate: NATIVE_RECEIPTS_VERIFIED for five saved scripted local branches; scientific COMPLETE remains HOLD.**

`bilateral030_native_verifier.verify_file(path, trusted_assigned_row)` reads one terminal bridge archive and a separately trusted `Bilateral030Row`. It opens no RPC connection and sends no transactions. Its status means the archived native transactions, receipts, events, transfers, and snapshots agree with the official ERC-8183 and bonus-hook code and with the assignment. It does not attest that the archived bytes came from an independently authenticated chain, that a model chose an action, or that the model received the promised pre-view funding proof.

## Inputs and checks

The verifier checks the pinned official ERC-8183 checkout, dependencies, compiled contracts, bridge and hook source hashes, and hook runtime immutables. It requires the assigned episode, provider/auditor model direction, exact public report and `createJob` description, and private invoice-oracle value to match their separate inputs. It replays exact signer, target, calldata, block order, receipt identity, and decoded core/hook/ERC20 event sequence from deployment through job creation/funding, optional provider-funded 5,000,000-unit bonus, claim, optional paid check, first decision, and terminal verdict. A transfer ledger checks every token movement and each opening/funded/intermediate/final balance snapshot. The bonus must go to the evaluator on first-claim approval or return to the provider on rejection or superseding submission; it cannot appear in the no-bonus arm. The official final verdict follows the protected oracle. The result exposes exact transaction hashes and the public digest for a separate Inspect-log join.

The saved `model_behavior_tier` is only a controller claim. The result names it `model_tier_controller_claim_only` and states `model_behavior_independently_replayed=false` and `chain_history_authenticated=false`. The verifier's status is deliberately `NATIVE_RECEIPTS_VERIFIED`, not an episode-wide COMPLETE label.

## Reproducible local check

Run from the repository root with the configured ORBIT environment:

```sh
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_bilateral030_native_verifier -v
```

Result on 2026-10-16: **PASS, 10 tests**. Positive cases replay five saved scripted branches. Negative cases reject altered source/public/private fields, runtime code, create/fund/claim/check/first/final calldata, transaction order/hash, approval signer, bonus source/beneficiary/refund, duplicate payouts, token balances, and WAIT/DEFER shapes. An edited `REAL_LLM_REMOTE_APPROVED` metadata string cannot upgrade the native-only status. No native transaction, model call, or network call was made by this verifier review.

| Saved fixture in `tests/fixtures/bilateral030_native/` | Raw JSON SHA-256 | Native transactions | Outcome |
| --- | --- | ---: | --- |
| `funded_bad_approve.json.gz` | `f72675a4f272b677e3bdc79ed52053331ec6689ca99947127d83427a00096410` | 24 | Bad report, paid check, false first approval, 5m evaluator bonus, final rejection |
| `funded_bad_reject.json.gz` | `f489603303dfd3b7c8f3d76d8a4694247c68936540df0856da6b72d3fad33941` | 23 | Bad report, first rejection, 5m provider refund |
| `funded_bad_defer.json.gz` | `5454aa6894939aef886e2abcff0f273ddef0e7f4b4f16d2ca84b4485b9d46b6a` | 22 | Bad report, pending claim superseded, 5m provider refund |
| `funded_bad_wait.json.gz` | `ab49e016744e460478eb313c2b80969038658d7982a98fc1d9c4f79948cde795` | 21 | Bad report, no first claim, 5m provider refund |
| `no_bonus_good_approve.json.gz` | `aadbeb1e6c8122fad5adee164a7530a6ec3e19c99096b73d188f01460cb00892` | 21 | Good report, first and final approval, zero bonus |

The fixtures came from fresh disposable local chains driven by scripted choices and bridge source commit `1a51189`; reject/defer and approve/wait pairs reuse assignments across separate test chains. They are mechanism test cases, not independent study observations.

The CLI accepts one saved JSON and one independently supplied assigned-row JSON:

```sh
python scripts/verify_bilateral030_native.py native-evidence.json --row trusted-row.json
```

It returns JSON with `evidence_sha256`, role/model direction, public digest, exact funding/claim/check/first/final hashes, and verified native amounts. Never derive the trusted row from the evidence file itself.

## Limits and next gate

**SKIP:** no live-model Inspect replay, no pre-view funding attestation, and no independently authenticated chain history in this review. A stopped local Anvil archive can be internally consistent while fabricated; a separate pre-view archive check may additionally query the still-live localhost chain read-only. The terminal verifier checks a canonical public `createJob` description and separate protected-oracle field; the Inspect trace verifier must prove what actually reached each model. A programmatic join of the terminal hash fields, funding attestation, Inspect trace, and cost ledger is required before calling a row COMPLETE. Neither these scripted fixtures nor a model-tier string count as a live bilateral outcome.

Files owned by this review: `src/agent_economic_trust/bilateral030_native_verifier.py`, `scripts/verify_bilateral030_native.py`, `tests/test_bilateral030_native_verifier.py`, five compressed fixtures, and this report. The verifier is independent of the bridge's `_assert_funded` routine and derives expected calldata/events/transfers from the pinned plan and official artifacts; it uses the existing ABI decoder and runtime compiler helper. The bridge/archive producer and native verifier remain separate source files for reviewer comparison.
