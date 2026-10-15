# W11 stopped session: provider export reconciliation

Result: **matched provider session; ledger unchanged**. The user-supplied OpenRouter Explore export reports **USD 0.037002** total usage for one session with eight requests. This is a settlement candidate for independent review, not a ledger settlement or a completed W11 round.

- Provider session ID and Inspect sample UUID: `X3NZV22BrmsPPw3eFEjYkb`.
- Model: `GPT-5.6 Sol` in the provider hour table, `openrouter/openai/gpt-5.6-sol` in the saved log (`openai/gpt-5.6-sol` underlying).
- Provider group: 2026-10-15 07:00:00 UTC, eight requests, USD 0.037002. Saved sample: 2026-10-15T07:25:09.446930+00:00 to 2026-10-15T07:25:29.072357+00:00, 8 model events.
- Both hourly CSVs agree on request counts; the provider session usage sums to each model-hour usage total within CSV floating-point precision.
- Original STOPPED SHA-256 `556b933b2eadd6dbafe41a4bbb089516533b02df796e4d9d027663f50b3da1ae`; Inspect SHA-256 `aa3f66f10f4f9a1165f9990687a7f52963d6c855dc340160aa06dab59efb04cb`; assignment SHA-256 `ae037b6df7b0e0130578c6f6f7fe210a23690ad653ee54d0877315173ee9f0d9`; archived frozen runner SHA-256 `294e50ddfc3628ba00f9405215ddbe06d45611d4cd95af7294f5d01ceffb2214`.
- Fresh, read-only structural forensic preflight SHA-256 `3e24e1cef1665d3de61e12fb5ec967c4ad3a7dc91b7f84a062dae28a144b8643`: eight calls, UNKNOWN reservation, native job OPEN, zero ledger/native mutations.
- Frozen copy of the original hash-chained ledger head `6c7220cbf39b8a433645868f70ce175526d4a762e4edc6e5d0e77e8807f40f44` (seq 88): UNKNOWN, USD 4.25984 reserved, blocked. The ledger copy SHA-256 is `9edd923e2ca4cfb329b326ac0f4e743df6a5db4101d0d85ff0fbe7595e55c4ed`; anchor SHA-256 is `506764391cc43ce8117268c9e4b4ade1ef2fb9e671f64d1a979342a21e4de017`. No original budget mutation was made.

CSV and blocked-ledger originals are copied byte-for-byte beside this report. CSV SHA-256 values are in `evidence.json`; run `/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_w11_provider_reconciliation.py --verify-only` to reproduce the checks without writing an artifact.

**Limits:** The CSVs are a user-supplied, unsigned provider export and show only a session total, not eight request-level charges. The exact Inspect UUID, eight-call count, matching model and hour, original archive hash, and independent hourly totals support attributing the USD 0.037002 to this stopped session. The W11 experimental assignment remains incomplete.
