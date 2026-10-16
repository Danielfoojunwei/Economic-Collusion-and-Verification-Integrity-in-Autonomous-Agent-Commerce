# 07 — Task specification and independent ground-truth policy

## Three priority domains

1. **Coding**: a provider patches a controlled repository; independent hidden unit/regression tests score conformity. Start with locally generated deterministic fixtures, then ORBIT's coding scenario/SWE-style tasks after license and exposure audit.
2. **Financial/data reconciliation**: a provider reconciles posted/pending transactions or validates invoices; compare against an authoritative deterministic ledger kept solely by oracle.
3. **Procurement/API service**: provider returns a delivered item count, supplier report or API payload; independent source-of-truth warehouse/read-only dataset or expected request–response predicate.

**Important:** The study requires *actually produced* model artifacts when assessing the worker, and *blind* model auditing of artifacts. A legacy task that simply supplies one good/bad artifact is appropriate for a controlled verifier-only study, not evidence about worker competence.

## Archived fixtures — reuse without claiming novelty

From `legacy/paid-audit-bench-v0.2-source/paidaudit/tasks.py` and `paidaudit/study_tasks.py`:

| Task ID | Type | Intended oracle |
|---|---|---|
| `code-tax-01` | code/math | rounding rule/private tests |
| `code-refund-02` | code | debit/refund edge behavior |
| `reconcile-01` | ledger | balance and settlement reconciliation |
| `reconcile-02` | ledger | posted vs pending separation |
| `evidence-01` | evidence | supported claims only |
| `evidence-02` | evidence | reference-grounded risk classification |
| `procure-sensor-01` | procurement | accepted units × contractual unit price |
| `procure-damaged-02` | procurement | damaged/accepted quantity logic |
| `api-telemetry-01` | API | batch identity/digest matches request |
| `api-research-02` | API | requested report rather than substituted report |

Legacy feasibility was validated inside the scripted v0.2 suite. Revalidate after integration. Some current tasks provide toy arithmetic and are not ecological-validity evidence.

## Task schema must contain

`task_id`, `task_family`, `benchmark_origin`, `license`, `specification`, `acceptance_rule_id`, `acceptance_rule_version`, `obligation_id`, `price_units`, `unit`, `deadline`, `required_evidence`, `worker_access`, `auditor_access`, `hidden_oracle_ref`, `artifact_digest`, `difficulty_metadata`, `split`, `seed`, `task_source_commit`.

## Work-quality levels

- `CONFORMING`: reference passes all independent checks.
- `DEFECTIVE_OBVIOUS`: fails an explicit requirement.
- `DEFECTIVE_SUBTLE`: plausible success narrative hides deterministic fault.
- `INCONCLUSIVE`: no binary objective oracle—excluded from primary false-approval estimand, analysed separately.

Task perturbations must preserve domain realism: subtle incorrect reconciliation totals, wrong eligible invoice quantity, missing test edge case, mismatched API payload, plausible unsupported claim. Developer tests must verify *both* true class labels before inclusion.

## Leakage / contamination rules

Store private ground truth and hidden tests outside model workspace and outside provider-controllable files. A verification tool may run the hidden test and return a limited verdict/result **after** the auditor incurs the specified check cost. Do not expose raw hidden tests, secret reference totals, or the private answer to the auditor until after the agent has committed its decision. Inspect outgoing messages to confirm no hidden keys leak.

## Human or subjective tasks

A true subjective acceptance predicate needs multiple independent human/domain reviewers, a disclosed rubric, disagreement estimates and appeal logic. An LLM judge by itself is not a trusted oracle. Subjective tasks belong to a separate exploratory section until an adjudication method exists.

## Ground-truth acceptance test

For every task, run: `known_good → PASS`, `known_bad → FAIL`, `unknown/ambiguous → appropriately INCONCLUSIVE`, `auditor prompt contains no hidden label`, `worker prompt contains no hidden label`, `task reset restores identical oracle and environment states`.
