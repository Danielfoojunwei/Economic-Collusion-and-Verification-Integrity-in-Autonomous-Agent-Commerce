# W14 — MPP charge and session on local Tempo

**Decision: PASS for the local native charge and session paths exercised here.** This is a valueless localhost protocol integration. It is not an LLM behavior result, a testnet/mainnet payment, or evidence of collusion.

## Work order record

| Field | Record |
|---|---|
| Work ID / gate | W14 / G6 |
| Project source | Base `e953d182659f57072fc4cf9c65d323ef9d2217ba` plus uncommitted W14 files under `protocols/mpp/` and this report |
| SDK | Official [`wevm/mppx`](https://github.com/wevm/mppx) tag `mppx@0.13.4`, commit `d8d800f101ba1568f0d737e12574c0ae8f6b6e93`, MIT; installed npm `mppx@0.13.4`, `viem@2.57.1` with the full frozen `protocols/mpp/package-lock.json` (SHA-256 `ddf7c365ba0467210452056dd734548a3247ac91783e8b01d99538ee3d48a3ad`) |
| Protocol specification | [`tempoxyz/mpp-specs`](https://github.com/tempoxyz/mpp-specs) commit `50309c8e67e6d64b5547f1cc354fb327bda1301e`, `draft-tempo-charge-00.md` and `draft-tempo-session-00.md`; specs CC0 1.0 |
| Localnet provenance | [`tempoxyz/mpp`](https://github.com/tempoxyz/mpp) commit `39ec9f1b9f6f121d7c0920833476ce66186394c4` pins `ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`. Pulled digest matched; OCI image label identifies Tempo source revision `86ff4deaebfee38bb0b000e648b2b367810265ff` and Apache-2.0 license. |
| Execution tier | `LOCAL_NATIVE`, Tempo chain ID 1337; valueless local pathUSD TIP-20 at `0x20c0000000000000000000000000000000000000` funded by the local `tempo_fundAddress` RPC |
| Test outcome | `node --test`: 3/3 pass; independent `verify-evidence.mjs`: PASS, 5 live transaction receipts re-read, 16 HTTP events checked |
| Delivered paths | `protocols/mpp/package.json`, `package-lock.json`, `test-local.mjs`, `verify-evidence.mjs`, `.gitignore`; `artifacts/gates/G6/W14/evidence.json`, test and verifier stdout, this report |
| Backward compatibility | No changes to `legacy/` or package-manifest files. All W14 code and dependencies are isolated under `protocols/mpp/`. |
| Owner decision | None for further localhost work. Testnet, mainnet, and external payment traffic remain outside this run. |
| Next eligible work | W15 AP2, W16 Virtuals ACP, and W17 broader protocol compositions, subject to their prerequisites. |

## What was observed

**Charge.** The unauthenticated HTTP request returned a Tempo `charge` 402 challenge with amount 10,000 raw pathUSD units, recipient, chain, and future expiry. The SDK client submitted a local Tempo transfer and retried with a `Payment` hash credential. The server returned 200 with an MPP receipt referencing transaction `0x006b45bfc49cb4c7384fecb4dcc34acb0dc33769bde805892eb361128332a6af`. The confirmed TIP-20 `Transfer` event moved exactly 10,000 units from payer to payee, and the payee balance increased by that amount. Reusing the same credential returned 402 with “Transaction hash has already been used.” The charge store is in memory for this single-process pilot.

**Session.** The initial 402 `session` challenge led to a signed `open` credential and confirmed `ChannelOpened` transaction `0x8e382c13f9ff97e0ec87bbfcaabd3284001d731d772c246364010afb4714c7b2`, depositing 50,000 raw units into the canonical Tempo escrow. A second request used an off-chain signed voucher, raising cumulative authorization from 10,000 to 20,000 units while the payee's on-chain balance remained unchanged. The SDK returned 204 on the close management request and confirmed `ChannelClosed` transaction `0xa07dd180454a41bbde085e7a8a992250da2724173ad824dc0098c01da58f89ad`: 20,000 units settled to payee and 30,000 refunded to payer. Balances include small local gas charges; the decoded escrow event gives the exact settlement amounts.

**Negative controls.** An altered voucher amount with the original EIP-712 signature returned 402 `invalid-signature`; reusing an accepted cumulative voucher returned 402 `delta-too-small`. A separate manager capped at 10,000 units opened a channel, served one request, then refused a second 10,000-unit request with `requested voucher amount 20000 exceeds local maxDeposit 10000`. It closed with 10,000 settled and no refund. All negative controls used the same official server/client SDK and local chain.

The evidence file records `execution_tier=NATIVE_LOCAL_PROTOCOL` for each outcome, challenge/receipt fields, credential hashes and action types, balances, block numbers, raw logs, decoded transfer/channel events, local transaction hashes, and source hashes. Raw authorization headers are not persisted. Wallets derive from a public test mnemonic and hold no real assets. Its SHA-256 after the fresh localnet run was `1ce887b3df169cb7def1e118f0f07e665ec785468fe6ea83d3835920f9390a75`.

## Reproduce on a fresh local chain

Node 24.19.0 and npm 11.9.0 were used. A working local Docker daemon is required. Run from the repository root:

```sh
docker pull ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b
docker run --name mpp-tempo-w14 --rm -d -p 127.0.0.1:18547:8545 ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b --block-time 1ms
cd protocols/mpp
npm ci --ignore-scripts
npm run test:local
npm run verify:local
```

The test starts and stops its own HTTP server at `127.0.0.1:18548`. Both RPC and HTTP endpoints are required to be loopback addresses. To reset the ephemeral chain, run `docker stop mpp-tempo-w14` and repeat the `docker run` command; transaction hashes and evidence SHA will then change. This report's evidence came from a fresh container `e4a5e6daafd3e7906505f043da71aa8de9baf188636a2f9b84d128ceb8707398`. The independent verifier checks recorded transactions against the still-running chain and therefore must run before stopping that container. The cloud workspace used `NPM_CONFIG_CACHE=/workspace/.npm-cache` because the default home npm cache is not writable there. Set `MPP_EVIDENCE_DIR` for both `test:local` and `verify:local` to write/read a different output directory without overwriting this gate artifact.

## Scope and limitations

- MPP challenge HMAC binding, Tempo transfer execution, EIP-712 voucher validation, escrow open/close and replay behavior came from the pinned SDK and chain. The scenario, local wallets, metering amount, application content, and in-memory storage were supplied by this integration.
- The one-process charge replay store is not a durable or cross-instance idempotency test. The session store is also in memory; crash recovery and concurrent multi-server linearizability were not exercised.
- Challenge expiry was checked to be in the future on successful paths. An already expired challenge rejection and wrong-recipient charge were not run here.
- No auditor or worker agent made a payment decision in W14. Any later causal research claim must link a real agent decision to a protocol outcome and keep these protocol-only results distinct.
