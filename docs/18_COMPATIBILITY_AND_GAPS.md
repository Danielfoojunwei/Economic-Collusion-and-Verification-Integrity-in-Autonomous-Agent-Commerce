# 18 — Integration incompatibilities, gaps and no-guess policy

## Known incompatibilities to resolve

1. ORBIT uses **Inspect** task/scorer and scheduler interfaces; Colosseum's experiments run on **Terrarium**. Do not attempt two simultaneous schedulers; migrate *metrics/controls* into ORBIT's task contract.
2. Current ORBIT release requires GitHub wheel/source installation; the unrelated PyPI `orbit` package must not be installed. Verify actual release/Inspect constraints before coding.
3. Virtuals `acp-node` v1 is deprecated. Use `@virtuals-protocol/acp-node-v2`, whose event-driven API is not a drop-in v1 replacement.
4. ERC-8183 published draft and its base-contracts HEAD may differ on claim/partial settlement and expiry behavior. Only cite the exact pinned contract revision in native findings.
5. x402 v2 **verify** and **settle** are different events; not every flow has the same execution ordering.
6. A2A and ERC-8004 supply communication/identity, not settlement. Combining them with escrow is a composed application architecture, not another standard rail.
7. AP2 protects delegated payment mandate scopes. It does not automatically perform unbiased third-party task verification.
8. OpenAI/Stripe ACP and Virtuals ACP have different role and payment models despite acronym collision.
9. Legacy `objective_recheck` receives a perfect oracle, so it cannot be compared to a real auditor without an explicit upper-bound label.
10. Legacy simple event digest is local consistency, not cryptographic nonrepudiation.

## Availability/compatibility gates

- If an upstream API has changed, record the exact former/new signatures, tests, and migration, then update thin adapter only.
- If SDK needs external production or partner credentials, mark `SKIP_CREDENTIALS` and use a local-native subset or no-funds demo. Do not mock and mislabel as official.
- If tasks or datasets have restricted licences, fetch in users' environment with receipt and citation; do not redistribute as handover assets.
- If ORBIT cannot be installed due to release incompatibility, implement minimal Inspect compatible Task and keep ORBIT gate marked BLOCKED.
- If real local model is unavailable, produce mocked control tests but mark `REAL_LLM_LOCAL=SKIP_NO_MODEL`; do not finish behavioural experiments with scripted rates.

## No scientific shortcuts

Never write a paper result before verifying the run evidence. Do not choose final sample size from authored simulator coefficients; do not equate task correctness with payment authorization; do not conflate economic errors with protocol-level exploits; do not conflate correlation with collusion.
