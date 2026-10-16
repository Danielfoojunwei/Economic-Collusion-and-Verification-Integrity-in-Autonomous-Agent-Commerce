# START HERE — hand this directory to Codex

## One-paragraph instruction

We are changing research direction. We are **not** creating another benchmark from scratch. Conduct a novel, testable study of whether financially dependent autonomous agents change their *verification effort and verdicts* when evaluating another agent's paid work, and whether payment workflows translate those verdicts into improper settlement. Reuse ORBIT/Inspect for agent orchestration, Colosseum for appropriately adapted coordination metrics, and real locally deployable payment SDKs/contracts. Preserve the previous PaidAuditBench v0.2 simulator as archival provenance and unit-level fixtures; reuse code selectively via thin adapters only. Build the smallest runnable experiment, not a platform.

## Immediate action checklist

- [ ] Read `AGENTS.md`, `CODEX_MASTER_PROMPT.md`, `docs/04_RESEARCH_QUESTIONS.md`, `docs/05_SYSTEM_AND_THREAT_MODEL.md`, and `planning/FIRST_48_HOURS.md`.
- [ ] Verify local legacy test baseline unchanged and record output in `artifacts/gates/G0/`.
- [ ] Verify upstream ORBIT release instructions (`pip install orbit` is **not** the official installation path), clone at a pinned git commit/release, and inspect API.
- [ ] Clone Colosseum at a pinned commit; reuse **methods** before touching its runtime code.
- [ ] Implement one ORBIT/Inspect objective task, worker/auditor role isolation, and an independent evaluation event record.
- [ ] Prove with a test that hidden task truth is never passed to the auditor's prompt or tools before authorized verification.
- [ ] Produce structured gate report with PASS/FAIL/SKIP and reasons.
- [ ] Stop before paid remote model or nonlocal-chain operations unless separately authorised and budgeted.

## The very first experiment

One objectively-checkable coding or reconciliation task. Run 2 real agent-model sessions in a locally sandboxed ORBIT task (one worker, one auditor) against a known-good artifact and an intentionally defective artifact. Provide the auditor a feasible priced verification tool. Obtain its actual check/skip action and verdict. Record what the *local* payment stub would do, **without** treating that payment stub as real ERC-8183 or x402. Negative control: frozen scripted always-accept and always-reject decisions. A correct result is a reproduced event trace, not a desired collusion rate.

## Stop / escalation

If the official ORBIT release, actual API, or necessary sandbox dependency cannot be fetched, document the exact failure and deliver a thin Inspect-only fallback *that preserves ORBIT integration compatibility*; do not claim ORBIT integration succeeded. Similarly, if a native payment SDK needs credentials, never fake credentials and call the result native—mark SKIP and continue the local branch. See `planning/STAGE_GATES.md`.

## Send Codex this exact prompt

Open `CODEX_MASTER_PROMPT.md`, copy its contents, and attach the complete ZIP. The `AGENTS.md` file applies to the extracted workspace automatically in compatible Codex workflows. No new research framework should be scaffolded unless an acceptance test proves a missing function that cannot be achieved through existing frameworks.
