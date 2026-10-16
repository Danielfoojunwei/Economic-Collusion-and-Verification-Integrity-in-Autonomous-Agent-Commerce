# Package manifest and provenance

This is a **handover and executable-work-order package**, not a claim that new research experiments have run.

### Core deliverables

- `CODEX_MASTER_PROMPT.md`: complete Codex implementation assignment.
- `AGENTS.md`: enforceable engineering and research constraints.
- `README.md`, `START_HERE.md`: orientation and initial commands.
- `docs/01_...18_...md`: research framing, paper, novelty exclusions, hypotheses, threat model, tasks, protocol-native requirements, analyses, ethics, source links, and compatibility caveats.
- `planning/`: complete ordered implementation plan, first-48-hours tasks, test matrix and stage gates.
- `schemas/`, `configs/`: templates to translate into pinned ORBIT and runtime contracts; explicitly **not native runnable ORBIT configs**.
- `legacy/paid-audit-bench-v0.2-source/`: preserved old simulator and 41-test suite.
- `legacy/results-summary/`: earlier offline simulation summaries and manifests.
- `legacy/raw-results/PaidAuditBench_v0.2_results_full.zip`: full earlier synthetic JSONL trial archive (large; deliberately remains compressed).
- `inputs/From chat collusion to bribes.pdf`: user's original preliminary paper source, unchanged.

### Validation performed at packaging

A fresh run of legacy source tests found 41 passing tests and an eight-trial smoke manifest with verified local trace digests. x402/MPP wire smoke passed for **mock** 402/replay and altered amount, not authentic payment signatures. Logs in `validation/legacy_tests_stdout.txt` and `validation/legacy_wire_smoke.txt`.

`MANIFEST.json` and `SHA256SUMS.txt` bind the packaged files to a reproducible byte-level inventory; `scripts/validate_handover.py` verifies the inventory and old raw trace ZIP integrity.

### Exact scientific status

- Native ORBIT integration: **not in this ZIP** (new Codex work).
- Official native ERC-8183, x402, MPP, AP2, ACP integrations: **not yet run**.
- Authenticated financial bribe experiment with real LLM: **not yet run**.
- Any new result of emergent financial collusion: **not established**.
- Prior scripted study: present solely as archival and instrument-validation evidence.
