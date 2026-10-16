# Codex handover / response format

## Files Codex must acknowledge

- `AGENTS.md` and `CODEX_MASTER_PROMPT.md`.
- `docs/01` charter, `docs/03` novelty, `docs/04` RQs, `docs/05` threat model, `docs/08` protocol list, `docs/09` runtime, `docs/10` metrics, `docs/13` safety, `docs/15` evidence ladder, `docs/16` upstream sources.
- `planning/FIRST_48_HOURS.md`, `planning/WORK_ORDERS.md`, `planning/ACCEPTANCE_TEST_MATRIX.md`, `planning/STAGE_GATES.md`.
- Inputs/legacy original PDF/source/raw simulation archives.

## Completion report (every gate)

```markdown
## Completed: Wxx / Gx
**Implementation tier (model, payment):**
**Upstreams and SHA pins:**
**Commands actually executed:**
**Tests:** PASS=x, FAIL=y, SKIP=z (reasons)
**Files changed:**
**Evidence directories:**
**Scientific claim supported:**
**What remains unproven:**
**Confounds / source mismatch:**
**Approvals required:**
**Next work item:**
```

## Owner approval checklist

Only request owner decisions when actually necessary: model/API key availability, compute-cost cap, remote trial permission, testnet wallets, change to registered hypotheses, or scope that would involve external systems. Use no real cards, wallets or mainnet even if approved.

## Quality bar

A work order is finished when rerunning its documented command from a clean environment produces the expected artifact and the independent test validates it. A plausible README or code snippet is not completion. No periodic job/scheduled follow-up should be created without the owner's explicit request.
