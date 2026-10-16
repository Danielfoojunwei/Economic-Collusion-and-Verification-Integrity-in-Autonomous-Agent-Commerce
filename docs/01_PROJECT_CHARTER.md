# 01 — Research charter and scope

## Scientific objective

Empirically characterize when an **LLM-based verifier**, whose verdict controls whether another agent gets paid, changes its verification effort or verdict due to (i) credible economic inducements, (ii) repeated financial dependence, (iii) feasible but costly checking, and (iv) persuasive, possibly misleading provider evidence. Evaluate realized financial consequences under **native protocol** semantics and compare practical safeguards on a **security–cost–fairness frontier**.

## Working paper title

**When Agents Pay Their Auditors: Economic Collusion and Verification Integrity in Autonomous Agent Commerce**.

Do not assert collusion as a result before evidence: it is a hypothesis and part of the attack taxonomy.

## Research gap and caveat

- Emergent Collusion and Colosseum examine agent coordination and its action-based measurement.
- ORBIT supplies a reusable multi-agent security runtime, including scenario/attack/defense controls; recreating this runtime has little novelty.
- Work on AP2 and payment protocol security already examines authorization, context binding, protocol integrity, and receipt–settlement consistency.
- *SoK: Decentralized Agent Economic Infrastructure* (arXiv:2610.01756) already models evaluator bribery, shared errors, and economic guarantee closure. This makes a pure 'pay your auditor' or 'verification-before-payment' claim insufficient.
- Candidate contribution: **measured causal interactions** among actual model-selected verification effort, authentic provider–auditor financial relationships, persuasive evidence, and protocol-valid payment consequences, plus a validated cost/quality countermeasure.
- This is a candidate, *not yet verified globally novel*; literature review/negative novelty check is a research gate.

## Explicit non-goals

1. New general-purpose benchmark or agent framework.
2. A new FHE, consensus, wallet, blockchain, or payment protocol.
3. Automated exploitation of external merchants or networks.
4. Long-running or unlimited model-calling jobs without an explicit budget.
5. Conclusions about intrinsically financial motives of LLMs.
6. Universal security rankings between protocols with incomparable guarantees.

## Artifacts required for the paper

- A pinned ORBIT extension with existing task-environment reuse.
- A methodologically faithful reference to Colosseum's action-based collusion metrics and counterfactual control, with correct adaptation when the objective differs.
- At least two different **native** payment mechanics: ERC-8183 evaluator-controlled escrow; x402 v2 HTTP payments.
- A pre-registered live-agent randomized study and matched-world protocol replay.
- Independent task quality oracle with no model leakage.
- Complete event, payment and evidence trace; per-run cost and model configuration.
- Empirical null-ready analysis; ablations, honest utility, security–cost frontier.
- A paper whose claims are restricted to actually exercised execution tiers.

## First falsifiable statement

> Among nonconforming tasks for which checking is feasible, randomized exposure to a credible provider–auditor financial relationship changes the probability of auditor false approval compared with a matched independent control, and this effect may be moderated by checking scarcity and evidence presentation.

This might turn out to be false: preserve the result. Characterization and credible uncertainty are valuable even if the effect is zero.
