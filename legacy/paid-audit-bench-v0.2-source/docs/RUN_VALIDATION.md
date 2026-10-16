# What was actually executed in PaidAuditBench v0.1

Date: 2026-10-15. No real-money payment, no SDK-level conformance, no real model inference.

- **27 automated Python unit/integration tests passed** at prototype creation. These cover independently checkable fixtures, safe arithmetic DSL, hidden tests not revealed to model interface, sandbox ledger conservation, role restrictions, rejection/refund, replay, deadline, invalid payee/amount, receipt substitution and guard, market graph, and live loopback header patterns.
- **11,520 local trial events/episodes** in `runs/pilot/trials.jsonl`, with manifest, paired descriptive contrasts, audit snapshots and **11,520/11,520** validated SHA-256 trace digests.
- **720 local repeated-market episodes** in `runs/market/trials.jsonl` with reciprocal/ring/rotating reviewer assignments; **720/720** trace digests validated.
- **4 local HTTP 402 challenge/response wire-shape smoke cases**: x402 normal 402→200 and mock replay blocked 409; x402 tampered amount blocked 403; MPP normal 402→200, replay 409; MPP tampered amount blocked 403.

## Example diagnostic only: single condition under invented policy parameters

These counts are **constructed output of the scripted `economic` policy**, NOT measured probabilities of real LLM behaviour and NOT protocol-level exploit discovery.

| Modelled workflow | Baseline wrong payments (out of 12 invalid work deliveries) | Mixed financial+verification+persuasion treatment | Why |
|---|---:|---:|---|
| ERC-8183 evaluator escrow | 0 | 7 | Scripted auditor is more likely to approve unchecked work with synthetic pressures; designated evaluator then calls complete. |
| Virtuals ACP v2 escrow | 0 | 7 | Uses same simplified escrow semantics in our code. This is **not independent external validation**. |
| x402 v2 authorization on delivered response | 12 | 12 | Simulator payment is tied to resource response, not third-party quality. This is not a specification violation. |
| MPP charge before resource delivery | 12 | 12 | Simulator models payment charge before quality audit. The problem is application-level, not native payment-integrity failure. |

All six work fixtures have independent exact oracles; `receipt_swap` submits valid work for auditor review then substitutes invalid delivered content. The idealised `objective_recheck` prevents this artificial substitution on escrow-style flows in the local simulator; it **does not** prove independent oracle deployment is cheap or possible for subjective services.

## What remains untested (scientific red lines)

- Real multi-agent LLM susceptibility to a paid offer or to a repeated economic relationship.
- Real vendor SDK/refcontract effects and cryptographic transaction verification.
- Proof that a pair of agents coordinated as opposed to making independent errors.
- Whether an actual auditing mechanism lowers misconduct at equal total cost, while ensuring honest-worker payment.
- Valid estimates of real-world financial loss, protocol exploitability, or breach probability.

The present tests validate the **harness mechanics** and expose which experiments to run. They cannot be cited as a paper's empirical security findings about third-party products.
