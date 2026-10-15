# Integration and realism gates (work to reach actual protocol-native experiments)

**Current state:** 12 protocol-shaped state machines, **zero official signed payment transactions or contracts**; two loopback HTTP 402 shape checks with *mock* HMAC, **not** x402/MPP scheme conformance; no remote LLM and no actual EVM connected.

| Priority | Integration | Minimal executable acceptance test | Realism status |
|---|---|---|---|
| P0 | Actual open-weight worker, verifier and payment agents | each has independent model state, prompts and tools, provider generates novel artifact; auditor spends tool budget; payer signs only scoped authorization; hidden test never enters prompt | **NOT BUILT**; v0.2 can call an optional loopback auditor only |
| P0 | Real ERC-8183 smart-contract local chain | vendor Solidity deployed to local anvil; fund / submit / evaluator complete or reject / expire / refund; on-chain event proofs and balances; no real tokens | **NOT BUILT**; `forge`/`anvil` absent in working container |
| P0 | Official x402 v2 exact scheme | official TS/Python SDK and facilitator in isolated environment; signed EIP-3009 valid/expired/nonce/wrong-amount credentials; default `verify→resource→settle→respond` flow | **NOT BUILT**; mock server and local state machine only |
| P0 | Official MPP charge/session | protocol-generated challenge and credential, actual test facilitator; meter, retry, expiry and settlement events | **NOT BUILT**; synthetic `mock/charge` only |
| P1 | Google AP2 v0.2 | signature validation, open/closed checkout/payment mandates, issuer/session binding, credential storage separated from model | **NOT BUILT** |
| P1 | Virtuals ACP/ ERC-8183 | protocol-version pinned TypeScript SDK + evaluator hooks over local EVM | **NOT BUILT** |
| P1 | OpenAI/Stripe ACP + UCP | merchant checkout schema, payment token issuer, legitimate order-state transitions and cancellations | **NOT BUILT** |
| P1 | A2A v1 communication | independent agent servers and A2A tasks; authenticated AgentCards, RPC/HTTP, cancellation and interrupted messages | **NOT BUILT** |
| P1 | ERC-8004 on-chain registry | identity and reputation written/read from local EVM; fake feedback / ID reset / shared ownership controls | **NOT BUILT** |
| P2 | Real-world SWE-bench / tau³-bench / AgentDojo tasks | licensed, version pinned, independent scorers, container sandbox and dataset leakage controls | **NOT BUILT**; only method transfer and synthetic task proxies |
| P2 | ORBIT/Inspect integration | compatible sandbox scheduler, multiple models, independent tools, role-scoped messages, Inspect scorers | **NOT BUILT** |
| P2 | Research A402/TessPay/ASP | independently installed research author prototype with pinned commit and faithful threat model | **NOT BUILT**; do not conflate with standards |

Do not charge real cards or send tokens on mainnet for this study. Use a local EVM/testnet or fake credits, and ensure irreversible actions and real credentials are inaccessible to autonomous models.

## Required experiment types once integrations exist

**E1: Exact protocol conformance** — native transactions are checked for declared native requirements only. Do not label missing service-quality protection in a payment-only protocol a vulnerability.

**E2: Behavioural evaluator independence** — finance / prompt / verifier evidence randomization with genuine models and blinded task truth. Use a null-capable, preregistered factorial and matched assignments.

**E3: Structural faults** — manipulate time between authorize, verify, execute, settle and respond; retry-after-settle, reused authorization, settled charge without delivered service, duplicate task ID under distinct transaction IDs. Record whether each failure is permitted by the native protocol or application logic.

**E4: Security–utility–cost** — measured block rates, correct-payment rates, review latency, API and cryptographic costs, legitimate false denial, and welfare across small micropayment and larger paid-service jobs.

**E5: Reviewer market and coalition** — independently owned vs same beneficial owner; random vs controlled assignment; 2/3/5 reviewers; correlated vs heterogeneous base models; actual reciprocal payments; stochastic prompt vs action comparison and counterfactual coalition advantage.
