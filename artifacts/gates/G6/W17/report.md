# W17 — broader protocol coverage

**Coverage result: PASS with one explicit native-composition SKIP.** This closes the W17 local coverage inventory only. It supplies no live-agent behavior, payment capture, escrow verdict, or cross-protocol ranking. [coverage.json](coverage.json) contains the required per-protocol fields.

## Pins and roles

| Protocol | Pinned primary source | Role tested | Result |
| --- | --- | --- | --- |
| OpenAI/Stripe ACP | `agentic-commerce-protocol/agentic-commerce-protocol` `7fdd78df677a94dce04c770644b0fbbb1401272b`, released `2026-04-17` schema | Retail checkout session and order contract | 4/4 local schema/mock state cases pass; no merchant SDK or PSP |
| UCP + AP2 | `universal-commerce-protocol/ucp` `d9c18e0d27c7f6892e69243fbc13df0e3685864e`, draft AP2 extension | Commerce capability negotiation plus delegated authorization | Native composition SKIP, explained below |
| A2A v1.0 | `a2aproject/A2A` `7c861a597b93208de3c19357cc0d66b9f6250e9b`; Python SDK `a2aproject/a2a-python` `a4c4fc91a22778f3d805e5e592bf690915a33033` | Agent messages and task lifecycle transport | 1/1 in-process SDK REST test passes; no money semantics |
| ERC-8004 | `erc-8004/erc-8004-contracts` `b9e466c250744a7e06b13dff9d3c2844ed64f825` | Identity, reputation, validation registries | 61/61 upstream contract tests plus 1/1 local registry scenario pass |

OpenAI/Stripe ACP is a checkout API, separate from Virtuals ACP v2 (W16). ERC-8004 validation records and A2A task states do not designate an ERC-8183 evaluator or move funds. Neither ACP is an evaluator escrow.

## Commands and evidence

All operations stayed on local or in-memory transports, used fixture identities and assets, and made no public-chain or payment-provider calls. Git HEAD and tracked-file cleanliness were checked for each upstream clone. Upstream sources stayed outside the project; no upstream source was copied into it.

For a fresh cloud checkout, `SETUP_W17_PROTOCOLS=true bash scripts/setup_cloud_environment.sh` opts into these W17 sources and tools after the base environment. The flag defaults to `false`, so base readiness does not depend on W17. The isolated A2A installation is synchronized from [a2a-dependency-freeze.txt](a2a-dependency-freeze.txt); the ERC-8004 compiler bytes are checked before local compilation. The opt-in setup does not run any protocol transaction or model call. Two successive full opt-in setup runs exited 0; the second kept all five source pins clean and reported `Nothing to compile`. [setup-validation.json](setup-validation.json) records their log hashes, script hash, compiler hash, and focused 4/4 ACP, 1/1 A2A, 61/61 ERC tests rerun afterward. The base setup also completed in both runs.

```bash
# From the project root; source clones are under /workspace/upstreams.
python -m unittest tests.test_acp_retail_local -v
UV_CACHE_DIR=/workspace/upstreams/.uv-cache uv venv /workspace/upstreams/w17-a2a-venv
UV_CACHE_DIR=/workspace/upstreams/.uv-cache uv pip install --python /workspace/upstreams/w17-a2a-venv/bin/python -e '/workspace/upstreams/w17-a2a-python[http-server]'
/workspace/upstreams/w17-a2a-venv/bin/python -m unittest tests.test_a2a_local -v

# From the pinned ERC-8004 checkout. RPC URLs are unreachable loopback
# config placeholders; the tests use Hardhat's in-memory chain.
NPM_CONFIG_CACHE=/workspace/upstreams/.npm-cache npm ci --legacy-peer-deps --no-audit --no-fund
# The first run installed solc@0.8.24 inside the checkout, copied soljson.js,
# then repeated npm ci to restore the upstream lockfile. A clean rerun can:
NPM_CONFIG_CACHE=/workspace/upstreams/.npm-cache npm install --prefix /workspace/upstreams/w17-solc24 --no-package-lock --no-audit --no-fund solc@0.8.24
cp /workspace/upstreams/w17-solc24/node_modules/solc/soljson.js /workspace/upstreams/w17-solc24/soljson.js
# The accepted compiler SHA-256 is fb59b825b7d57f9de89cd9de2415b12aab1fcc7eb2573fd2bf5c9b969eacf4d9.
python /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce/scripts/prepare_erc8004_offline.py
SEPOLIA_RPC_URL=http://127.0.0.1:9 MAINNET_RPC_URL=http://127.0.0.1:9 XDG_CONFIG_HOME=/workspace/upstreams/.config XDG_CACHE_HOME=/workspace/upstreams/.cache npx hardhat compile --config hardhat.local.config.ts
SEPOLIA_RPC_URL=http://127.0.0.1:9 MAINNET_RPC_URL=http://127.0.0.1:9 XDG_CONFIG_HOME=/workspace/upstreams/.config XDG_CACHE_HOME=/workspace/upstreams/.cache npm run test:core
SEPOLIA_RPC_URL=http://127.0.0.1:9 MAINNET_RPC_URL=http://127.0.0.1:9 XDG_CONFIG_HOME=/workspace/upstreams/.config XDG_CACHE_HOME=/workspace/upstreams/.cache node /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce/protocols/erc8004/local_registry.mjs /workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce/artifacts/gates/G6/W17/erc8004-local.json
```

The offline compiler preparation writes only an untracked local Hardhat config and cache files after checking the pinned upstream commit and compiler bytes. Hardhat's automatic `binaries.soliditylang.org` compiler-list request failed under the cloud network policy; the local index points to the genuine npm `solc@0.8.24` bytes. The upstream Hardhat lockfile remained pinned. [erc8004-compile.log](erc8004-compile.log) shows compilation of 8 Solidity files, [erc8004-core-test.log](erc8004-core-test.log) shows 61 pass/0 fail, and [erc8004-local.json](erc8004-local.json) records five successful chain-31337 transaction receipts with hashes and event topics. The local probe registers agent ID 0, proves owner-address self-feedback is rejected, stores a quality score from a separate test wallet, and revokes it. Both wallets are controlled by the test operator, so this is a scope check on the contract's address-based rule, not evidence of a real sybil attack or collusion.

[acp-retail-test.log](acp-retail-test.log) shows 4 pass/0 fail against the official released schema (SHA-256 `d0e4290617d66bf05d002b8ace388732be2b3eb9a92a1003db7a2daa1e0436f2`) and example bundle (SHA-256 `989e4bc7ccbdb789ea362450963821a368da63d20a2000186455fa7fbcaac8e7`). The local merchant rejects malformed checkout and missing idempotency key, preserves the same response on replay, rejects changed-body key reuse, creates a synthetic order once, and blocks terminal-state changes. Its capture counter is synthetic; no card token was sent to a PSP. The upstream repository is an Apache-2.0 specification bundle, not a merchant runtime SDK, so this is a schema and mock state result at `SCRIPTED_SIMULATION` tier.

[a2a-test.log](a2a-test.log) shows 1 pass/0 fail using the official Python SDK's HTTP/JSON REST client and server routes on `httpx.ASGITransport`. The application bearer guard rejects an unauthenticated call, while signed-in local calls serialize a user message, working task, cancellation, and completion. The in-memory handler supplies these task states; the SDK exercises the transport and message types, not agent execution. Authentication here is an application control, not an A2A native proof of human identity or payment provenance. Execution tier is `NATIVE_LOCAL_PROTOCOL` for communication only.

## UCP + AP2 SKIP boundary

The pinned UCP source provides schemas and specification text for `dev.ucp.common.payment.ap2_mandate`, but no runnable checkout/PSP SDK. Its AP2 extension requires capability intersection, a merchant detached JWS over the JCS-canonicalized checkout excluding `ap2`, and **two distinct** platform artifacts: `ap2.checkout_mandate` bound to the full signed checkout and a Payment Mandate in `payment.instruments[*].credential.token`. The W15 AP2 test proves a signed local **Payment Mandate** chain; it does not construct this UCP signed checkout or Checkout Mandate. A schema-shaped object alone would not prove the cryptographic binding. Therefore native UCP+AP2 completion, merchant signature verification, PSP settlement, refunds, and downgrade resistance are SKIP with zero tests/pass claims. No external credentials or real money are needed for a future local cryptographic fixture, but it must be implemented and checked separately.

## Independent checks, limits, and next work

The test logs, JSON registry receipts, coverage file, and source hashes are indexed by [manifest.json](manifest.json). Source commit checks, official JSON Schema validation, and on-chain registry reads are independent of the coverage labels. The ERC-8004 contract checkout declares `ISC` in `package.json` but has no tracked root LICENSE file; no contract source was copied into this repository. The ACP, UCP, A2A specification, and A2A Python SDK checkouts include Apache-2.0 licenses. Publication reuse of ERC-8004 code requires license confirmation.

Files added: `protocols/acp_retail/local_checkout.py`, `tests/test_acp_retail_local.py`, `tests/test_a2a_local.py`, `protocols/erc8004/local_registry.mjs`, `scripts/prepare_erc8004_offline.py`, and this W17 evidence directory. `scripts/setup_cloud_environment.sh` gained the optional W17 section. Existing package and `legacy/` files were not changed. Follow W18 only after G4 causal treatment and G5 defense prerequisites; use ERC-8004 identities as an optional relationship overlay, with payment evidence still supplied separately by ERC-8183 or another actual rail.
