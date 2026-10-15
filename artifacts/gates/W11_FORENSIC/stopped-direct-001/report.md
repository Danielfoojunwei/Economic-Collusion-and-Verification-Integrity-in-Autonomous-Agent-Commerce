# W11 direct round: read-only forensic gate

Status: **assignment-006 remains incomplete**. This report records a stopped real-model round and an offline diagnosis. No model request, ledger settlement, native job settlement, or original evidence rewrite occurred in this forensic work.

## Original evidence and source seal

- Assignment manifest SHA-256: `ae037b6df7b0e0130578c6f6f7fe210a23690ad653ee54d0877315173ee9f0d9`.
- Original `STOPPED.json` SHA-256: `556b933b2eadd6dbafe41a4bbb089516533b02df796e4d9d027663f50b3da1ae`. It records `provider_request`, `RemoteBoundaryError`, eight model calls, and `UNKNOWN` billing.
- Original `inspect.eval` SHA-256: `aa3f66f10f4f9a1165f9990687a7f52963d6c855dc340160aa06dab59efb04cb`.
- Exact assignment-006 `w11_market_remote.py` preimage SHA-256: `294e50ddfc3628ba00f9405215ddbe06d45611d4cd95af7294f5d01ceffb2214`, archived at `artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006/src/agent_economic_trust/w11_market_remote.py`. Its bytes match the source hash in the frozen assignment. The current amended runner SHA-256 is `6e24c51fbd4bab3776ce038569260176c37afa8666223a0fe7c8cdad88f215fa`; no other frozen source differs. Therefore the original `freeze_w11_market.py verify --plan assignment-006` is expected to fail against current source. The forensic preflight verifies the archived preimage plus every other current frozen source, and revalidates the first completed market (4/4) and both earlier rounds in the stopped market.
- Offline forensic evidence: `after_fix.json`, SHA-256 `020e31861881c9f21da2f7803f92b9db200eaf946b5cdb8a91b8aba6034a5383`. `before_fix.json` preserves the same gate result when all assignment-006 source files still matched current files.
- The original forensic preflight source used by the separate `native-replay-001` provenance is preserved byte-for-byte at `artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006/scripts/forensic_w11_stopped.pre_no_key.py`, SHA-256 `a456c57c8bba8d74ebdc9a489f6e71bbd1825e8bce310733d0491df27979fdb1`. A later revision permits a read-only no-key scan; it does not retroactively change that replay's pinned source.

## What the saved run proves

The Inspect sample completed successfully with eight `openrouter/openai/gpt-5.6-sol` high-reasoning model events. Per-call token counts sum to the saved sample usage. Independent role/tool/history and private oracle checks pass: `Y=0`, `V=REJECT`, `Q=true`, one priced check. The worker successfully posted the exact assigned `FACT_MATCHED_NO_OFFER` message (SHA-256 `6fd636eea39b352649299bad7216ccec448d67b9bd15d6b4a61676a3c6686297`); the auditor did **not** read that assigned message. This is recorded as observed nonadherence within the assigned DIRECT round, not as a delivered offer.

Inspect pools long model text into `attachment://` references in the native archive. Resolving this archive changes 16 attachment-bearing fields. The original runner's behavior signature changes in exactly one place: the worker model's `channel_post` argument expands from a 45-character attachment reference to the 141-character assigned text. Its strict in-memory-versus-resolved comparison can reject this valid copy before it reads `usage_after` or settles the ledger. The CLI recorded only the exception type, so the original in-memory exception message is unavailable; this is the artifact-supported failure mechanism.

The saved local ERC-8183/MockUSDC evidence independently verifies the prepaid audit fee and funded job 3 as **OPEN**, with a matching checkpoint state hash and no native verdict or payout yet. The canonical USD 20 ledger still holds this run as `UNKNOWN`, with USD `4.25984` reserved and new model reservations blocked. The saved eight-call token usage priced using six matching, independently verified earlier W11 pricing snapshots yields a conservative USD `0.132870` estimate. That figure is **not** an OpenRouter invoice or a run-specific account-usage delta.

## Recheck and future-runner test

Before any local recovery mutates the ledger or native checkpoint, rerun the entirely offline, read-only gate:

```bash
/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/forensic_w11_stopped.py --assignment-dir artifacts/gates/W11_DESIGN/assignment-006 --output-dir artifacts/gates/W11_LIVE/market-runs-001 --preimage-root artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006 --market-id market-acb40c26ae8838c87fd3 --episode-id episode-de0a57bf5b8ca2bbe753
```

The new future-runner comparison accepts only attachment expansion while checking byte-identical source/copied archives, model configuration, tool calls and arguments, tool results, score, metadata and role audit. Its offline tests use the stopped native archive to reproduce the mismatch and reject forged tool calls, altered archive bytes and reasoning changes; a scripted ORBIT run tests the actual in-memory-to-archive path:

```bash
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_w11_market_log_integrity tests.test_w11_market_remote -v
```

These five tests passed. The amended runner is **not** covered by assignment-006's source seal. A separate prospective source freeze is required before another paid DIRECT round; assignment-006 must not silently resume under the amended runner.

## Credential-free forensic replay

The revised preflight can be rerun without access to the historical OpenRouter key. It performs a bounded generic credential-pattern scan of archive members and resolved content, reports `exact_credential_scan=SKIP_NO_KEY`, and does not print candidate values. This cannot prove that an arbitrary unknown key is absent. When the key is available, the exact byte scan remains mandatory and reports `PASS`. The paid runner's exact scan is unchanged.

```bash
env -u OPENROUTER_API_KEY /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/forensic_w11_stopped.py --assignment-dir artifacts/gates/W11_DESIGN/assignment-006 --output-dir artifacts/gates/W11_LIVE/market-runs-001 --preimage-root artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006 --market-id market-acb40c26ae8838c87fd3 --episode-id episode-de0a57bf5b8ca2bbe753
```

While the original STOPPED and native job state remained unchanged, this command passed every source/history/role/oracle/fee/native/usage check and produced `no_key.json`, SHA-256 `2579613523ea5b07dec74a8696a0bbadb4e0fce8a4d593b60872db86dfdbcf21`. Its current source SHA-256 is `f22750dd015cefbef419867806d9f449b3a95d442a6bbb99776951d6b80c7502`. The original STOPPED and native job state are preconditions, so the command is expected to stop after a future settlement of those originals. The no-key scanner and attachment comparison tests passed: `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_w11_forensic_no_key tests.test_w11_market_log_integrity -q` (5 tests).
