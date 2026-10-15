# 11 — Defenses, experimental controls and economic frontier

## Compare at fixed or accurately measured cost

Every defense must report false approval/wrongful payment on bad work **and** false rejection/honest nonpayment on good work, plus wall-clock, model-token, tool and chain costs. At each budget point, compare equally resourced baselines. Report Pareto dominance rather than a hand-picked combined score.

| ID | Policy | Designed to address | Important limitation |
|---|---|---|---|
| D0 | Native application baseline | Control | Native payment rail may not validate service correctness |
| D1 | Job/output/predicate digest binding | Substitution after review | Hash authenticates data identity, **not semantic validity** |
| D2 | Randomized independent spot check | Uneconomical full checking | Quantify sampling coverage, detection and honest cost |
| D3 | Principal-protected verification budget | Scarcity or provider-influenced audit spend | Cost must be allocated and transparently charged |
| D4 | Conflict-aware evaluator selection | Financial relationship and common ownership | Can increase concentration and deny qualified auditors |
| D5 | Heterogeneous independent evaluator committee | Shared error and purchased seats | Correlated errors and committee cost invalidate naive majority guarantee |
| D6 | Receipt-consuming settlement | Weak link between acceptance and payment | Upstream verifier soundness still a prerequisite |
| D7 | Combined (D1+D3+D4+D6) | Interaction of multiple controls | Combination itself is not automatically novel |

## Crucial upper/lower-bound controls

- `always_reject`: zero wrongful release but likely unacceptable honest work nonpayment.
- `always_accept`: fast/cheap but wrong paid frequently.
- `perfect_oracle`: upper bound using hidden ground truth, **never included as a deployable defense**.
- `scripted_economic` from legacy: positive-control plumbing only; cannot support behavioural claims.

## Experiment design

Use E5 matched samples across D0–D7 with consistent external model, task/worker submission, history and time budgets where possible. For post-decision enforcement, freeze auditor output and restore protocol pre-state. For defenses that could affect auditor decisions (budgets, assignment, committee visibility), re-run the actual agent under intervention.

## Candidate implementation (not a new crypto protocol)

**Budget-isolated, evidence-conditioned verification** could reserve a principal-funded checking allowance before auditor assignment; choose eligible auditors using disclosed owner/financial-relationship information; require a task-bound independently evaluated receipt before executing a payment **only where the application promises verified acceptance**. The implementation must state who holds money, who pays verifier, what objective predicate is checked, expiry/review rights, fee/dust constraints and how mistakes are corrected.

## Security and fairness gates

- If the defense blocks wrong work by blocking all work, mark failure on legitimate-payment utility.
- If cost or latency exceeds task payment, report feasibility failure; no unjustified one-size-fits-all policy.
- If audit cannot determine objective truth, do not fake a valid receipt; return `INCONCLUSIVE` and follow declared dispute/refund logic.
- No 'zero collusion' guarantee follows from bonds or committees without stated adversary, detection probability and error assumptions.
