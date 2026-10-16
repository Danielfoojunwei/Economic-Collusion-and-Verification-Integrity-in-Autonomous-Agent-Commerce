# G0 / W00: package and legacy baseline

Status: **PASS** for A00 and A01, the package integrity and legacy baseline checks. W01 must verify and pin upstream source before G1. This report is about the archived `SCRIPTED_SIMULATION` model tier and mock local payment behavior only.

## Commands and results

Commands ran with Python 3.12.14 and `PYTHONDONTWRITEBYTECODE=1`. The package root was `/workspace/handover-staging/Agent_Economic_Trust_Codex_Handover_2026-10-15`.

| Command | Working directory | Result | Output |
| --- | --- | --- | --- |
| `python scripts/validate_handover.py` | Package root | PASS; 111 manifest files verified by SHA-256 and byte length; both schemas parse; prior results ZIP passed CRC; preliminary PDF present | `handover_selfcheck.stdout.txt`, `handover_selfcheck.stderr.txt` |
| `sha256sum -c SHA256SUMS.txt` | Package root | PASS; 111/111 entries | `sha256sums.stdout.txt`, `sha256sums.stderr.txt` |
| `python -m unittest discover -s tests -v` | `legacy/paid-audit-bench-v0.2-source/` | PASS; 41 tests, 0 failures/errors; 1.657 seconds as reported by unittest | `legacy_unittest.stdout.txt`, `legacy_unittest.stderr.txt` |
| `python -m paidaudit wire-smoke` | `legacy/paid-audit-bench-v0.2-source/` | PASS; loopback mock x402 and MPP 402/200, altered amount 403, replay 409 | `legacy_wire_smoke.stdout.txt`, `legacy_wire_smoke.stderr.txt` |

The wire exercise uses mock HMAC credentials and no money. It is **not** native x402 or MPP authorization, a real wallet flow, or LLM evidence. The unittest suite also generated eight temporary **offline simulation** trials during one test.

## File and archive provenance

All 55 manifest-listed files under `legacy/paid-audit-bench-v0.2-source/` have identical SHA-256 digests before and after execution; see `legacy_source_sha256_before.json` and `legacy_source_sha256_after.json`. No legacy source file was edited. The package has no Git commit in this extracted directory, so package provenance is limited to its internal manifest and checksums. The separately run `sha256sum` check verifies extraction against the supplied checksum list, not an external publisher signature.

The archived full-results ZIP has SHA-256 `6738ae52499039f515dc0f721cb45ba11213935d480510205ed53bcd8790677b`. Streaming its two `trials.jsonl` members found 17,280 factorial and 67,200 pilot trace rows, 84,480 total. Each member's SHA-256 and row count matched its accompanying legacy run manifest. See `archive_trace_verification.json`. These are archived scripted traces and do not measure real-model collusion.

## Runtime inventory and limitations

See `tool_inventory.json` for paths and versions. Python 3.12.14, uv 0.12.23, Node 24.19.0, Docker CLI 28.4.0, and Git 2.52.0 are available. `forge`, `anvil`, and `pytest` were not on `PATH`; Foundry is a G2 prerequisite. Docker daemon availability was not tested by this G0 work. No external model call, testnet transaction, or paid API request was made.

Upstream runtime pins and licenses have not yet been verified. The provisional `upstream_versions.json` records the handover's source links without claiming source availability. W01 is the next eligible work order. The independent checks here cover package bytes and legacy test execution; they do not validate research claims, genuine agent behavior, or native payment protocol behavior.

## Artifact inventory

- `baseline_run.json`: commands, exit codes, wall times, Python version, package manifest hashes.
- `handover_selfcheck.*.txt`, `sha256sums.*.txt`, `legacy_unittest.*.txt`, `legacy_wire_smoke.*.txt`: captured stdout and stderr.
- `legacy_source_sha256_before.json`, `legacy_source_sha256_after.json`: legacy file digests.
- `archive_trace_verification.json`: archived trace counts and digests.
- `tool_inventory.json`: available tool paths and versions.
- `upstream_versions.json`: provisional upstream inventory, pending W01 pinning.

Files changed: only new files within `artifacts/gates/G0/`; the tracked project checkout and legacy baseline were untouched.
