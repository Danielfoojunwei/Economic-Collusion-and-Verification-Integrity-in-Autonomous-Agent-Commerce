# Native ERC-8183 payout receiver control

**Evidence cut:** 2026-10-15. **Status:** PASS for the narrow contract/payment question. Three scripted cases, zero model calls, no real money. This is not observed collusion or a finding that ERC-8183 is exploitable.

## Question and pinned source

Can a job with *distinct* nominal `provider` and `evaluator` addresses set its `payoutReceiver` to the evaluator address, and where does the fixed 20,000,000-unit MockUSDC budget go on APPROVE versus REJECT? The [pinned reference contract](https://github.com/erc-8183/base-contracts/blob/142e669c1fd318486a4628395b629f033654dd06/contracts/ERC8183.sol) disallows `provider == evaluator` at job creation, while `setPayoutReceiver` excludes the escrow and payment-token addresses and `_payout` routes provider-side net funds to the receiver. This control executes those functions on a fresh local chain for each case.

Upstream `erc-8183/base-contracts` commit: `142e669c1fd318486a4628395b629f033654dd06`. Pinned submodules: forge-std `620536fa5277db4e3fd46772d5cbc1ea0696fb43`, OpenZeppelin contracts `5fd1781b1454fd1ef8e722282f86f9293cacf256`, upgradeable `7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf`. Each disposable Anvil chain uses ID 31337, valueless six-decimal MockUSDC, 10% native evaluator fee, and zero platform fee. The output [manifest](native-001/manifest.json) binds each case's raw evidence hash.

## Native results

| Scripted case | Receiver | Final action | Client net | Provider net | Evaluator net | Native release |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Direct approve | unset, so provider | APPROVE | −20,000,000 | +18,000,000 | +2,000,000 | Provider 18,000,000; evaluator fee 2,000,000 |
| Evaluator receiver approve | evaluator address | APPROVE | −20,000,000 | 0 | +20,000,000 | Evaluator receives both net 18,000,000 and fee 2,000,000 |
| Evaluator receiver reject | evaluator address | REJECT | 0 | 0 | 0 | Client receives full 20,000,000 refund |

Each case includes three negative native transactions: the client cannot create a job whose nominal provider equals evaluator; the evaluator cannot assign the payout receiver; and the provider cannot change that receiver after funding. Those transactions reverted, retained no logs, and changed no MockUSDC balance. In the evaluator-receiver cases, the provider's **Open-state** assignment succeeded and emitted `PayoutReceiverSet`. All three provider and evaluator *role addresses* remained distinct, and no prior partial claim occurred. Of 53 archived local transactions, 44 succeeded and 9 were intentional guard reverts.

The provider-side payment and evaluator fee converging on one EOA establishes **possible payout custody concentration** despite distinct job roles. An address alone does not establish beneficial ownership or the agent's incentives. This is a permitted provider-managed custody option in the specification; a marketplace that needs an independent evaluator must enforce its own payout-recipient and beneficial-owner policy before funding. Rejection produced no evaluator fee or provider-side release in this no-prior-claim control.

## Reproduction and checks

```bash
python scripts/run_erc8183_receiver_control.py --output /tmp/new-erc8183-receiver-control
python scripts/verify_erc8183_receiver_control.py --input /tmp/new-erc8183-receiver-control
python scripts/verify_erc8183_receiver_control.py --input artifacts/prospective/erc8183-receiver-control/native-001
python -m unittest tests.test_erc8183_receiver_control -q
```

All commands passed on the evidence cut. The independent verifier does not import the runner. It checks the upstream/ABI and runner hashes, fixed transaction order and roles, the failed guard receipts, native calldata, ERC-20 Transfer logs, indexed fee/release/refund events, and actor balances reconstructed from raw receipts. Five negative test categories changed receiver calldata, reverted status, payee/amount events, rejected-job balances, or attempted archive overwrite; all failed closed. The archive includes native transaction and receipt JSON, compiled artifact hashes, local process logs, and SHA-256 files.

**Evidence boundary:** `SCRIPTED_SIMULATION` agent behavior plus `NATIVE_LOCAL_PROTOCOL` payments. The evaluator actions were authored; there is no verified BAD invoice, auditor check, provider request, auditor assent, wrongful payment, real token, or model call in this control. A live agent test would need to freeze independent task truth, disclose or hide payout custody by randomized assignment, measure the auditor's check and verdict, and link any improper request and assent before calling it bilateral collusion. This control neither spends nor reserves OpenRouter budget.
