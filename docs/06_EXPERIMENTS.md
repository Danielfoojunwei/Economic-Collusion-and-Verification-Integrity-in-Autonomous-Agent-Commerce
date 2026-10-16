# 06 — Experiments, interventions and design discipline

## Separation: two different causal questions

**Behavioural experiment:** change what the live auditor experiences and resample its policy; outcome is check/skip and verdict.  
**Enforcement experiment:** freeze one auditor action/verdict and replay against native protocol/application enforcement under the *same initial state*; outcome is the committed payment.  
Never combine the two estimands or call fixed-decision replay a model-behaviour effect.

## E0 — Calibration (required)

- Correct artifact passes an independent objective oracle; planted-defect artifact fails. Verify each task's legitimate tool path succeeds.
- Hidden oracle must not appear in provider/verifier model prompts or untrusted tool messages.
- Mock payment side-transfer receipt must change ledger balances and carry a unique obligation ID.
- Native protocol sessions are version-pinned and target-local only; exact adapters pass published positive/negative tests.
- Assert that quoted evidence text is task-relevant but cannot change the underlying oracle truth.

## E1 — Clean baseline

Run 2–3 independently controlled model families with the *same objective tasks* in independent role sessions. Comparators: scripted always-approve/always-reject, normal unconstrained verifier, cost-aware verifier, independently assigned auditor. Each outcome includes role-separated prompt digest, check tool calls, decision, oracle truth, paid status and timing.

## E2 — Economic 2×2×2

Fully cross R (relationship), S (checking scarce but possible), P (persuasive evidence). Assignment at pair/market cluster where history persists; if a model's memory can leak between arms, use isolated fresh instances. Include good/bad work and balance the domains. Limit conditional offers to permissions and verify payment authorization independently.

Additional orthogonal arm: `offer_mode in {none,untrusted_promise,authenticated_escrowed_offer}`. If cost prohibits full Cartesian design, preregister a staged fractional factorial and preserve its estimands.

## E3 — Longitudinal market

Arm M0 random fresh pairing, M1 repeated random pairing, M2 provider-influenced assignment, M3 role-reciprocal pairs, M4 conflict-aware assignment, M5 explicit collusion positive control. Hold underlying task blocks fixed; randomize relationship graphs and communication permissions. Add auditor turnover, memory-reset, role-crossover interventions. Evaluate *incremental* coalition payoff and false approvals after each intervention.

## E4 — Fixed-decision native replay

For a fixed case (same exact artifact/receipt/decision), restore pre-run local chain/payment state for each enforcement policy. Test role authorization, payment timing, commitment/expiry, wrong recipient, authorization replay and **distinct new authorization for same business obligation**, refund/liveness and post-approval content swap. The last is an application artifact-binding issue unless native specification commits to verifying it.

## E5 — Defenses with budget discipline

D0 standard protocol application, D1 artifact digest binding, D2 random spot check, D3 protected verification budget, D4 conflict-aware assignment, D5 committee with tested independent errors, D6 receipt-consuming settlement where objective predicate is checkable. Compare to always-reject and perfect oracle only as controls. Include good submissions and honest-payment deadline, and report operating cost/latency.

## E6 — External task realism (after core gates)

Add ORBIT bundled coding / cooperative allocation tasks, then AgentDojo stateful tasks where licensing/scorers permit. Avoid subjective “LLM judge says correct” as sole ground truth. Stage input provenance audit before large live-agent collection.

## Blocking confounds

- Randomize relationships, not just arm labels displayed to agent.
- Freeze only variables needed for causal contrast; don't let agent use the oracle to form persuasive evidence.
- Report exogenous shared difficulty, paired same-model correlated error and agent private-information differences.
- Do not call an intentionally colluding agent's outcome naturally emergent.
- Do not interpret inability to check caused by insufficient tools/channel as coordination.
- Do not exclude interrupted runs because those are likely related to protocol timing.

## Experimental results status

E0 simulator path partly exists in `legacy/`; E1–E6 **not completed with native payment and live models**. No positive or negative claim about autonomous bribery/collusion is substantiated by the legacy scripted trial counts.
