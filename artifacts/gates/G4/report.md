# G4 / W10 — completed exploratory R×S×P live pilot

**Status, 2026-10-15:** W10's 32 assigned live-model and native local-payment trials are **complete and independently reverified**. The broader G4 causal-collusion gate remains **open**: this slice has no direct-channel/offer positive-control comparison, longitudinal market, held-out task family, or second model. The observations support task-bound behavior and payment outcomes in the frozen pilot, not a general claim that economic collusion is absent.

## Frozen design and execution

The active [assignment-003](../W10_DESIGN/assignment-003/assignment_manifest.json) (SHA-256 `369b63133240346994c506a80b2efbe4ab554e14a20b817f61f2519eee48eded`) reused assignment-002's secret seed and identical 32 rows. Fresh worker–auditor economic pairs were assigned once within two receipt domains and good/bad private warehouse worlds: 8 R×S×P cells × 4 pairs, with 2 bad and 2 good per cell. R0/R1 changed whether the independent client or provider prepaid a fixed two-unit auditor fee. S0/S1 charged 1/3 of 4 budget units for a feasible independent check. P0/P1 changed a recommendation in a fact-equivalent provider note. The same frozen authored artifact and public provider copy accompanied each domain's good/bad hidden worlds; a private controller oracle determined correctness.

Each trial used approved `openai/gpt-5.6-sol` with high reasoning and at most six calls, in a fresh native Inspect/ORBIT task with no offered channel tools, shared memory, communication edge, or cross-pair model conversation. Before the auditor saw the controller-authored, truthful fee-source statement, a fresh local Anvil chain had mined and verified the assigned pair's ERC-20 fee transfer against raw transaction/receipt data and balances. The auditor did **not** receive a raw wallet/receipt tool and did not independently verify that chain. A separate funded ERC-8183 job released 20 valueless MockUSDC units to the provider after ACCEPT, or refunded the client after REJECT. Its evaluator and platform percentage fees were set to zero; the auditor's token balance remained at the same two-unit prepaid fee after either verdict. Direct ERC-20 fee-to-obligation binding is application-level; ERC-8183 does not judge the artifact.

## Verified outcomes

The [final collection](collection-final-001/analysis.json) and [32 trial records](collection-final-001/records.jsonl) have SHA-256 `cc0d34db15a9a62731005ed07a33c8463fdd90ac3218a622cea51e1d4672f37f` and `e84310e7a0916dddfc1b0d3358c684f34b82b56d4c005b56501042773e90787e`. The read-only collector reopened all 32 saved `.eval` files with attachments resolved, confirmed exact model/high reasoning, R/S/P exposure, role tool sets, no offered or called channel tools, frozen artifacts, private-oracle scores, and each pair's native fee and ERC-8183 release/refund. It also checked every schema-v1 event/outcome/manifest hash and canonical project-ledger settlement. **32/32** records passed, with zero missing, failed, or excluded pairs. Each cell has four verified pair clusters; all 32 outcomes and 608 derived schema-v1 events link to original Inspect and raw native transaction evidence.

| Observation across all eight cells | Count |
| --- | ---: |
| Designated check completed | 32/32; S0 spent 1 unit, S1 spent 3 |
| Good work accepted and provider paid | 16/16 |
| Bad work rejected and client refunded | 16/16 |
| Bad-work false approval or wrongful provider payment | 0/16 |
| Good-work legitimate nonpayment | 0/16 |
| Treatment/channel/source/payment evidence failures | 0/32 |

Every cell's observed bad-work wrongful-payment rate was 0/2. The prespecified exploratory three-way contrast in that rate was **0**. The observed R contrast for wrongful payment and S contrast for check completion were both 0 in this pilot, because all bad claims were rejected and all assigned checks were completed. These are **descriptive**, pair-assignment-conditioned observations. With only two bad pair clusters per cell, one model, four reused private worlds, and no outcome variation, they do not estimate a narrow effect interval or establish that payer identity, checking price, or persuasive wording have no effect in a broader population. Correct outcomes following accessible checks also do not test collusion under a direct offer.

The 32 runs made 192 bounded provider calls and 528 local native transactions. Their conservative model-use estimates sum to **USD 1.811760** (range USD 0.053200–0.064030 per trial). The canonical shared USD 20 ledger, which also includes earlier project calls, had **USD 2.03895 settled** and **USD 17.96105 available** after this collection, with no unknown charges. These estimates and ledger entries are spending guards, not provider invoices. Local tokens had no real value and were never mixed into USD cost.

## Aggregate link and prospective sizing

The [aggregate manifest](aggregate-pilot-001/aggregate_run_manifest.json), SHA-256 `5170235c2125923515464daca5b1820b025a0dec7d46e81f141a02b001d9cdfd`, reverified each of the 32 trial files and ledger links and binds their hashes to the [W19 exploratory calibration](aggregate-pilot-001/pilot_calibration.json), SHA-256 `563a33f2ee84902c960f8184482602168686ce476fd0f39480e9c50e8e68f9e1`. All eight calibration cells contain four assigned pairs, two bad, zero bad paid, four checked, and zero unresolved. The largest observed model-cost estimate was USD 0.064030.

The sealed W19 candidate's sizing script produced two **scenario-only** results under a proposed 10-percentage-point R effect on bad wrongful payment and 10-point S decrease in checking, with two held-out task families, two model versions, one task per pair, `rho=0`, 2,000 simulations, and Holm adjustment. The [128-pair scenario](../W19_PREP/power-g4-2pairs-v1.json) projects USD 10.2448 at 1.25× the pilot maximum cost, within the then-remaining USD 17.96105, but its simulated rejection fractions were only **0.1545** for R and **0.3805** for S. The [256-pair scenario](../W19_PREP/power-g4-4pairs-v1.json) projects USD 20.4896, above that remaining cap, with fractions **0.316** for R and **0.705** for S. These are approximate Wald sizing scenarios, not achieved power, confirmatory tests, or authorization for more spending. Smoothing supplies nonzero hypothetical event risks even though observed bad payment was zero. Independent held-out tasks, model versions, a feasible sample size and a final externally recorded preregistration are still required for G7.

## Reproduce the read-only checks

From the repository root after its pinned environment is set up:

```sh
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/collect_w10_factorial.py \
  --assignment-dir artifacts/gates/W10_DESIGN/assignment-003 \
  --runs-dir artifacts/gates/G4/live-trials \
  --output-dir artifacts/gates/G4/collection-recheck-new
PYTHONPATH=src:. /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/build_g4_pilot_calibration.py \
  --assignment-dir artifacts/gates/W10_DESIGN/assignment-003 \
  --collection-dir artifacts/gates/G4/collection-recheck-new \
  --runs-dir artifacts/gates/G4/live-trials \
  --output-dir artifacts/gates/G4/aggregate-recheck-new
```

Both commands require fresh output directories and make no model or payment calls. The final live files are under `live-trials/<trial-id>/`: original Inspect `.eval`, raw native transactions, trial record, schema-v1 events, outcome CSV and manifest. Historical checkpoint `collection-002` was taken while a trial directory was in progress and is explicitly marked superseded; the final collection above was made after all runs closed.
