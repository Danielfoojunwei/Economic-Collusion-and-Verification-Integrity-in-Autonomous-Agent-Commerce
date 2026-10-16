# Stage gates / stop conditions

## G0 — Packaging + prior artifact provenance

**Pass:** supplied ZIP self-test succeeds; legacy 41-test expected suite results captured without mutations; old offline runtime deliberately marked simulation-only; upstream inventory prepared. **Stop** on missing source files, an invalid archive, or unverifiable provenance.

## G1 — ORBIT/Inspect + truthful ground truth

**Pass:** valid ORBIT/Inspect task and separated worker/auditor action record, costed verification, independent scorer, and no ground-truth leakage. A real local model is needed for **behavioural** claim, but deterministic mock may pass plumbing subgate only. **Stop** if neither independent scorer nor isolation passes.

## G2 — ERC-8183 native local chain

**Pass:** pinned upstream contracts actually deployed to isolated Anvil; valid and invalid roles/state transitions tested; balance conservation/event trace and refund/claims available; no real assets. **Stop** if only legacy Python mock exists.

## G3 — x402 native localhost

**Pass:** pinned official x402 v2 payment-scheme/transport SDK produces verified signed authorisation and separate settlement records; replay/freshness checks and timing tested; exact scheme version recorded. **Stop** if mock HMAC is mistaken for official signature.

## G4 — Causal live-agent pilot

**Pass:** real model decisions, independently randomized financial relationships, budget feasibility, blinded truth, treatment adherence, valid inference unit; proper null controls. **Stop** if experiments use only authored scripted policy coefficients or confounded assignment.

## G5 — Equal-cost defenses

**Pass:** both good/bad tasks, honest-payment fairness, measured cost, latency and uncertainty; a defendable frontier comparison. **Stop** if outcome is 'all reject' or defense has omniscient oracle access while described as practical.

## G6 — Broader protocols

**Pass:** each additional protocol is pinned and tested with native behavior relevant to its intended guarantee, or explicitly SKIPped with exact cause. **Stop** comparative ranks that treat A2A/registry or checkout as evaluator escrow.

## G7 — Confirmatory science

**Pass:** preregistered hypotheses and smallest effect, cluster-aware power analysis from real pilot, held-out tasks, multiple model versions, no data leakage, freeze of prompts/configs. **Stop** if cherry-picking/missing denominators persists.

## G8 — Paper submission readiness

**Pass:** every number traces to executable reproducible analysis; all prior work is represented fairly; results have uncertainty, confounds, limitations; source/data licences and ethics cleared; claims restricted to evidence level. **Stop** before a manuscript abstract claims any result from a mock simulation.

## Owner decision points

Get user approval before paid remote model use, long autonomous runs, any testnet network traffic, external credential setup, new research hypothesis after confirmatory freeze, or deployment beyond localhost. A technical blocker is not permission to fabricate a substitute.
