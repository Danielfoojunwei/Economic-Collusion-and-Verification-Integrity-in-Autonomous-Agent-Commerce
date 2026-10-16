# W19/G7 analysis preparation

**Gate status:** PREP PASS; W19 confirmatory registration/run and G7 **PENDING**.
No G4 treatment outcomes were read or used. No model calls or native payments
were made by this work order.

## Work and evidence

- Work ID: W19 preparation candidate. Dependencies W18 and completed G4 remain
  unsatisfied for W19 execution.
- Model/payment execution tier: `NOT_EXECUTED` / `NOT_EXECUTED` for this work.
- Files: `docs/W19_PREREGISTRATION_CANDIDATE.md`,
  `src/agent_economic_trust/w19_analysis.py`,
  `src/agent_economic_trust/w19_power.py`, `scripts/run_w19_power.py`, and
  `tests/test_w19_analysis.py`.
- Commands actually run:

  ```sh
  PYTHONPATH=src python -m unittest tests.test_w19_analysis -v
  python -m py_compile src/agent_economic_trust/w19_analysis.py \
    src/agent_economic_trust/w19_power.py scripts/run_w19_power.py
  ```

- Result: six synthetic tests passed; compilation passed. Tests verify a known
  factorial effect, pair-level randomization test, cluster bootstrap,
  all-assigned missingness bounds, family-wise decisions, refusal of scripted
  calibration, deterministic scenario simulation, and projected budget flag.
  These tests establish analysis plumbing, not power or a research result.
- Independent verifier statement: the synthetic known-effect test recovers
  expected contrasts; a future source-evidence verifier must authenticate G4
  model/native records before constructing calibration or final outcomes.
- Evidence limitation: G4's 32 unique pair IDs cover only four private task
  worlds, with two bad-work pairs per arm. There is no independent held-out W18
  task/model population, no real randomized pilot rate supplied to this power
  tool, and no preregistered sample size. No confirmatory freeze or claim is
  made.
- Next eligible action: finish G4, W18, independent outcome verification and
  real-pilot calibration; review and freeze a feasible W19 plan before a
  confirmatory run. Any projected spend must remain within the existing shared
  ledger or receive separate owner authorization.
