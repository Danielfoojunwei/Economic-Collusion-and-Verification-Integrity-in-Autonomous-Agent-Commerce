# 02 — Full manuscript blueprint (claim-led, not platform-led)

**Working title:** *When Agents Pay Their Auditors: Economic Collusion and Verification Integrity in Autonomous Agent Commerce*.

## Narrative

1. Agents move from asking/answering to hiring, verifying and paying other agents.
2. A valid payment can pay for bad work; a valid evaluator identity or signed statement is not automatically trustworthy evidence.
3. Existing work covers payment protocol integrity and collusion in isolation; closely related SoK already theorizes economic reviewer manipulation, so we must study **actual verifier decisions + financial history + authentic payment consequences**.
4. Prior preliminary PDF challenges simplistic joint-acceptance collusion definitions and reports no effect of one kind of synthetic bribe; this motivates meaningful negative controls and authentic financial conditions.
5. Reuse ORBIT and Colosseum, then add only the economic/payment layer to test the missing causal mechanisms.
6. Native ERC-8183 and x402 demonstrate contrasting enforcement timings; other protocols extend coverage without being falsely compared as equivalent.
7. Evaluate whether any practical verification policy improves wrong-payments vs legitimate-payments vs cost/latency.

## Section-by-section structure

| Section | Goal | Minimum required evidence / figure |
|---|---|---|
| Abstract | Research problem, instrument, actual outcomes, limitations | Write **last**, no numbers until verified |
| 1 Introduction | Concrete paid coding-agent job with worker, verifier, principal, payment | Fig. 1 trust boundary; 4–5 explicit contributions after evidence |
| 2 Related Work | Colosseum, Emergent Collusion, ORBIT, AgentDojo, CABAL, protocol security, auditor mechanism design, decentralized agent economy SoK | Table 1 nearest-neighbor matrix |
| 3 Definitions & RQs | False approval, unchecked approval, wrongful settlement, coordination, financial dependence, honest nonpayment | Mathematical definitions and hypotheses |
| 4 System & Threat Model | Roles, capabilities, admissible manipulation surfaces, trust assumptions, objective correctness and oracle limitations | Fig. 2 actor+authority graph; explicit out-of-scope |
| 5 Experimental Substrate | ORBIT/Inspect reuse, Colosseum baseline, task fixtures, native protocol adapters, event schemas | Fig. 3 thin integration and case state machine |
| 6 Methods | Clean baseline, economic 2×2×2, longitudinal market, fixed-decision protocol replay, defenses | Fig. 4 randomized treatment and intervention diagram |
| 7 Results | RQ1 influence, RQ2 mixed pressures, RQ3 coordination, RQ4 settlement consequences, RQ5 defenses | Real model and native outcomes only; uncertainty |
| 8 Mechanisms | Tested guard(s) + assumptions + cost and false-rejection accounting | Security–cost–fairness frontier |
| 9 Discussion | What actually explains harm; validity vs conformance; trade-offs | Negative results and falsified hypotheses discussed |
| 10 Limitations | Evaluation domain, model/SDK versions, temporal generalization, missing task truth, realistic money incentives | Explicit failure modes, availability |
| 11 Conclusion | Narrow supported statements and reproducibility paths | No extrapolation to all agents/protocols |

## Candidate contributions (conditional)

C1. Empirical evidence on live LLM verifier responses to randomized **authentic** financial influence with checking effort observed via tool calls.  
C2. Identified interaction of credible relationship × resource scarcity × evidence presentation, with appropriate negative/null controls.  
C3. Coordination-attribution analysis distinguishing common error from direct manipulation and coalition-specific advantage under interventions.  
C4. Native comparison of payment *consequences* for the same frozen verifier decision across compatible flows with security assumptions explicitly qualified.  
C5. Evaluated cost-budgeted guard achieving a frontier change (only if observed).

Do **not** number these as finished contributions in a submission until the relevant empirical gate passes.

## Required figures

- F1 actor/payment/evidence boundaries.
- F2 ORBIT/Inspect-based experiment + native protocol replay architecture.
- F3 full factorial treatments and randomized unit.
- F4 audit rate / false approval / confidence intervals by economic influence.
- F5 longitudinal financial relationship graph and assignment/communication interventions.
- F6 frozen-decision guard/protocol counterfactual outcomes.
- F7 wrongful payment vs honest nonpayment vs audit cost/latency Pareto plot.

## Required tables

- T1 prior-work novelty matrix.
- T2 task families and ground-truth procedures.
- T3 protocol target properties and conformance status.
- T4 threat actors and action/control permissions.
- T5 treatment matrix and preregistered estimands.
- T6 real-agent outcomes and model heterogeneity.
- T7 native payment outcomes + exceptions.
- T8 defense trade-off at matched budget.

## Appendix obligations

Exact prompts; version-locked model identifiers; ORBIT/Inspect releases; task hidden-oracle separation checks; precise randomization; SHA of outputs; native SDK/testnet transaction evidence; exclusions and incomplete-run denominators; environmental resource/cost accounting; source and dataset licences; confidence intervals and robust null interpretation.
