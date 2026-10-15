# 15 — Evidence ledger and permitted claim ladder

## Current evidence ledger (as packaged)

| Record | Status | Supports | **Does not support** |
|---|---|---|---|
| Preliminary 12-page PDF | USER-SUPPLIED PRELIMINARY NARRATIVE | Prior claimed results: impossible verification, independent errors, random offers, provider reasoning trust | Native payment vulnerability or actual new ERC-8183/x402 study |
| PaidAuditBench v0.2 source | LEGACY SCRIPTED OFFLINE | Task examples, script harness, local event accounting, regression tests | Open-source ORBIT integration, LLM collusion, financial motivation |
| Legacy v0.2 full archive | SCRIPTED_SIMULATION | 67,200 local pilot + 17,280 factorial event traces; SHA-256 local digest | 84,480 independent live model observations or verified transactions |
| ORBIT/Inspect upstream | EXTERNAL PUBLIC SOFTWARE | Reusable multi-agent execution, scheduling, scoring; needs pin/install | Already integrated into *this* research project |
| Colosseum upstream | EXTERNAL PUBLIC SOFTWARE | Published action/coalition metrics; needs faithful reproduction | Economics or native payments already reproduced here |
| ERC-8183/x402/MPP/AP2/etc. specs | EXTERNAL PUBLIC REFERENCES | Version-specific intended native semantics | Proof that their SDKs were executed in this workspace |

## Claim ladder

**L0 — Architecture proposal:** a design document; no measured effect.  
**L1 — Offline scripted simulation:** tests instrumentation/logging and authored hypotheticals.  
**L2 — Real LLM behavior with mock payments:** measures actual agent choices under stated simulated economic incentives; still no native transaction claim.  
**L3 — Real LLM + native local payment flows:** supports protocol-specific combined security observations under local contracts/facilitators.  
**L4 — Multiple model families/tasks/native flows + proper randomization:** supports bounded generalization to tested settings and defensible causal/negative results.  
**L5 — Deployment claims:** require independent real-world operational evidence beyond this package; do not claim from local/testnet study.

Use claim level L0–L4 explicitly when writing interim reports. No manuscript abstract result should be based on L1 authored coefficients.

## Failure and contradiction policy

If new native protocol evidence contradicts simulator assumptions, mark the legacy simulator behavior as a modeling assumption, not a protocol defect. If a real LLM effect is zero or changes sign, report it, preserve planned denominator, and investigate only in a separately marked exploratory branch. Every published numerical table must point to a frozen script and run ID.

## Versioned change log to maintain

Append a dated entry with: claim ID, exact statement, evidence file/path, source version, compute script, assumption, supported level, independent verifier, and status `PROVED/OBSERVED/SIMULATED/OPEN/REFUTED`. **Do not use PROVED for probabilistic model behavior**; prefer observed under sample conditions.
