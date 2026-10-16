# W09 — frozen invoice decision across escrow and paid HTTP delivery

**Status: PASS for the narrow scripted, native-local cross-flow pilot.** Both invoices reuse W07's exact public task, submitted artifact digest, unchecked scripted `ACCEPT`, and canonical decision SHA-256. W09 then delivers each submitted record through the official x402 v2 `exact`/EIP-3009 local flow. This is a payment for report delivery, while ERC-8183 releases a worker's job escrow after the designated evaluator attests. The two native payment rules are different; this run does not rank their security.

## Source, commands, and evidence

- W07 ERC-8183 source: `erc-8183/base-contracts` commit `142e669c1fd318486a4628395b629f033654dd06`; frozen W07 evidence SHA-256 `30d0470a003273898ace5e9cd5cee37ccdec9fa396ac2dbf401770fd8c15be39`.
- W08 x402 source: `x402-foundation/x402` commit `e95b06661e1a2a8a9a21fce34cc28b9934834650`; official SDK version 2.28.0, x402 v2 `exact` with a signature-verifying local EIP-3009 token.
- Model tier: `SCRIPTED_SIMULATION`; payment tier: `NATIVE_LOCAL_PROTOCOL` on disposable Anvil chains with valueless tokens. No remote model call, public RPC, testnet, or real asset was used.

From the repository root, after the local prerequisites recorded in `artifacts/gates/G2/report.md` and `artifacts/gates/G3/report.md`:

```bash
python scripts/run_w09_cross_flow.py --output artifacts/gates/W09/native-run-NEW --port-base 18620
python -m unittest discover -s tests -p 'test_w09_cross_flow.py' -v
```

The recorded run is `native-run-001/evidence.json`, SHA-256 `14b1c94f8d70d5eab4fb6b38de20adec75b5f88d89b415b8e6eed2b9613e5d1e`. Each `good/` and `bad/` directory contains the exact public record offered for sale, full x402 native evidence with signed authorization and receipt, and stdout/stderr. The W09 runner hashes the W07 evidence, its own source, the x402 source, each served record, and each child evidence file. Three focused tests passed: a fresh two-case native run, rejection of a tampered frozen decision hash before payment, and refusal to overwrite evidence.

## Observed consequences

| Invoice | Protected oracle | ERC-8183, frozen `ACCEPT` without app guard | x402, same record and verdict | W07 ideal app guard |
| --- | --- | --- | --- | --- |
| Good (`reconcile-001`) | PASS | Evaluator `complete` mined; provider received 17,000,000 local MockUSDC minor units | HTTP 200 delivered the correct record; signed authorization settled 1,000 local token units to seller | `complete`; provider received 17,000,000 |
| Bad (`reconcile-002`) | FAIL | Evaluator `complete` mined; provider received 17,000,000 for wrong work | HTTP 200 delivered the incorrect record; signed authorization settled 1,000 local token units to seller | Application oracle vetoed `complete`; evaluator `reject` refunded 20,000,000 to client |

W07 proves the paired ERC actions began from an identical submitted-job Anvil snapshot, and its independent test reconstructs native balances from receipts. W09 independently checks the common task/artifact/decision hashes, W08's successful 402 → signed authorization → read-only verify → resource execution → settlement → response sequence, a successful token receipt, one exact `Transfer` log, buyer −1,000 and seller +1,000, and a consumed nonce for each x402 case. The x402 authorization signs payer, payee, token, amount, chain, validity and nonce. It does not sign the HTTP URL, record body, artifact digest or verdict. The record linkage in W09 is an application assertion evidenced by the exact HTTP body and content hashes.

## Interpretation and limits

The wrong report was paid under both *configured applications*, but this has different meanings. In ERC-8183, the designated evaluator's `ACCEPT` released payment for incorrect submitted work. In x402, the buyer authorized payment for access to a report and received that report; the buyer saw the 402 requirements before signing and the report body only after payment. The native payment rule did not promise the report was correct. The x402 seller is an HTTP resource seller and has no native evaluator role. Wallets on the two disposable chains are separate test principals; W09 does not attest a shared cross-protocol identity. W09 does not compare the two amounts, estimate protocol vulnerability rates, or infer collusion from these authored decisions.

The W07 guard is explicitly `APPLICATION_IDEAL_ORACLE_UPPER_BOUND`. It used protected truth and did not measure its monetary cost, so its success is neither native ERC enforcement nor a deployable defense result. W09 did not add an analogous guard to x402. A14 is supported for scripted frozen-input linkage and W07's within-ERC snapshot replay; no cross-protocol identical chain pre-state or live-model counterfactual is claimed. W05 live-agent behavior and W10 economic randomized experiments remain separate prerequisites for behavioral or causal findings.

**Independent verifier:** `tests/test_w09_cross_flow.py` launches fresh local x402 transactions and compares their delivered JSON and receipt-derived payment evidence with the pre-existing W07 frozen decisions and the independent G1 fixture oracle. **Next eligible work:** W05 bounded remote-model pilot under the owner's specified `openai/gpt-5.6-sol`, high reasoning, $20 total cap, after the runner validates route, credentials, and local spend controls. W10 depends on that pilot and W09.
