# 17 — Supervisor demo and research narrative

## One-minute summary

“We began by reproducing claims of emergent collusion among mutually auditing LLM agents. Our preliminary analysis suggested many unsupported joint approvals were compatible with independent decisions, and artificially costly or impossible verification could produce apparent misconduct. The next question is whether commercially interacting agents remain independent verifiers when they are paid to audit other agents' work. Rather than build another general-purpose benchmark, we reuse ORBIT, Colosseum methods and native agent-payment SDKs to study real model choices and actual payment outcomes. The scientific goal is to separate ordinary verification mistakes, financial influence, actual coordination, and protocol/application enforcement failures—and to measure the cost of preventing them.”

## Five-slide flow

1. **Motivation and example:** A coding agent hires worker; auditor approves; payer pays; bug remains. Payment signature valid but work incorrect.
2. **Prior-art map:** Colosseum/ORBIT already cover agent collusion/runtime. Native protocols cover transfers. We measure the missing interaction, with Sun et al. as critical nearest comparator.
3. **Research design:** randomize financial relationship × budget scarcity × persuasive evidence; separate model behaviour from frozen-decision settlement.
4. **Systems design:** thin ORBIT extension + local ERC-8183 evaluator escrow + x402 native HTTP payment; independent oracle and immutable event/financial records.
5. **Research gates:** old simulator validates scaffolding, not emergent collusion; show forthcoming live-agent and native transactions with preregistration and cost-vs-security assessment.

## Key anticipated question answers

**“Why no new benchmark?”** Because ORBIT already provides the MAS runtime and Colosseum action-based metrics. We only add components essential to answer the new economic-verification question.

**“Where is novelty?”** Candidate causal evidence about live verifier effort under authentic financial dependence × scarcity × persuasion and downstream native payment consequences; not the mere possibility of bribery, which prior work already studies.

**“What proves collusion?”** Coordination-attributable action/financial advantage under randomized interaction interventions; not two unsupported approvals or persuasive text alone.

**“Why do we need x402 if ERC-8183 includes an evaluator?”** Contrasting payment timing and intended guarantees; x402 tests whether application assurance can protect an HTTP-native payment flow and exactly where it must be placed.

**“What results are real today?”** The prior PDF's preliminary simulations and 84,480 authored offline simulator traces with tested instrumentation. No completed native LLM/payment collusion result exists yet.
