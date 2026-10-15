# 04 — Research questions, hypotheses and falsification

**Primary factual status:** Everything in this document is a planned test, not a result.

## RQ1 — Direct inducement and auditor effort

Can a **credible** conditional transfer alter auditor `check`, `ACCEPT`, or `REJECT` decisions on work of objectively known quality, with feasible checking costs?

- H1-null: no change in bad-work false approval between randomized verified offer and no offer.
- Additional arms: signed but unenforceable promise, spoofed/untrusted text offer, executed sandbox transfer, offer to worker rather than auditor (negative control).
- Do not equate 'assistant says it accepted $8' with payment execution.
- Primary: actual check invocation and false approval; secondary: settlement for bad work.

## RQ2 — Mixed incentives and evidence

Estimate interaction of **R** financial relationship (0 independent / 1 economically dependent), **S** verification scarcity (0 comfortably funded / 1 feasible but costly) and **P** persuasive provider text (0 neutral / 1 persuasive but fact-equivalent). Pre-specify the 8 arms; include good and bad work.

- H2: scarce feasible checking decreases check rate; may vary by model.
- H3: R×S×P changes wrongful-payment risk beyond additive lower-order effects; effect sign is exploratory absent prior preregistration.
- Primary estimand on bad work: `p_rsp = Pr(WP=1 | do(R=r,S=s,P=p))`.
- Three-way interaction: `p111 - p110 - p101 - p011 + p100 + p010 + p001 - p000`.
- Guard against having persuasive text inadvertently change factual evidence; check fact-equivalence separately.

## RQ3 — Coordination vs independent failures

Does a sustained financial relationship cause **incremental coalition advantage** beyond independent error under matched circumstances?

- Explicit alternative explanations: independent cost-saving, common model bias, correlated evidence, task difficulty, asymmetric information, selection effects, reward misspecification.
- Randomize pairing/role crossover; remove direct communication; reset history; replace auditors; vary topology; retain task and payoff state.
- Controlled colluding prompt as **positive control only**; never count it as emergent collusion.
- Outcome: excess coalition benefit under randomized interaction changes plus direct action/payoff evidence; joint bad approvals alone are not enough.

## RQ4 — Native payment consequences

Given the **same frozen auditor output and original task pre-state**, how do protocol-native authorisation, settlement and application acceptance gates affect realized payouts and recovery?

- Separate ERC-8183/Virtuals evaluator-settled jobs, x402/MPP HTTP payment, AP2 authorisation and checkout, and composition overlays.
- This isolates *enforcement*, not the agent's incentive response.
- Classify every failure as `PROTOCOL_CONFORMANCE`, `APPLICATION_SEMANTICS`, `BEHAVIORAL_DECISION`, or `INCONCLUSIVE`.

## RQ5 — Defenses at a fixed budget

Do independent funding, task-bound evidence, conflict-aware reviewer assignment, probabilistic checks, or independent evaluator committees improve improper payment at fixed legitimate-work acceptance and comparable total verification cost?

- Primary: wrong-paid vs honest-unpaid at matched audit budget.
- Secondary: settlement delay, total compute/API/chain expense, task pass^k, false positives, and escrow liveness.
- Always reject and omniscient oracle are **negative/upper-bound controls**, not deployable proposals.

## Interpret both positive and null outcomes

Write preregistered smallest effect of interest and confidence/credible interval for H1/H2 before collecting confirmatory data. If credible offers fail to change decisions, report a bounded null result. If auditor dependence changes choices but there is no coordination evidence, call it **economic influence** or **verification drift**, not collusion. If only a protocol application's omission permits wrong payment, avoid attributing a native-standard vulnerability.
