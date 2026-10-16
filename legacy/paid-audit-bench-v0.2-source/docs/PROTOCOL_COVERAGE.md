> **v0.2 update, 2026-10-15:** the simulator also provides `x402_v2_upfront` and `x402_v2_escrow`, bringing it to **12 local adapters**. These represent the x402 v2 published `authorization`, `upfront` and `escrow` payment-flow *orderings* only; each remains a MOCK, not a supported scheme implementation. The default authorization flow has event order `verify → resource handler → settle → final response`. The base-contracts ERC-8183 repository may differ from the eips.ethereum.org draft; pin an exact revision before native conformance work. See `docs/RESEARCH_TO_RUNTIME_V02.md` and `docs/REALISM_INTEGRATION_GATES.md`.

# Source-grounded protocol coverage, 2026-10-15

**CAVEAT:** Each `PASS` of a harness unit test means only that its *own simplified state machine* did what the test expected. It **does not** mean the official payment protocol is compliant, insecure, secure, or fully integrated. Never compare security outcomes without noting which guarantees are native and which belong to the application.

## The complete relevant taxonomy

| Layer | Entity | Official reference | Snapshot / distinction | Executed coverage |
|---|---|---|---|---|
| Agent messaging | Agent2Agent | https://github.com/a2aproject/A2A/blob/main/docs/specification.md | v1.0, transports agent tasks; not a payments protocol | A2A-shaped event transport simulation only |
| Payments by HTTP | x402 Foundation | https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md | v2, `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`; models *authorization* flow | Offline lifecycle + real loopback HTTP 402 with fake signatures |
| Payments by HTTP | Stripe/Tempo MPP | https://github.com/tempoxyz/mpp-specs | `WWW-Authenticate: Payment`, `Authorization: Payment`, `Payment-Receipt`; this harness models **charge** not session subscriptions | Offline lifecycle + loopback HTTP 402 mock credential |
| Mandated agent checkout | Google AP2 | https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/specification.md | v0.2, open and closed checkout/payment mandates and receipts | Simplified simulated mandate sequencing only; no actual SD-JWT |
| Retail checkout composition | Google UCP | https://github.com/universal-commerce-protocol/ucp | stable version v2026-08-25 available; checkout composes with AP2 | Simplified UCP checkout events + AP2 simulation |
| Commerce checkout | OpenAI/Stripe ACP | https://github.com/agentic-commerce-protocol/agentic-commerce-protocol | published stable snapshot 2026-04-17; unrelated to Virtuals' ACP | Simulated shopper/merchant checkout only |
| Paid agent work | ERC-8183 | https://eips.ethereum.org/EIPS/eip-8183 | **draft** escrow: Open→Funded→Submitted→Completed/Rejected/Expired; *evaluator only* completes | Simulated job/escrow/role/expiry/refund transitions |
| Paid agent work implementation | Virtuals ACP v2 | https://whitepaper.virtuals.io/acp/acp-changelogs | v2 April 2026, implements ERC-8183 + optional hooks; distinct ACP | Simplified hook invocation + ERC-8183 simulation |
| Agent registry | ERC-8004 | https://eips.ethereum.org/EIPS/eip-8004 | **draft** identity, reputation, validation; explicitly excludes payments | Mock request/feedback events composed with ERC-8183 |

## Wire-mock scope

For `x402`: genuine local HTTP 402+retry with `PAYMENT-REQUIRED` and `PAYMENT-SIGNATURE` headers; challenge+payload shaped as v2, but **not exact v2 EIP-712 signatures or a facilitator**, and no token contract or blockchain.

For `mpp`: genuine local HTTP 402+retry with `WWW-Authenticate: Payment` and `Authorization: Payment`; an ephemeral fake wallet uses local HMAC instead of a valid official payment method. The challenge uses a hypothetical `mock/charge` method. It is a wire-shape smoke test, **not MPP conformance**.

`wire-smoke` checks: unpaid 402, mock paid 200, replay 409, tampered amount 403.

## Unimplemented, not silently claimed as tested

- Official real x402 clients and facilitators, and `exact/upto/batch-settlement` scheme variants.
- Real MPP `charge/session/subscription` methods, signed payment credentials and Stripe/Tempo settlement.
- AP2 cryptographic open/closed mandate verification, certificate chains, actual credential provider, human-present mode, genuine AP2 dispute evidence.
- Solidity/ERC-8183 smart contracts, fully functional Virtuals ACP v2 SDK and `beforeAction/afterAction` validation on an EVM; current hooks only log.
- OpenAI/Stripe ACP OpenAPI checkout state machinery and network payment token issuer; checkout is a research stand-in.
- UCP SDK conformance, product schemas and profiles.
- ERC-8004 registered agent identities and actual validation/reputation registry writes; Sybil resistance is not achieved by this simulation.
- Visa TAP, Mastercard Agent Pay, Lightning L402, research A402, ASP, RAILS, TessPay, and other proprietary payment networks not amenable to a common public sandbox today.
- Genuine secure cryptographic transaction proofs, insurance claims and economic enforcement. Tested numerical balances are not digital money.

## Vendor reference implementation upgrade paths

- ERC-8183 base contract / Foundry tests: https://github.com/erc-8183/base-contracts
- UCP conformance suite: https://github.com/universal-commerce-protocol/conformance
- Official x402 reference: https://github.com/x402-foundation/x402
- MPP IETF evolving draft: https://datatracker.ietf.org/doc/draft-httpauth-payment/01/
- Virtuals v2 SDK: https://whitepaper.virtuals.io/acp/acp-changelogs
- OpenAI/Stripe ACP stable schemas: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol/tree/main/spec/2026-04-17

## What local tests mean

The official ERC-8183 `complete` call transfers escrow to the provider when the designated evaluator marks it Completed. Its optional `reason` can hold an attestation commitment; it does **not** cryptographically certify a semantic quality predicate. The work-level oracle is added by our application, and the benchmark knows the ground truth separately.

The x402 v2 specification supports schemes and different payment-flow choices; our adapter intentionally models a common authorization/response/settlement pattern. We **must not** generalize its results to all x402 schemes or claim all x402 payments happen before service. Likewise, MPP's charge route does not represent all MPP sessions and payment methods.
