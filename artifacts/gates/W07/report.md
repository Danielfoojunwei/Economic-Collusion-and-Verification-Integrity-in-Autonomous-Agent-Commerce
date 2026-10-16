# W07 — fixed-decision ERC-8183 replay

**Status: PASS for a scripted, native-local enforcement replay.** This does not establish a live-agent behavioral effect or a practical priced guard.

## Reproduce

Run from the repository root after the pinned Foundry/solc/ERC-8183 setup described in `artifacts/gates/G2/report.md`:

```bash
python scripts/run_erc8183_replay.py --output artifacts/gates/W07/native-run-NEW
python -m unittest tests.test_erc8183_replay -v
```

The recorded run is `native-run-001/evidence.json`, SHA-256 `30d0470a003273898ace5e9cd5cee37ccdec9fa396ac2dbf401770fd8c15be39`. Its local Anvil, offline Forge build, deployed implementation/proxy/token ABI and bytecode hashes, test wallets, raw transaction inputs, native receipts, log indexes, state reads and balances are in the JSON. The three replay tests passed; captured output is in `tests.stderr.txt`. No external RPC or asset was used.

## Paired result

Each fixture uses a *single authored, unchecked ACCEPT* from `AuditState.submit`. Its canonical SHA-256 is the native completion attestation in both arms. After a worker submits the artifact digest and the client funds 20,000,000 minor units of valueless MockUSDC, the runner takes `evm_snapshot`. It executes the unguarded arm, saves `eth_getTransactionByHash` and receipt data, calls `evm_revert`, and verifies that block hash, job state, balances, pending claim, job counter and account nonces equal the saved pre-state before the guarded arm. Thus paired actions start from the same native state; reverted-arm receipts are archival branch evidence and are not all transactions on one final canonical chain.

| Fixture | Independent truth | Unguarded dispatch | Guarded dispatch | Provider settlement (unguarded / guarded) |
| --- | --- | --- | --- | --- |
| Good | PASS | Native `complete`, `Completed` | Native `complete`, `Completed` | 17,000,000 / 17,000,000 |
| Bad | FAIL | Native `complete`, `Completed` | Application guard directs native `reject`, `Rejected` and full client refund | 17,000,000 / 0 |

The remaining 3,000,000 units on each completion are the configured evaluator and platform fees. Both arms' terminal replay transactions revert with status zero and no logs; the tests reconstruct token balance changes independently from the receipts' `Transfer` events. The good case uses identical evaluator nonce and `complete` calldata across forks. The bad case uses the same frozen ACCEPT input and nonce, but the application dispatcher substitutes `reject` after a trusted check.

## Enforcement boundary and limits

The pinned ERC-8183 contract enforces who may complete/reject, job state transitions and payment accounting. It does **not** establish that a submitted artifact is correct. The unguarded bad case proves a designated evaluator can natively release payment for wrong work. The guard is custom application code outside the contract: it checks task and artifact digest binding and consults the independent fixture oracle; on failure an authorized dispatcher asks the evaluator to reject. This oracle-backed guard is an ideal upper bound with one additional check per guarded arm, not a priced or deployable defense. Its result must not be counted as ERC-8183's native semantic enforcement.

The two verifier outputs are scripted controls, not samples from an LLM or evidence of economic collusion. No uncertainty estimate or cross-protocol security ranking follows from two fixtures. The exercise identifies only downstream native settlement consequences under a frozen action and an explicitly added application guard.
