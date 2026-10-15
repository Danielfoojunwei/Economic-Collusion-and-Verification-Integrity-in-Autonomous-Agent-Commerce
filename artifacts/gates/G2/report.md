# W06 / G2 — native ERC-8183 local chain

**Status: PASS for the W06 native local protocol gate.** The official pinned ERC-8183 contracts were deployed through an ERC1967 proxy to a disposable Anvil chain on `127.0.0.1`. MockUSDC has no real value. The model behavior tier is `SCRIPTED`; the payment tier is `NATIVE_LOCAL_CHAIN`. This report does not claim real LLM collusion or a production payment defect.

## Source, runtime, and commands

| Item | Pin or path |
| --- | --- |
| ERC-8183 source | `erc-8183/base-contracts` commit `142e669c1fd318486a4628395b629f033654dd06`, MIT |
| Source dependencies | `forge-std` `620536fa5277db4e3fd46772d5cbc1ea0696fb43`; OpenZeppelin contracts `5fd1781b1454fd1ef8e722282f86f9293cacf256`; upgradeable contracts `7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf` |
| Toolchain | Checksum-verified Foundry 1.8.5 and solc 0.8.28; installation record: `/workspace/.tools/erc8183-prerequisites.md` |
| Final native evidence | `artifacts/gates/G2/local-run-004/evidence.json`, SHA-256 `e0c43e031f7c2a5013dfd4dc369ab4b1be609a34a1076fb4df912f5ffe632a13` |
| Native runner | `scripts/run_erc8183_local.py`, SHA-256 `0ea236b0c0fdc7c545736c34d92cc2318aa8cac8281feeb6652f218a3f83c5a7` |
| Independent receipt test | `tests/test_erc8183_local.py`, SHA-256 `72f12f22e0a43604d8d2b2d60d5b093339f6dc9ab460d84f7e7ce0923a1a552a` |

Commands actually run:

```bash
cd /workspace/upstreams/erc8183
/workspace/.tools/foundry/v1.8.5/forge test --offline --use /workspace/.tools/solc/v0.8.28/solc --threads 4

cd /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce
python scripts/run_erc8183_local.py --output artifacts/gates/G2/local-run-004
python -m unittest discover -s tests -p test_erc8183_local.py -v
```

The upstream suite passed **76/76** tests. The final runner compiled the pinned upstream source offline, then mined **49 local transactions: 41 successful and 8 expected reversions**. The two focused independent tests passed. The test output is in `tests.stderr.txt`; the upstream log is `/workspace/.tools/logs/erc8183-forge-test.log`. The runner's offline compilation log is in `local-run-004/forge-build.log`. No nonlocal RPC, testnet, or production chain was used.

## Native observations

The local chain ID was `31337`, with the Cancun hardfork and deterministic test accounts. The native contract proxy was `0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0`; MockUSDC was `0x5fbdb2315678afecb367f032d93f642f64180aa3`. The evidence records all deployed addresses, signer roles, source and ABI hashes, block heights, transaction hashes, raw receipts, log indexes, state reads, and balance snapshots.

| Acceptance | Result | Receipt evidence |
| --- | --- | --- |
| A08 wrong roles and terminal replay | **PASS** | An outsider's `complete` and provider's `reject` on a Submitted job reverted with status `0`, empty logs, and unchanged MockUSDC balances. Second `complete` and `reject` after terminal states likewise reverted, preventing double payment or refund. See steps `reject.wrong_actor_complete`, `reject.wrong_actor_reject`, `good.replay_complete`, and `reject.replay_reject`. |
| A09 settlement and known wrong work | **PASS** | The good job ended Completed. For 20,000,000 MockUSDC minor units, client −20,000,000, provider +17,000,000, evaluator +2,000,000, and treasury +1,000,000. A separately scored bad G1 artifact had oracle status `FAIL`; fixed scripted evaluator approval nevertheless made the **native escrow** pay the same amounts. This records the contract's reliance on evaluator attestation; no application evidence guard was installed. See `good.complete` and `bad.complete_without_guard`. |
| A10 expiry and claims | **PASS** | Funded expiry refunded immediately after `expiredAt`. Submitted expiry rejected refund during the one-hour evaluator grace period and refunded after it. Client direct partial settlement, provider claim submission, client claim rejection, consumed claim replay, mismatched claim binding, evaluator claim approval after expiry, and refund of the unsettled remainder all produced native receipts. A pending claim prevented refund after expiry until resolved. |

Representative transaction hashes: proxy deployment `0x75afe3471667aed9e6f7c74f1e7fc66b999b6bfd6ce4e11e1b9b29aea8d8510c`; good completion `0xea8980d54a5645da1e2560495dc499d78c6c0c3f8ca3ad87f91a32eb1785650a`; bad completion `0x3efc5e2d8ba1a8fe514b3831ec7cc63e6f106d8e6f780486b93ac82a03981421`; wrong-role completion `0x3d59944e0f6889542d2a1745c48b31a5922f238c8ced3c1f691996532391c7c7`; post-grace refund `0x0c09226289f425f508854b80810753fb75469a2e5fc3e8b364419a581b029f16`; claim approval after expiry `0xbf8ff76d6ca4162ee0648cd5448298d207b5ed8a98936f27c4c54f8671d3bc56`. Every transaction and log index is in the raw evidence.

The independent test reconstructs all token balances from ERC-20 `Transfer` logs in the saved native receipts and compares them with on-chain `balanceOf` snapshots. Final MockUSDC units were client 70,000,000; provider 42,500,000; evaluator 5,000,000; treasury 2,500,000; escrow 0. These sum to the minted 120,000,000 units. It also checks failed receipt statuses, terminal replay behavior, the bad artifact's separately obtained oracle result, expiry timestamps, claim state, ABI hashes, and absence of signing secrets in the evidence file.

## Limits and next work

The evaluator actions were fixed script decisions, not LLM outputs. The bad artifact's truth comes from the independent G1 oracle; ERC-8183 itself does not inspect that truth. The result supports local native escrow mechanics and the observation that evaluator approval pays under these conditions. It does not establish collusion, live-agent behavior, or a protocol vulnerability. A pending Funded claim can leave escrow parked after expiry if no authorized party resolves it; this is a pinned-contract liveness condition.

**PASS / FAIL / SKIP:** W06 native gate PASS; 2 focused tests PASS, 0 FAIL, 0 SKIP; 76 upstream tests PASS, 0 FAIL, 0 SKIP. W07 fixed-decision replay with a separately labeled application guard is **SKIP here** because it is the next work order, not part of this native contract run. No protected `legacy/` or original package-manifest file was changed. `local-run-004` is the sole final W06 run in this gate directory. Earlier developmental runs were moved to `/workspace/.tools/erc8183-dev-runs/` and are excluded from this result.

**Independent verifier:** `tests/test_erc8183_local.py` re-runs the native flow on a fresh local chain and reconstructs token balances from raw receipt logs without relying on the runner's balance arithmetic. **Next work order:** W07, replay the same fixed auditor verdict from equal submitted-state snapshots with and without a custom application evidence guard.
