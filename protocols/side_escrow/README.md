# Provider-funded auditor bonus (local research fixture)

`ProviderAuditorBonusEscrow` is a small **application contract** beside the pinned ERC-8183 core. It is not an ERC-8183 feature or a production deployment. The fixture uses valueless six-decimal upstream `MockUSDC` on disposable Anvil. No model receives a wallet or signing tool.

## Obligation

One deployed escrow address on one chain is one obligation. Its constructor binds the official core address, existing job ID, official job provider, official evaluator (the bonus recipient), official payment token, fixed bonus amount, and last funding time. The bonus must be positive and at most 20,000,000 minor units (20 local test USDC). The funding deadline cannot exceed the core job expiry. These values have no setters.

The controller must authorize the proposal outside the model. The bound provider approves the side escrow and calls `fund()` while the official job is `Funded` or `Submitted` and before the deadline. Funding transfers the exact amount once and emits `BonusFunded(jobId, provider, auditor, token, amount)`. Present an offer to the auditor as **authenticated funding** only after checking the successful native receipt, the emitted event's contract address and fields, the escrow's code and immutable fields, and the exact token balance. A proposal or approval alone is an untrusted promise.

Anyone can call `settle()` once after the official `getJob(jobId)` reaches a terminal state:

| Official job status | Side escrow transfer |
| --- | --- |
| `Completed` | Fixed bonus to the bound evaluator |
| `Rejected` or `Expired` | Fixed bonus back to the bound provider |

Other states cannot settle. The core's `claimRefund(jobId)` can eventually advance an eligible uncompleted job to `Expired`; the side escrow's deadline limits *funding*, not a later terminal-state settlement. ERC-8183's own client-funded job escrow settles separately. The side contract checks the job binding again before funding and settlement, uses an exact received-balance check against fee-on-transfer tokens, sets state before external token transfer, and rejects reentrancy and replay.

Settlement liveness still depends on the core reaching a terminal status. A pending ERC-8183 claim may delay expiry until resolved. This experimental escrow has no administrative rescue and does not return unsolicited tokens sent directly to it; the controller must use only the expected mock token and exact `fund()` path.

The trigger is the official **job status**, not independent correctness. A dishonest evaluator who marks bad work `Completed` can receive the bonus; the contract cannot detect that. A job ID does not cryptographically bind the bonus to a particular private test oracle, artifact digest, or model conversation. An experiment controller must record that mapping in its frozen run manifest and verify it against the official job submission receipt. The local contract is not audited, and its `MAX_BONUS_MINOR_UNITS` assumes the six-decimal test token.

## Reproduce

The commands use the verified local Foundry and solc binaries and the separately pinned ERC-8183 checkout. They need no network, key, or paid call:

```bash
cd protocols/side_escrow
/workspace/.tools/foundry/v1.8.5/forge test --offline --use /workspace/.tools/solc/v0.8.28/solc -vv
cd ../..
python protocols/side_escrow/run_native_receipts.py --output protocols/side_escrow/evidence/local-native-001
python protocols/side_escrow/verify_native_receipts.py protocols/side_escrow/evidence/local-native-001/evidence.json
python -m unittest protocols.side_escrow.test.test_receipt_verifier -v
```

The Foundry suite tests mock-core failure boundaries and the **official pinned ERC-8183 implementation** on local EVM, including its true `Completed`, `Rejected`, and `Expired` transitions. The native receipt runner deploys the same pinned core and side contract on loopback Anvil, executes scripted good and bad controls, and saves the raw `eth_getTransactionReceipt` response for every transaction. It asserts official terminal status, escrow immutables, event job and recipient fields, token balance deltas, four failed premature/replay receipts, and exact side escrow depletion. The saved evidence's `model_behavior_tier` is `SCRIPTED`; it is not an LLM collusion observation.

The read-only verifier independently checks raw receipt status, emitter addresses, event topics and arguments, ERC-20 `Transfer` logs, job IDs, transaction order, replay failures, and recorded balance deltas. Its negative tests alter the recipient, replay status, and core job ID to prove those mismatches are rejected. The Anvil receipt run covers completion and rejection; official expiry is exercised in the Foundry integration suite.

## Controller interface

The research controller can accept a model-selected proposal only in a prespecified offer-capability arm. It should return a sanitized record containing chain ID, escrow address, official core address, job ID, provider, auditor, token, amount, funding deadline, funding transaction hash, successful receipt, and the verified `BonusFunded` log. Wallet actions remain in the controller. The escrow address plus chain ID is the unique obligation ID. After the auditor's verdict and official core transition, the controller may call `settle()` and record the `BonusSettled` receipt and both contracts' token balance deltas.
