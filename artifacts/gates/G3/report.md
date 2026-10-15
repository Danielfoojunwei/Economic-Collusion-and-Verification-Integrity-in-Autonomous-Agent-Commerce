# G3 / W08 — native x402 v2 localhost

**Work ID:** W08. **Result:** PASS for the exact/EIP-3009 localhost slice. W09/A14 cross-flow replay is separate and pending. No live model, real asset, public chain, external RPC, or testnet was used.

## Source and execution tier

- Official source: `x402-foundation/x402` at `e95b06661e1a2a8a9a21fce34cc28b9934834650` (Apache-2.0), `@x402/core`, `@x402/evm`, `@x402/express`, `@x402/fetch` 2.28.0, x402 v2 `exact` with EIP-3009. The upstream `typescript/pnpm-lock.yaml` SHA-256 is `227bb649f1a6ca5c2c9f50e6c9bffe9516894aaa18f6551df24d4bf03ebbe8d2`; package manager is pnpm 11.1.1. The checkout is outside this repository at `/workspace/upstreams/x402`.
- Local tools: Node 24.19.0, Anvil 1.8.5, solc 0.8.28. SDK packages were installed with the frozen lockfile and built from the pinned checkout. The script verifies the commit at runtime and compiles the local test token from source.
- Model execution tier: `SCRIPTED_SIMULATION` (no model decision). Payment execution tier: `NATIVE_LOCAL_PROTOCOL` (official SDK, real EIP-712 signature and local EVM transaction). The token is minted solely on a disposable Anvil chain and has no real value. The well-known Anvil mnemonic derives public local test accounts only; no key is saved in evidence.

## Commands actually run

From `/workspace/upstreams/x402/typescript`:

```sh
COREPACK_HOME=/tmp/x402-corepack XDG_CACHE_HOME=/tmp/x402-cache corepack pnpm --filter '@x402/evm...' --filter '@x402/express...' --filter '@x402/fetch...' install --frozen-lockfile --store-dir /workspace/upstreams/.pnpm-store --reporter=append-only
COREPACK_HOME=/tmp/x402-corepack XDG_CACHE_HOME=/tmp/x402-cache corepack pnpm --filter '@x402/evm...' --filter '@x402/fetch...' -r --workspace-concurrency=2 run build
COREPACK_HOME=/tmp/x402-corepack XDG_CACHE_HOME=/tmp/x402-cache corepack pnpm --filter '@x402/express...' -r --workspace-concurrency=2 run build
```

From this repository root:

```sh
node scripts/run_x402_local.mjs --port 18545 --output artifacts/gates/G3/native-run.json
node --test tests/test_x402_local.mjs
```

Both local commands passed. The focused official upstream core, EVM and fetch tests previously passed 433/433. The project test passed 1/1; output is in `test.log`. The runner uses RPC `127.0.0.1:18545`, facilitator HTTP `127.0.0.1:18555`, and resource HTTP `127.0.0.1:18556`. `X402_SDK_ROOT`, `X402_ANVIL`, and `X402_SOLC` override the default local paths; `X402_TEST_PORT` overrides the test's default RPC port 18565.

## Acceptance evidence

| Test | Result | Evidence |
|---|---|---|
| A11 challenge | PASS | Unpaid GET returned 402 and the official `PAYMENT-REQUIRED` v2 schema: `exact`, `eip155:31337`, 1,000 token atomic units, local token address and seller address. |
| A12 native authorization | PASS | Official client signed EIP-712 EIP-3009 authorization, official facilitator verified it without changing nonce, balances or block, and the test independently recovered the buyer signer. Fresh unspent signatures were rejected for wrong amount, wrong payee and expired authorization. Paid nonce replay was rejected with HTTP 402; direct token simulation reverted `AuthorizationAlreadyUsed`. A tampered payee failed the token's on-chain signature check. |
| A13 timing and settlement | PASS | Trace order is `CHALLENGE`, `SIGNED_AUTHORIZATION`, `VERIFY`, `RESOURCE_EXECUTE`, `SETTLE`, `RESPONSE`, with UTC and monotonic timestamps. Settlement mined in block 3: successful receipt, `transferWithAuthorization` calldata, `AuthorizationUsed` and `Transfer` logs, buyer 1,000,000→999,000 and seller 0→1,000, nonce unused→used. The `PAYMENT-RESPONSE` transaction matches the receipt. |
| Fault boundary | PASS | A separate paid resource handler deliberately returned 503 after a successful verify. Official Express middleware skipped settlement: no `/settle` call, no payment response header, unused nonce and unchanged balances/block. |
| A14 frozen cross-flow replay | SKIP | W09 depends on W07 and W08 and is a separate work order. W08 exposes `resourceRecord` for its frozen input. |

Full machine-readable evidence is in `native-run.json`, including the 402 requirements, public signed authorization, facilitator read-only snapshots, receipt, event logs, exact negative results and fault snapshots. The local receipt proves transaction inclusion on the disposable Anvil chain; it does not claim public-chain consensus finality.

Final SHA-256 fingerprints (the evidence file is frozen after this report):

| File | SHA-256 |
|---|---|
| `native-run.json` | `0c96e524bcde4ed9de7dd886a3c540f5ec518db53cd2f16e537b9565257bf857` |
| `test.log` | `01b729d0bae403de4b34f74d028d8461b1cf687f1857ae24bac673e92867ca9c` |
| `TestEIP3009Token.sol` | `4decd30c239f09aa0b3ee4df76ce1078020fdc30c9925d7d24f9cf3dfae55640` |
| `run_x402_local.mjs` | `f7a4c21b625e916def700e7e6741ea02163bd71a45a07a8f81bbd0fc43cff2e0` |
| `test_x402_local.mjs` | `bb6d6116647e4c52db438d79915a76ab3209608f5b2ca16fd29c371eae45b4cc` |

## Threat assumptions and limits

- The test token is a minimal, signature-verifying ERC-20/EIP-3009 implementation at `contracts/x402/TestEIP3009Token.sol` (source SHA-256 `4decd30c239f09aa0b3ee4df76ce1078020fdc30c9925d7d24f9cf3dfae55640`), not the upstream test mock. The signature binds chain ID, token contract, payer, payee, amount, validity window and nonce. Solc compiles it in memory; no shared Foundry build output is touched.
- The official client required an explicit spend-control allowlist for this non-default local asset; the runner caps each payment at exactly 1,000 atomic units.
- EIP-3009 does **not** sign the HTTP resource URL, returned content, task or auditor verdict. The facilitator accepted a fresh valid authorization whose `resource.url` metadata was altered. An application-level record guard would be additional logic and must be labeled as such. The payment here pays for access to the route; it does not certify that a served audit record is true.
- The isolated Anvil chain does not deploy the canonical Multicall3 helper used by the SDK's optional failure diagnosis. For replay, the SDK returned `invalid_exact_evm_transaction_simulation_failed`; its raw revert says `AuthorizationAlreadyUsed`, and both the token's nonce state and a direct on-chain simulation corroborate that cause. No substitute mock result was supplied to the SDK.
- The fault test establishes no settlement on a handler 503 in the default after-handler flow. It does not assess process crashes, chain reorganization, alternative x402 flows or a remote facilitator.

## Delivered paths and next work

- `contracts/x402/TestEIP3009Token.sol`
- `scripts/run_x402_local.mjs`
- `tests/test_x402_local.mjs`
- `artifacts/gates/G3/native-run.json`, `test.log`, this report

W09 can supply a frozen public audit record with `--resource-record-file PATH` or `runLocalX402({ port, output, resourceRecord })`; the exact JSON served after payment appears as `http.resourceBody` in evidence. No backward compatibility or migration is required. No owner approval is needed for this local slice; paid model calls, public/testnet traffic and deployment beyond localhost remain separate owner decisions. Next eligible work order: W09.
