# W05 OpenRouter pilot — preparation

The first paid sample and the post-run numeric-evidence repair are reported
separately in `REAL_PILOT_REPORT.md`; this file records the preceding setup.

**Status:** remote runner ready for coordinated first paid sample; no model
inference has run in this preparation record. Real local model:
`SKIP_NO_LOCAL_MODEL`. Native payment: `SKIP` (mock settlement only).

## Commands and results

- `scripts/run_w05_openrouter.sh --model-id openai/gpt-5.6-sol --project-cap-usd 20 --sample-id reconcile-002 --output-dir artifacts/gates/W05/real-run-001`: dry run PASS, no inference. Public catalog exact model, high reasoning and tool capability confirmed; one-sample reservation USD 2.662400.
- `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest discover -s tests -p 'test_remote*.py' -v`: 24 PASS, 0 FAIL. Tests cover provider request shape, disabled retries, preflight, call/input/output limits, ledger tampering/truncation, concurrent reservations, unknown billing, and pricing edge cases.
- `scripts/run_w05_openrouter.sh --model-id openai/gpt-5.6-sol --project-cap-usd 20 --sample-id reconcile-002 --output-dir artifacts/gates/W05/real-run-001 --init-ledger --opening-spent-usd 0`: PASS. Project ledger initialized once at USD 20 cap, USD 0 committed, no active reservations.
- `scripts/run_g1_offline.sh --output-dir artifacts/gates/G1/scripted-run-004 --created-utc 2026-10-15T05:00:00Z`: PASS. All three policy logs have all three fixtures and pass `verify_evidence`, including manifest hashes. This later refresh covers the numeric-field scrubber fix.
- `PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`: 61 tests OK, 2 skipped across the shared tree after concurrent work completed.
- `python scripts/validate_handover.py` and `sha256sum --check SHA256SUMS.txt`: PASS, including all 111 packaged source hashes.

Only the W05 focused test result is a W05 gate assertion; the full suite also
includes other work orders that were added concurrently.

## Evidence level and limits

The final G1 scripted evidence is `artifacts/gates/G1/scripted-run-004/`;
run-002 and run-003 are labelled superseded. This preparation record predates
the first real W05 sample; the follow-up report records that sample. Native
payment protocols have not been exercised by this runner. The fixture's public
arithmetic and authored earlier submissions do not establish costly
verification behavior, worker competence, or economic collusion. Estimated
API cost is recorded distinctly from mock payment amounts.

Independent verifier for this preparation: the remote focused test suite and
G1 `verify_evidence` reopened every final scripted manifest and native log.
Next action: root agent executes one approved remote sample under the shared
budget ledger, then reviews its native log and account charge before any
additional sample.
