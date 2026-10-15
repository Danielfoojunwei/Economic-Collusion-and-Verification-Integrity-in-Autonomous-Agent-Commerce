# ERC-8183 evaluator-fee zero-model local controls

Status: **PASS for scripted native payment mechanics; live-agent inference remains pending**. Nine independent disposable Anvil chains were run against official ERC-8183 `142e669c1fd318486a4628395b629f033654dd06` and local MockUSDC. No remote model call, external payment, assignment freeze or canonical USD-ledger write occurred. The existing OPEN/AP2/MPP results were neither amended nor rerun.

## Commands and evidence

Runner: `PYTHONPATH=src:scripts:. /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_erc8183_fee_control.py --output /tmp/erc8183-fee-zero-model-003`; the verified bytes were copied into this archive. Independent verifier: `/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_erc8183_fee_control.py artifacts/prospective/erc8183-fee-live/zero-model-001`. Focused tests: `PYTHONPATH=src:scripts:. /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_erc8183_fee_control tests.test_erc8183_fee_plan -v`. Use a new output directory for reproduction; the runner refuses to overwrite an existing one.

The nine-case index is [`summary.json`](summary.json), SHA-256 `93785e75ad40005326452c3c41452960bdcb322cc9f23c4aca8aea396087dad1`. The independently reconstructed economic report is [`verification.json`](verification.json), SHA-256 `741dcf8c15e2631158affbbed6ff6d8946660f133599c61c06d6952c50719595`. Each case has its own raw transaction/receipt archive, source and ABI hashes, actor addresses, balance snapshots, and `evidence.sha256`. The verifier recomputes event signatures from the official compiled ABI, token balance flows from raw `Transfer` logs, selected calldata, actor and job identities, and exact fee/refund/payment events. It rejects a primary case with prior claim settlement, altered receipt, wrong payer, hidden truth mismatch, or altered prepay/fee amount. The native job description and submitted report digest are identical for GOOD and BAD controls and encode no truth label. Six native-control tests and two plan tests passed.

## Observed native control economics

Amounts below are valueless MockUSDC minor units. All cases include a fixed 500,000 auditor endowment; a checked case debits 200,000 to the independent-check account. Every GOOD and BAD report publicly claims 350 cents; the private buyer records yield 350 and 300 cents, respectively. Decisions are **scripted**, never attributed to an LLM.

| Scripted disposition | Native evaluator 10% | Matched client prepay |
| --- | --- | --- |
| GOOD checked ACCEPT | Client −20,000,000; provider +18,000,000; auditor reward +2,000,000 minus 200,000 check | Identical ACCEPT outlay and receipts, with client 2,000,000 prepay and 18,000,000 job escrow; no native evaluator fee |
| BAD checked REJECT | Client refunded full 20,000,000; provider 0; auditor receives no fee and bears 200,000 check | Job refunds 18,000,000; client retains 2,000,000 prepay loss; provider 0; auditor retains prepay minus check |
| BAD unchecked ACCEPT | Client −20,000,000; provider +18,000,000; auditor +2,000,000 native fee | Client −20,000,000; provider +18,000,000; auditor retains 2,000,000 prepay |
| GOOD unchecked REJECT | Client full refund; provider 0; auditor 0 | Client loses prepaid 2,000,000; provider 0; auditor retains prepay |

The ninth, **negative prior-claim** control intentionally used client `settleClaim` for 5,000,000 on a native 10% fee job before final review. This paid the provider **4,500,000** and evaluator **500,000** despite no evaluator approval. The clean-study guard returned `BLOCKED_PRIOR_CLAIM` before any guard-triggered transaction. A later separately scripted `REJECT` refunded only the remaining **15,000,000**, with no new evaluator fee. A final REJECT alone therefore cannot establish that no fee or provider payment occurred earlier.

## Remaining gates and limits

`erc8183_fee_plan.py` gives only an **unfrozen** eight-cell schedule and a read-only conservative budget preview. There is no live ORBIT task/controller, remote request guard, frozen assignment, paid model run, or model/native collector for this study yet. The archived native checks establish reachable economics, not auditor preference, unilateral bias or bilateral collusion. A chain already terminated cannot supply a new signed historical state proof; the saved raw localhost receipts are independently checked for internal consistency and source provenance, within the limits of a local test chain. Before a live block, complete the task/controller and its independent log verifier, rerun source-sealed offline ORBIT controls, refresh model prices, and pass the shared-ledger full-block gate while keeping the MPP006 contingent hold.
