# BILATERAL030 30-row scripted infrastructure rehearsal

`stress-index.json` records **30/30 complete scripted simulations** over seven
predeclared arm slots (12/4/4/4/2/2/2) and 15 assigned slots in each proposed
Sol/Sonnet model direction. The assigned hosted model IDs were **never called**:
both actual ORBIT routes were `mockllm/`. Every row has
`scientific_result_row=false`, a fresh valueless local Anvil ERC-8183 job,
raw Inspect `.eval`, native transactions and receipts, and replay reports.

The guarded run took 247.922 seconds. All 30 pre-view funding archives were
read-only verified against their still-live local chain before either scripted
role acted. Inspect trace replay confirmed the exact independent public funding
proof in both mock role inputs and the auditor inbox for all 30. Each row's
terminal native receipts and Inspect action trace passed read-only replay and
were joined on its assignment, job, report and transaction hashes. The index
records 14 frozen source file hashes; they remained stable throughout the run.
All 210 summary-referenced file SHA-256 hashes were rechecked after completion.
No failure file exists. A second process independently replayed all 30 saved
rows, matching their native, funding and Inspect reports. It cannot recheck
the stopped local chains against live RPC after the fact.

The fixed scripts injected 14 BAD first-claim APPROVEs (seven after a paid
FAIL check and seven without buying a check), 12 BAD first-claim REJECTs, and
four GOOD APPROVEs after paid PASS checks. These actions demonstrate that the
native first-claim and side-bonus mechanism can pay on an improper approval;
they are **not agent-chosen collusion**. The scripts also create a spurious
apparent model-direction pattern: among BAD checked APPROVEs, six slots were
assigned a Sol provider and one a Sonnet provider. Those assignments were
labels only, and this rehearsal supports no model comparison or ablation effect.

No remote model call, live LLM behavioral trial, causal ablation result, or
observed bilateral collusion is in this package. The separate
`ERC8183_BILATERAL030_STRESS_SMOKE001` attempt was aborted after its replay
checks because of summary path serialization and is excluded from this 30-row
count. `ERC8183_BILATERAL030_STRESS_SMOKE002` is a separate completed GOOD,
no-bonus smoke row, also excluded.
