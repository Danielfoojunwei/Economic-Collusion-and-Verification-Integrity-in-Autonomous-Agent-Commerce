# Turning the simulator into a research-grade real-protocol experiment

Current v0.1 already runs local flows; this is the remaining work rather than an assertion it is already complete.

## Phase 1 — ERC-8183 reference contract execution (highest priority)

Source: https://github.com/erc-8183/base-contracts . Use Foundry (`forge`, `anvil`) and a no-value local chain; neither executable is installed in the current benchmark execution environment. Build reference contracts, deploy a mock ERC-20, mint **only local test credits**, create job, set budget, fund, submit, complete/reject/expire. Capture transaction receipts, gas, event logs, revert reasons, role identities and end-state balances. Faults: unauthorised complete, expired claim, replayed finalization, evaluator wrongfully accepting invalid deliverable. Compare contract output with independent objective oracle; **a valid call is not an acceptance-correctness proof**.

Bridge `Session` to a `RealERC8183Adapter` with `createJob`, `setBudget`, `fund`, `submit`, `complete`, `reject`, `claimRefund`, and verify emitted events. Include optional hook paths for Virtuals ACP v2. Do not broadcast to Base mainnet.

## Phase 2 — x402 v2 scheme-valid test execution

Source: https://github.com/x402-foundation/x402 . Install official SDK version from a pinned commit. Replace `wiremock` HMAC with test wallet signatures and a genuine local/testnet facilitator using supported official payment scheme; validate correct 402+retry+receipt, signature, payee, amount, nonce, network and expiry. Distinguish authorization flow settled after service from variants that settle up-front. Use a dedicated fake resource server, with an independent result-quality oracle not assumed native to x402. Never pay live providers or expose actual signing keys in logs.

## Phase 3 — Stripe/Tempo MPP official SDK

Source: https://github.com/tempoxyz/mpp-specs . Use the official SDK on a local/official no-funds integration or provider test mode; implement `charge` first, then explicit `session` and `subscription` methods as **separate adapter variants**. Bind challenge id/realm/method/intent/request, request body digest, TTL, single-use payment credential, server receipt. Do not infer service-quality guarantees from valid charge credentials.

## Phase 4 — AP2/UCP delegated mandate chain

Sources: https://github.com/google-agentic-commerce/AP2 and https://github.com/universal-commerce-protocol/ucp . Use SD-JWT/ES256 and official schemas for user-signed open checkout and payment mandates, trusted-surface constraints, agent-signed closed mandates, merchant-signed checkout JWT, checkout/payment receipts and processor verification. Pin human-not-present and human-present flows separately. Validate checkout/payment hash binding, privacy-preserving selective disclosure, delegation scope, amounts/payee/expiry and single-use conditions. No direct user payment credentials or secrets in agent prompts.

## Phase 5 — Distinct ACP integrations

- **Virtuals ACP v2**: `@virtuals-protocol/acp-node-v2`, run against a developer/no-value chain, exercise `CreateJobParams`, hook callbacks, provider/evaluator roles, escrow and partial settlement. The v2 design follows ERC-8183; compare implementation deviations rather than count them as wholly unrelated payment primitives.
- **OpenAI/Stripe ACP**: stable `2026-04-17` OpenAPI/JSON schema and checkout endpoint. Integrate merchants' sandbox checkout flows and payment handler abstractions; work-verification claims must be explicit application extensions, not attributed to ACP retail standard.

## Phase 6 — A2A transport and ERC-8004 trust overlay

Use official A2A v1.0 SDK and AgentCards to carry task specifications, provider submissions, verifier evidence and state changes. Use ERC-8004 identity/validation/feedback entries in a **local EVM** to test identity and feedback provenance. Identity alone does not guarantee correlated-error independence or verifier honest effort.

## Phase 7 — genuine model experiments and defensible novelty

Run at least 3 independently developed LLM families with frozen checkpoints and full token/tool logs. Randomize: feasibility of verification, verified conditional side-payments, past financial dependence, persuasive false evidence, auditor assignment. Control same tasks and model context, repeat with adequate power; estimate clustered confidence intervals and cost/security Pareto curves. Model provider and verifier autonomy separately. Compare against independent agents rather than classifying mutual incorrect approvals as collusion automatically.

## Production controls

No mainnet value, live users, private user data, healthcare decisions or monetary exposure during research. Keys restricted to temporary local development accounts; no real wallet exports in test artifacts. For code tasks, isolate execution in an unprivileged sandbox with no network, CPU/memory/time/file quotas and deterministic reference tests. Review consent/terms of provider SDKs. Escalate security defects via responsible disclosure, not merely publication of ambiguous mocked state-machine outcomes.
