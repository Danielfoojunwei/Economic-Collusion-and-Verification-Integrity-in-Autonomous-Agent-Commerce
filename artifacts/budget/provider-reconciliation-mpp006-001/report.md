# MPP006 stopped Sol request: owner CSV cross-check

**Result: `INCONCLUSIVE_FOR_EXACT_CHARGE`.** The 2026-10-15 owner-exported OpenRouter Explore CSV contains no billing session matching the failed MPP006 Sol sample. It does contain four exact Inspect sample UUID matches for all 46 completed model requests in the 13:00 UTC hour. This is evidence that the failed call was not recorded as a billable session *in this export*. It is not evidence of a final USD 0 charge. No model call, ledger settlement, payment transaction, or reassignment occurred during this review.

| Saved run | UTC sample interval | Inspect / provider session UUID | Inspect / provider requests | Provider session USD |
| --- | --- | --- | ---: | ---: |
| OPEN006 `open006-45d3e5f5c000f353052ae159` | 13:14:45–13:15:27 | `3xFrzkfuAHpqtSCvQrqnka` | 12 / 12 | 0.064948 |
| OPEN006 `open006-c76de603251a134fba5c6868` | 13:17:06–13:17:50 | `MKyq6fZxDrNQpCvzQCnJ9C` | 12 / 12 | 0.067361 |
| OPEN006 `open006-d465a82d1e64e0b3f5eccef2` | 13:18:56–13:20:00 | `6pLhG9jQ5Xjwg6D6KzSpcU` | 12 / 12 | 0.074036 |
| MPP006 `mpp006-dcf4a781b0982260ecfe3012` | 13:53:42–13:54:10 | `8Dq8JKJXXk2wPFiQwgKDvu` | 10 / 10 | 0.063154 |
| **Matched 13:00 UTC hour** | | **4 of 4 CSV sessions** | **46 / 46** | **0.269499** |

The stopped MPP006 `mpp006-bc092a2baae1584874c4f308` sample started **13:57:23 UTC** and has UUID `aqKLUoK75wehRUqhXaE288`. It attempted one provider call, returned HTTP 400 `invalid_function_parameters`, has empty Inspect model usage, and is absent from all 16 exported provider session rows. The original [`STOPPED.json`](../../gates/MPP006/runs-mixed-001/episodes/mpp006-bc092a2baae1584874c4f308/STOPPED.json) and frozen eight-row collection remain unchanged: one completed row, one stopped row, six pending rows.

The copied, byte-identical [`usage_by_session_hourly.csv`](usage_by_session_hourly.csv) has SHA-256 `29481fb76fd22888d810ea58d9bc42ce624bc935e842b54ea2030f28c158ff39`. Its 16 rows sum to **USD 2.187010** after six-decimal rounding. A separate sanitized, read-only [key-usage observation](account_usage_readonly.json) at **14:32:55–14:32:56 UTC** reports **USD 2.1870442**, which is **USD 0.0000342 higher** than the CSV total. The raw response was not stored; its SHA-256 is in that JSON. The key-level figure has no request ID and cannot assign that difference to the failed call, another request, or accounting delay.

The CSV is user-supplied and unsigned. It groups usage by hour and session, contains no failed-request register or per-request charge, and does not establish when all possible delayed charges have posted. Session/count matching is strong for the four completed runs; the absent stopped session and small aggregate difference leave the exact failed-call charge unresolved. The earlier W11 reconciliation had an exact stopped-session UUID with a provider-reported session amount; this record does not. Do not record USD 0 or the USD 0.269499 hour total as the stopped call's actual invoice cost. A conservative budget upper bound would need separate accounting semantics and a stated time/completeness assumption. The shared USD 50 ledger remains at sequence 132, `UNKNOWN`, with USD 6.307840 reserved and new paid work blocked.

## Reproduction and integrity

Run from the repository root with the pinned Inspect environment:

```bash
/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_mpp006_provider_export.py
```

The read-only verifier reopens each saved Inspect log, checks the exact UUID, UTC hour, and model-event count against the copied CSV, proves that all four 13:00 UTC CSV sessions are accounted for, confirms the stopped sample remains `UNKNOWN` and absent, and recomputes the CSV/account difference. Its saved output is [`evidence.json`](evidence.json). The original ledger copy in this checkout had SHA-256 `e5067415a2abfd589cfa9c3073e8dedcc0cbc25ce2af4635978fea7c3486b440` and anchor SHA-256 `c77675a2510594e4c9eac42becd5abc6c01e135cfad2f313e39969f0aa1067b7` at review. The verifier does not write to either.

Next billing evidence: a fresh OpenRouter Activity export for the same key showing **13:00–14:00 UTC Sol model-hour spend and request count**, plus request/session identifiers, statuses, and per-request spend if the UI provides them. Provider confirmation of whether the specific 13:57 UTC HTTP 400 request was charged would also resolve attribution. Keep the original stopped research row in its frozen denominator regardless of reconciliation.
