# Validated engineering outputs — 15 October 2026

**No-funds, scripted simulation only. Not research evidence of emergent collusion, live agent payment security or SDK conformance.**

## Run manifests

- `runs/realism_pilot`: 67,200 matched-world cases; 12 offline protocol-shaped adapters; 10 fixture-audited tasks; 14 scenario classes; 5 application guards; two scripted verifier policies; two task qualities; two seeds.
- `runs/realism_factorial`: 17,280 paired-world cases; six representative payment families; full 2×2×2 financial relationship × feasible audit scarcity × persuasive message; three guards; two scripted policies; two task qualities; three seeds; ten tasks. The export contains 2,016 descriptive factorial-effect lines and 1,728 pass^k rows.
- All **84,480** exported trial event lists passed recomputation of the local SHA-256 trace digest. This is an archive-integrity check, **not** digital signatures or independent witness notarization.
- **41** Python unit/integration tests passed, including mock-loopback model API isolation, no-private-test leakage, and three x402 v2 payment-stage variants. The model-API mock is not a real LLM evaluation.

## Selected mechanistic expected results (NOT discoveries)

Each row aggregates **80 scripted simulation worlds** across tasks, model-policy labels, work qualities and seeds; scenarios with a replaced deliverable are invalid by construction even if the originally submitted work passed.

| Protocol-shaped flow | Scenario | Application guard | Wrong-work payments / 80 | Interpretation |
|---|---|---|---:|---|
| ERC-8183 evaluator escrow | post-audit deliverable replacement | none | 80 | local escrow trusts designated evaluator without checking the final content binding |
| ERC-8183 evaluator escrow | same | receipt-binding guard | 0 | non-native application guard detects changed digest before release |
| x402 v2 default authorization | same | none | 80 | local server could settle based on unchecked final artifact; this is not a standards exploit |
| x402 v2 default authorization | same | receipt-binding guard | 0 | non-native post-handler guard vetoes settlement before 200 |
| x402 v2 upfront | same | receipt-binding guard | 80 | funds already paid; post-delivery guard cannot undo the charge |
| MPP charge | same | receipt-binding guard | 80 | prepaid charge remains despite later evidence failure |
| ERC-8183 evaluator escrow | independently good/bad baseline | none | 0 | fixture/oracle calibration plus scripted checks, not measured model robustness |

**Additional controlled controls:** A distinct transaction ID may pay for the same economic task twice in this deliberately permissive application. The application `obligation_dedupe` policy prevents the duplicate in the sandbox. It is **not proof of an ERC-8183 or x402 nonce-replay bug**: a distinct job can legitimately be independently payable unless the principal constrains its business obligation. A same-identity 25% price increase relative to an experimental reference price persists after an objective work-quality recheck, because checking work quality does not enforce a customer's reference-price preference. Neither finding implies that an accepted market price was unlawful or cryptographically invalid.

## Interpreting the factorial outputs

The `economic` policy's probability coefficients are explicitly authored in `paidaudit/policies.py`. Therefore any estimated effects of relationship, scarcity or persuasion in `factorial_effects.csv` are predominantly consequences of the **chosen simulator**, not observations about the behaviour of GPT, Gemini, Claude, Qwen or any live model.

The 2×2×2 contrast calculator and clustered bootstrap routine themselves are tested and executable. The test utility is to calibrate the study design and data plumbing *before* running actual models. More than a few seeds and substantial changes in the agents' task generation, evidence and adversarial capabilities are essential for inferential research.

## Reproduce

```sh
python -m unittest discover -s tests -v
python -m paidaudit wire-smoke
python -m paidaudit verify-log runs/realism_pilot/trials.jsonl
python -m paidaudit verify-log runs/realism_factorial/trials.jsonl
python -m paidaudit realism-run --config configs/realism_pilot.json --out runs/realism_pilot
python -m paidaudit realism-run --config configs/realism_factorial.json --out runs/realism_factorial
```

The exact standards/SDK version must be pinned and the live protocol suites rerun before publishing any claim about standards conformance or exploitable flaws.
