# 03 — Closest prior art, methods to reuse, and novelty exclusion test

## Critical reading priority

| Study / source | Already contributes | Reuse in this paper | **Do not claim as first** |
|---|---|---|---|
| [ORBIT](https://arxiv.org/abs/2609.33102), [code](https://github.com/wlanderson0/orbit) | Inspect-based multi-agent scheduler; modular attack/defense/topology/evaluation | The runtime itself; cross-agent tools, logs, presets, same scenario ablations | A configurable multi-agent security benchmark |
| [Colosseum](https://arxiv.org/abs/2602.15198), [code](https://github.com/umass-ai-safety/colosseum) | DCOP coalition advantage/regret; action vs chat distinction; communication probes | Measure coalition benefit under a clearly defined financial objective and independent no-interaction controls | Agent collusion metrics, hidden-channel discovery |
| [Emergent Collusion](https://arxiv.org/abs/2609.24967) | Long-horizon pair verification deviations, peer/history/reward ablations | Context and proper experimental comparison | Repeated LLM agents violating verification rules |
| [CABAL](https://arxiv.org/abs/2609.05227) | Counterfactual reviewer assignment and strategic bidding ring | Matched-world evaluator-selection/peer relationship interventions | Reviewer-selection capture |
| [AgentDojo](https://arxiv.org/abs/2406.13352), [code](https://github.com/ethz-spylab/agentdojo) | Realistic stateful agent tasks; attacker control vs user utility | Existing task/scorer ecosystems and admissible untrusted surfaces | Dynamic agent security testbeds |
| [AgenticPay](https://arxiv.org/abs/2602.06008), [code](https://github.com/SAIL-Research-Lab/AgenticPay) | Language bargaining with private valuation and multiple buyers/sellers | A minority negotiation/relationship module if grounded by task economics | LLM buyer–seller market negotiation |
| [Agentic Commerce Bench](https://arxiv.org/abs/2609.35886) | Economic fraud, identity-right counterparty abuses, event layers, clean-train calibration | Separate transaction identity from economic correctness; fraud score | Detection of valid-looking economic fraud |
| [A Formal Analysis of Agent Payment Protocols](https://arxiv.org/abs/2609.00060) | Formal lifecycle consistency for x402, MPP, ACP, AP2 | Native protocol semantics/counterexample categories | Generic payment protocol state validity |
| [Beyond the Mandate](https://arxiv.org/abs/2608.23858) | AP2 trust-surface analysis and valid-signature/intent gap | AP2-specific threat boundaries and version evidence | Authorisation signature != user intent |
| [SoK: Decentralized Agent Economic Infrastructure](https://arxiv.org/abs/2610.01756) | Guarantee closure, receipt soundness, evaluator corruption-cost and shared-error analysis | Distinguish direct vote buying from induced correlated mistakes; mixed attacks | Paid auditors can be bribed; receipt is not semantic truth |
| [When HTTP 402 Meets the Blockchain](https://arxiv.org/abs/2607.19545) | Native facilitator /verify and /settle security invariants and attacks | x402 verify-vs-settle event and fault tests in local sandbox | Facilitator replay/settlement flaws |
| [Compromise Is Not Consequence](https://arxiv.org/abs/2610.05840) | Paired post-decision replay and scoped-enforcement separation | Frozen agent decisions across guard choices and matching pre-state | Separation of policy compromise from executed harm |
| [SoK: When Safe Agents Fail Together](https://arxiv.org/abs/2609.00595) | Execution-centered multi-agent trust-boundary taxonomy; includes NTU author | Define interaction-dependent security effects and interfaces | General multi-agent security composition taxonomy |

## Novelty test for each planned claim

A proposed claim is **not** sufficiently novel if it says only:

- LLM agents can collude;
- a verifier can be bribed;
- digital signatures and payments do not prove service quality;
- auditor bonds or verification-before-payment deter bad decisions;
- reviewer selection can be captured;
- ORBIT lacked a named payment adapter.

The stronger candidate is: **quantified, causal effect of real LLM verifier effort under credible recurring economic relationships × feasible verification scarcity × provider-controlled evidence, where actual native payment outcomes are separately verified and defenses are compared at matched cost**.

## Prevent novelty overclaiming

Before experimental paper draft: run search across arXiv, OpenReview, IEEE/ACM proceedings and the citations of the three closest SoKs, then fill a claim matrix with explicit “same experiment?”, “same estimand?”, “same incentive mechanism?”, “actual native payment?” judgments. No sentence like “first” without documented exclusion logic and a cutoff date. Any discovered collision must narrow scope or change contribution.

## Methods and ethics transfer

- Borrow ORBIT's modular runtime, don't fork and rebrand as a benchmark.
- Preserve Colosseum distinction between *communication-based* and *action-based* evidence; adapt its coalition benefit only where the financial payoff model is explicit.
- Borrow CABAL's **matched environments and assignment** interventions, not its peer-review data domain.
- Borrow AgentDojo's independent environment-based utility checks, not a model judge as ground truth.
- Borrow Agentic Commerce Bench's false-positive calibration and observation levels.
- Borrow paired replay's fixed action and pre-state while being explicit that this estimates **enforcement** and not how defense changes agent behavior.

## Paper evidence provenance

The attached `inputs/From chat collusion to bribes.pdf` (12 pages) is the user's **preliminary experiment narrative**, not a report of native ERC-8183/x402 results. Read pages 4–5 for impossible-verification and independence confounds; pages 9–12 for random synthetic offers, planted errors, and partner-message trust. Its numeric claims should be attributed to the preliminary PDF and, if used in a new paper, independently reproduce from underlying raw logs.
