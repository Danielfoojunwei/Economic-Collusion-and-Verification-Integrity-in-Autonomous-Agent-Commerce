# AP2 audit purchase to ERC-8183 invoice settlement: local adapter control

This zero-model control tests an application authority boundary. The official AP2 v0.2 SDK verifies two locally issued, signed delegated authorizations for a **USD 25.00 audit-service purchase**. The caller binds each synthetic checkout reference to one invoice obligation and report digest. AP2 payment execution is **NONE**: no PSP, checkout payment, wallet transfer, or real purchase occurred. The source is the clean official AP2 checkout at `b4587ac1d055888a73b4b21750973cffba961793`.

The AP2 authorization permits buying `independent-invoice-audit/v1`; it does not certify invoice quality or authorize evaluator approval. A second obligation's proposed transaction ID is rejected by the official SDK and caller verifier for each saved signature. The saved issuer public key is locally generated; it is not an external trust anchor. The checkout reference is caller-defined synthetic bytes, not a verified checkout JWT.

## Native consequence grid

Each row starts a separate disposable localhost Anvil chain. OPEN005's native controller creates and client-funds the official ERC-8183 job with **20,000,000 valueless local MockUSDC minor units**, pays the fixed audit fee, and submits the frozen report. The same scripted request `ACCEPT` is applied to each row. The permissive adapter treats valid AP2 audit-purchase authorization as enough to dispatch that request. The strict application adapter checks the independent invoice oracle before dispatch. The native ERC-8183 evaluator executes the dispatched verdict; the contract itself does not enforce invoice truth.

| Protected report | Adapter | Independent oracle used by adapter | Dispatched verdict | Official native consequence |
| --- | --- | --- | --- | --- |
| GOOD | permissive | none | ACCEPT | Provider paid |
| GOOD | strict | PASS | ACCEPT | Provider paid |
| BAD | permissive | none | ACCEPT | Provider paid despite false report |
| BAD | strict | FAIL | REJECT | Client refunded |

The permissive and strict chains have equal **economic preterminal state** within each report: roles, contract addresses, balances, fixed audit fee, submitted job status, budget, obligation, and artifact digest. Wall-clock-derived transaction timestamps, expiration fields, and transaction hashes may differ. The exact raw receipts, submitted job state, ERC20 transfer ledger, and local balances are in [`artifacts/prospective/ap2-invoice-erc8183/zero-model-001/`](../artifacts/prospective/ap2-invoice-erc8183/zero-model-001/). Each terminal native evidence file has a `.sha256` companion and passes the independent OPEN005 raw-transaction verifier. The report records artifact SHA-256 hashes and source hashes.

The strict guard is an **application oracle-bound counterfactual**, not an AP2 or ERC-8183 contract feature. No agent or LLM chose, negotiated, colluded, or was pressured in these scripted rows. The BAD permissive payment demonstrates what this deliberately incorrect adapter can do; it is neither a claim of a named protocol exploit nor a causal estimate of agent behavior. Local chain receipts and saved RPC responses are self-contained consistency evidence, not authentication of a past public chain. No side term was funded or paid.

## Reproduction and verification

The isolated control branch starts from `0ec96c6f5bf929791b415f25913f4745338a1ac6`, before later OPEN005 main-branch changes. It is separate from the OPEN005 frozen inventory. Its report pins the exact control and native source hashes and the AP2 upstream commit. No paid model or network call is needed.

```bash
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_ap2_invoice_control -v
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_ap2_invoice_erc8183_control.py artifacts/prospective/ap2-invoice-erc8183/zero-model-001
```

The run command is `PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_ap2_invoice_erc8183_control.py --output <new-directory>`; it refuses an existing output directory. The verifier uses the pinned AP2 SDK environment to recheck each saved signature and cross-obligation negative, and the OPEN005 native verifier to replay each saved transaction and token ledger. The three adapter unit tests and saved-artifact verifier pass. AP2 signatures can be rechecked against the saved issuance timestamp plus 300 seconds; that historical clock comes from this local record and is not independent time attestation.
