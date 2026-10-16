# PaidAuditBench v0.2 realism study

**SIMULATED, NO FUNDS. Not evidence of protocol exploits or LLM-agent collusion.**

17,280 matched local trials over 6 protocol-shaped adapters and 10 audited tasks.

The same original auditor decision is frozen and replayed under all defenses for every task/scenario/policy/seed/protocol cell.
This permits descriptive *post-decision* comparisons only; it is not evidence that verifier model behavior is unchanged if deployed guards are advertised upstream.

## Result inspection

`trials.jsonl`: full event logs and hidden-ground-truth scores.
`summary.csv`: complete per-protocol/per-scenario/guard counts including legitimate nonpayment and audit costs.
`paired_defense_contrasts.csv`: matched no-guard comparisons; synthetic descriptive only.
`factorial_effects.csv`: 2x2x2 contrasts with task-cluster bootstrap CIs (only for full factorial runs).
`reliability.csv`: tau-bench-inspired pass^k when at least k random seeds exist.

## Selected synthetic scenario counts

| Scenario | Guard | Trials | Improper payments | Legitimate nonpayments |
|---|---|---:|---:|---:|

**Cautions:** The baseline simulator executes distinct protocols at different payment stages by design. Comparing raw payment counts is not a standards security ranking. Objective recheck is an *idealized application-level* oracle funded from a separate 4-credit budget; fraud reduction cannot be claimed for production without a real verifier.

## Reproduction

`python -m paidaudit realism-run --config configs/realism_pilot.json --out runs/realism_pilot`

`python -m unittest discover -s tests -v`
