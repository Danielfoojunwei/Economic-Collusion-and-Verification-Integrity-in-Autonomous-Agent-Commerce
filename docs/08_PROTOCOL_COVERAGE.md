# 08 — Protocol coverage, classification and native conformance gates

**Do not treat every item as a peer payment rail.** This table is a protocol coverage plan, not a current conformance report. The official current upstream implementation takes priority over archived simulator assumptions; pin each tag/commit and run SDK tests locally.

| Protocol / layer | Source | Genuine role | Local native experiment | Priority |
|---|---|---|---|---|
| **ERC-8183** | https://github.com/erc-8183/base-contracts | Client-funded job escrow with designated evaluator | Local Anvil, contracts, fund, submit, evaluate, expired/refund, event + balance proofs, partial claims where supported | P0 |
| **x402 v2 default authorization** | https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md | HTTP resource payment; verify authorization; resource execution; settle | Official SDK, loopback facilitator, scheme-valid signatures/expiry/amount/recipient; response and tx evidence | P0 |
| **x402 v2 other payment flows** | same | Upfront and declared scheme-specific variants | Each path under its exact spec, different ordering and refund contract | P1 |
| **MPP charge** | https://github.com/tempoxyz/mpp | HTTP 402 machine charge | Official SDK, valid challenge/credential + charge, idempotency, response semantics | P1 |
| **MPP session** | same | Session-based/metered payment | Native test ledger/session validity, expiry, bounded spending | P1 |
| **Google AP2 v0.2** | https://github.com/google-agentic-commerce/AP2 | Delegated payment authorization and mandates | Official SDK, signed mandate chain, scope, revocation/expiry as specified, safe demo/test credentials | P1 |
| **Virtuals ACP v2** | https://github.com/Virtual-Protocol/acp-node-v2 | Agent-commerce jobs, event-driven `AcpAgent`/`JobSession` | Test provider/evaluator role events and token flows; local/test-only after verifying supported transport and credentials | P1 |
| **OpenAI/Stripe ACP** | https://github.com/agentic-commerce-protocol/agentic-commerce-protocol | Checkout, not evaluator escrow | Pinned 2026-04-17 checkout schemas, mock merchant implementation and official conformance, no real cards | P2 |
| **UCP + AP2** | https://github.com/universal-commerce-protocol/ucp | Commerce coordination + delegated authorization | Valid compositional order and separate protocol evidence | P2 |
| **A2A v1.0** | https://github.com/a2aproject/A2A | Communication/agent discovery, **not** money | SDK task server/client, authenticated role/provenance, delegate/complete/cancel + separate payment adapter | P2 |
| **ERC-8004** | https://github.com/erc-8004/erc-8004-contracts | Identity, reputation, validation registry, **not** money | Local registry identity/feedback; controlled sybil/reputation relationships with escrow integration | P2 |
| **A402/TessPay/other research implementations** | Source-specific paper/repos | Research verification/payment architecture | Only if code exists, licensed and runnable, with declared comparison semantics | Optional |

## Native ERC-8183 minimal acceptance plan

Read actual pinned contract ABI and docs before writing calls. The repository now describes a job state machine, optional hooks, EIP-712 authorization, and additional partial claim/settlement features; do not assume it only contains an earlier one-shot lifecycle. At minimum:

- Local chain (Anvil), deterministic funded test wallets, mock test ERC-20 (no real-world assets).
- Honest path: client creates/funds job, worker submits, designated evaluator completes; assert correct terminal state and exact delta of provider/client/fees.
- Reject/expiry: evaluator rejects and eligible refund correctly finalizes; expiry with pending claims may impose additional liveness conditions per pinned revision.
- Wrong-role caller cannot complete, invalid transitions revert, repeated terminal settlement cannot double pay.
- Evidence-binding guard is explicitly marked a custom application hook and evaluated separately.
- Emit chain ID, contract address, tx hashes, log indexes, ABI revision, block heights, balances before/after, known custody and signer principals.

## Native x402 v2 minimal acceptance plan

Use official SDK and a local facilitator, not legacy mock HMAC. Pin exact spec/tag and scheme implementation. For each relevant flow:

- Payment-required challenge returns correct requirements, asset/network/recipient/amount and expires.
- Client issues cryptographically valid scheme-specific authorization; server/facilitator validates the requested resource and payer authority.
- Verify changes not confused with final settlement; record timestamps for `VERIFY`, `RESOURCE_EXECUTE`, `SETTLE`, `RESPONSE`.
- Wrong amount/payee, reused nonce, stale authorization or mismatched resource fails where guaranteed by the chosen scheme.
- Server failure between verify/execute/settle assessed against documented flow and actual proof of finality.
- Application semantic verification only exists if an extra evaluator service is deliberately composed.

## Why apples-to-apples comparison is wrong

ERC-8183 defines a trusted evaluator role for a specific job; x402 often pays for API access rather than satisfactory semantics; AP2 protects delegated spending authority; ACP/OpenAI manages retail checkout; A2A carries messages. Measure **within-family conformance** separately from **application outcome correctness**. For cross-protocol experiments fix the task/specification and auditor decision, but label additional application controls and genuinely comparable flows.

## Version/release controls

- ORBIT: maintained GitHub release v1.0.2 observed in official README; **`pip install orbit` is unrelated**. Codex must verify release hash/API. Inspect baseline recorded by ORBIT was `0.3.263`, accepted `>=0.3.263,<0.4` at observed snapshot.
- Virtuals ACP v1 `@virtuals-protocol/acp-node` is explicitly **deprecated**; maintained SDK is `@virtuals-protocol/acp-node-v2`. Do not follow outdated Virtuals tutorials without checking version.
- OpenAI/Stripe ACP and Virtuals ACP both abbreviate ACP; **never conflate**.
- Exact specification version and SDK git commit, contract ABI and dependencies are required in each run manifest.

## Coverage report schema

For every protocol record `name`, `component_type`, `official_url`, `spec_version`, `commit_sha`, `native_sdk_installed`, `credential_type`, `test_environment`, `native_transactions`, `tests_total`, `pass_count`, `fail_count`, `skip_count`, `skip_reason`, `supports_evaluator`, `supports_refund`, `application_guard_needed`, `evidence_file`. Do not transform unrun into failure or pass.
