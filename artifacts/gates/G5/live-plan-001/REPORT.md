# W13/G5 live decision replay and prospective defense assignment

**Superseded by `../live-plan-002/REPORT.md`.** The successor freezes exactly
four planned spot checks in each costed prospective arm. This directory is
preserved as an exploratory artifact of the earlier planner version.

**Gate status: PENDING.** This is a read-only follow-up to the G4 live-agent
pilot. The source decisions and native ERC-8183 settlements are real local
evidence. Every defense result here is a projected application decision;
there was no defended settlement or new model call in this W13 run.

## Work-order record

| Field | Record |
| --- | --- |
| Work ID / dependency | W13 offline preparation after G4 exploratory collector; G5 equal-cost effectiveness pending |
| Source evidence | `source_collection/records.jsonl` SHA-256 `e84310e7a0916dddfc1b0d3358c684f34b82b56d4c005b56501042773e90787e`; G4 assignment-003 manifest SHA-256 `369b63133240346994c506a80b2efbe4ab554e14a20b817f61f2519eee48eded` |
| Collector proof | 32/32 complete G4 records independently validated by reopening saved Inspect logs with resolved attachments, native local transaction receipts, balances, v1 event exports, source hashes and the canonical USD 20 model-spend ledger; 0 failed evidence rows |
| Model / payment tier | Source: `REAL_LLM_REMOTE_APPROVED` / `NATIVE_LOCAL_CHAIN`; W13 replay: no new model call / `DEFENSE_NOT_EXECUTED` |
| New evidence | `retrospective_replay.json` SHA-256 `0c3f752a26109ed289b7b77cc37998453dfcef0116a9c07d4ec5d84c12a247f0`; `prospective_assignment_manifest.json` SHA-256 `b6feb895dd1703da383752f4d82f9cb9b10885c4caf2feaad8afbc4853604ed6`; `seed_material.json` SHA-256 `e6cf3f923b0f1ea991cdbe07cf9e72a64c20a5d8652b69e371d1289e5e1aeeaa` |
| Command | `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_w13_live_plan.py --assignment-dir artifacts/gates/W10_DESIGN/assignment-003 --runs-dir artifacts/gates/G4/live-trials --output-dir artifacts/gates/G5/live-plan-001 --spot-seed <seed_material.json value> --prospective-pair-seed <seed_material.json value> --prospective-defense-seed <seed_material.json value>` |
| Tests | `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_w13_live_defense_plan -v`: 8 PASS, 0 FAIL, 0 SKIP. `python -m py_compile` passed. |
| Files changed | New module `src/agent_economic_trust/w13_live_defense_plan.py`, runner `scripts/run_w13_live_plan.py`, test `tests/test_w13_live_defense_plan.py`, and this G5 evidence directory. No original handover or G4 source file changed. |

## Source observations and projected replay

The 32 G4 source pairs had 16 good and 16 bad warehouse worlds across two
public task domains. All 32 live auditors bought an authoritative check. All
16 good claims were accepted and paid; all 16 bad claims were rejected and
refunded. Source runs used 192 model calls and 64 application check units;
the conservative model-spend estimate summed to USD 1.811760. Those are
**source G4 observations**, not new W13 outcomes.

The replay selected four of eight economic treatment cells by a saved HMAC
seed. Selection depended on cell labels, not the hidden warehouse label. That
selects 16 G4 trials, with eight good and eight bad worlds. The `digest_spot_check`
and `principal_check_budget` branches each bought 16 additional local oracle
checks; the `unchecked_reference` bought zero. A private oracle callback was
the only route from the dispatch code to warehouse truth. The two costed
branches had the same selected rows, exact extra check-unit parity, and the
same projected outcomes. Both guards projected zero bad payments and zero
good nonpayments, identical to the unchecked source reference. No defense
reduced errors because there were no errors in these source decisions.

| Branch | G4 source pairs replayed | Extra local checks | Projected bad paid / 16 | Projected good unpaid / 16 | Defended native payment |
| --- | ---: | ---: | ---: | ---: | --- |
| Frozen live verdict reference | 32 | 0 | 0 | 0 | None |
| Digest-bound spot check | 32 | 16 | 0 | 0 | None |
| Principal-owned check budget | 32 | 16 | 0 | 0 | None |
| Independent reviewer | 0 | Not measured | Not estimated | Not estimated | None |

The extra check unit is application accounting; its Python callback wall
time is in each replay row. G4's existing native payments are retained as
source provenance. The replay never rolls back or replaces those chain states.
The two costed policy labels alter budget ownership, but the offline check
logic is otherwise identical. They cannot distinguish a budget-ownership
effect on agent behavior.

## Prospective design and limits

The separate prospective manifest uses a new pair seed and a separate defense
seed. It specifies 32 new pair IDs, one assignment in each of eight R/S/P
cells for each of four defense arms, and four good plus four bad private worlds
per arm. Private fixture IDs are for the controller and must not enter model
inputs. Each pair has a distinct planned reviewer ID; this alone does not
establish an independent reviewer. The manifest is **planned only**. No
prospective model action, new fee transfer, check, or settlement has occurred.

G5 needs a prospective runtime that enforces each policy before native
settlement, a distinct live independent auditor with verified tool and role
isolation, measured actual model/check/gas/latency costs, and a defensible
uncertainty analysis across more task instances. An equal check cap is not an
equal realized cost. The two task domains and four frozen private worlds are
too narrow for a publishable defense frontier. The retrospective selection
was produced after G4 outcomes existed and is hypothesis-generating only.
