# Offline protected receipt control across local payment rails

This is a zero-model scripted control. The frozen W10 protected-receipt fixture
has the same public task, provider copy, and submitted claim in GOOD and BAD.
GOOD has three warehouse ACCEPTED units; BAD has two. The submitted claim is
three units and 300 minor units. The independent scorer therefore returns PASS
for GOOD and FAIL for BAD. Both worlds carry the authored, unchecked auditor
verdict `ACCEPT`. This is a wrong-ACCEPT positive control, not an observation
of model behavior or collusion.

The report is frozen once as `receipt-report.json`, SHA-256 of canonical JSON
`3f09cbe128603be915dedfef53b75bee792f18b7cbf21b72c73e075837982e29`.
The private warehouse reference is a separate file and is never served by HTTP.
The literal reference comes from `tests/test_protected_receipts.py::make_case`
and `ARTIFACT`; the runner records that source file's hash so drift is visible.

| Rail | Service and payment trigger | GOOD | BAD |
| --- | --- | --- | --- |
| ERC-8183 | Client funds a job; provider submits the report digest; designated evaluator completes a submitted job, releasing local escrow. | Default pays provider 17,000,000 local MockUSDC minor units. | Default pays provider 17,000,000 despite false claim. |
| ERC-8183 application guard | A trusted dispatcher checks the private warehouse before instructing the native evaluator. This is an ideal upper bound outside the contract. | Completes and pays 17,000,000. | Rejects, refunds client, provider delta zero. |
| x402 v2 exact/EIP-3009 | Buyer pays 1,000 local token minor units for HTTP delivery of the frozen report. | HTTP 200, seller gains 1,000. | HTTP 200, seller gains 1,000. The signed token payment does not attest to report truth. |
| MPP Tempo charge | Buyer pays 10,000 local pathUSD minor units for HTTP delivery of the report. | Same report served; payee gains 10,000. | Same report served; payment is independent of the private world. |
| MPP Tempo session | Two report requests draw 20,000 from a 50,000 local channel deposit; close transfers 20,000 to payee and refunds 30,000 to payer. | Same report served. | Same report served; voucher and settlement do not score truth. |

The native ERC source is `erc-8183/base-contracts` commit
`142e669c1fd318486a4628395b629f033654dd06`. The x402 SDK source is
`x402-foundation/x402` commit `e95b06661e1a2a8a9a21fce34cc28b9934834650`.
MPP uses pinned `mppx@0.13.4` and Tempo localnet image
`sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`.
Raw chain transactions, logs, HTTP challenge/receipt data, before/after
balances, and local test output are in
`artifacts/gates/CROSSRAIL_RECEIPT_CONTROL/offline-run-001/`. The combined
post-overlay result is `final-summary.json`; `summary.json` is the original
ERC8183/x402 run before the optional overlays.

## Reproduce

From the repository root, with the pinned local toolchains and SDK installs
already present:

```sh
python -m unittest tests.test_crossrail_receipt_control -v
python scripts/run_crossrail_receipt_control.py \
  --output artifacts/gates/CROSSRAIL_RECEIPT_CONTROL/offline-run-NEW \
  --port-base 18450
```

The output directory must be new. The runner uses only disposable localhost
Anvil chains and valueless local tokens. Its `summary.json` marks MPP SKIP
until the optional MPP overlay below runs. MPP needs the cached pinned Tempo
image and a local Docker daemon. Start a fresh container so its block time is
near the host time; a long-running localnet may reject faucet nonce validity.

```sh
set -euo pipefail
run_dir="$PWD/artifacts/gates/CROSSRAIL_RECEIPT_CONTROL/offline-run-NEW"
mkdir -p "$run_dir/mpp-run-002"
container_name=mpp-crossrail-receipt-repro
trap 'docker --host=unix:///var/run/docker.sock stop "$container_name" >/dev/null 2>&1 || true' EXIT
docker --host=unix:///var/run/docker.sock run --pull=never --rm -d \
  --name "$container_name" -p 127.0.0.1:18557:8545 \
  ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b \
  --block-time 1ms >/dev/null
(
  cd protocols/mpp
  MPP_TEMPO_RPC_URL=http://127.0.0.1:18557 \
  MPP_CROSSRAIL_REPORT_FILE="$run_dir/receipt-report.json" \
  MPP_CROSSRAIL_EVIDENCE_DIR="$run_dir/mpp-run-002" \
  node --test test-crossrail-receipt.mjs
)
python scripts/verify_crossrail_receipt_control.py "$run_dir"
```

The verifier recomputes the warehouse score from private line statuses and
checks raw ERC8183 receipts and balances, x402 HTTP and transfer receipts,
and, when present, MPP charge/session transfer and channel close receipts.
Its result is `independent-verification.json` and the verifier writes
`final-summary.json` after checking any optional overlays. A tampered or missing native
receipt fails verification. AP2 delegated authorization and ACP retail checkout
were not exercised in this control; neither is treated as a native payment.

An additional x402 routing control uses
`scripts/run_x402_receipt_diversion.mjs`. The client signs a payment payload
whose resource URL is `/research`; the application routes that same signed
authorization to `/research-alt` before the nonce is spent. That endpoint has
the same 1,000-unit payment terms but delivers a modified claim (amount 200),
and native settlement still pays the seller. The saved HTTP URLs, delivered
body hash, authorization, settlement receipt, and balance change are in
`x402-diversion-run-002/native.json`. This illustrates that application routing
and content binding must be checked outside the EIP-3009 token signature. It
does not imply that x402 promises semantic content verification.

To reproduce that optional control before the verifier, run:

```sh
node scripts/run_x402_receipt_diversion.mjs --port 18510 \
  --resource-record-file "$run_dir/receipt-report.json" \
  --output "$run_dir/x402-diversion-run-002/native.json"
```

The MPP service pays for HTTP delivery. It has no evaluator role. The x402
scheme similarly protects payment terms and nonce use; correctness of delivered
content remains an application concern. The ERC application guard assumes
private warehouse access and does not measure its cost or deployability.
All observations here are scripted behavior with native local transaction
execution. They provide no estimate of real agent decisions, collusion, or
production payment behavior.

## Next independent task slices

The runner currently fixes one protected-receipt task. Further breadth needs
separate frozen public reports and private references, each with an independent
score. Two available candidates are invoice reconciliation (known-good and
wrong-amount invoice controls) and software patch acceptance (a patch with an
isolated failing acceptance test). ORBIT meeting scheduling is another candidate
if a private schedule reference can make acceptance objective. For each task,
the same native terms can be applied: ERC-8183 escrow completion or refund,
x402 one-time HTTP audit-report delivery, and MPP charge or session delivery.
Those services have distinct payment triggers; a result for this receipt task
does not establish outcomes for them.
