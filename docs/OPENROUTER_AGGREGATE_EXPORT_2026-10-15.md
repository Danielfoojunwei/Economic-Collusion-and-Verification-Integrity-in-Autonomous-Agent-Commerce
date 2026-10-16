# OpenRouter aggregate export review — 2026-10-15

The owner supplied two OpenRouter Explorer CSV exports, retained byte-for-byte at
[`artifacts/billing/openrouter-request-count-2026-10-15-13h.csv`](../artifacts/billing/openrouter-request-count-2026-10-15-13h.csv)
and [`artifacts/billing/openrouter-total-usage-2026-10-15-13h.csv`](../artifacts/billing/openrouter-total-usage-2026-10-15-13h.csv).
The request-count file has SHA-256
`f1e30259ab4c3a22576ee79906fc7d61ffff4708f689d6b6b2a9b3620d576372`;
the usage file has SHA-256
`900a5135005e16e5aee31eb2d6f0cd96da714e6ddba47cca898323310377fdc3`.

The rows cover October 15 hours 05:00 through 13:00 UTC. They sum to **423
requests** and **2.187010 in the export's `total_usage` field**: 413 GPT-5.6 Sol
requests and 10 Claude Sonnet 5.5 requests. These are hourly model aggregates.
The files have no request or run ID, per-call charge, exact call time, or billing
line-item identifier. The 07:00 Sol row alone combines 44 requests and 0.215055
usage, so it cannot attribute a charge to the eight MPP006 calls near 07:25.
The export stops before MPP009's seven calls around 16:20.

The shared ledger therefore retains MPP006's full USD 6.307840 `CONTINGENT`
hold; this aggregate export does not justify settling or releasing it. The
ledger's `SETTLED` model amounts are its bounded usage estimates unless a
specific provider bill is independently linked to the run. None of these
aggregates are evidence of collusion or of a model's verdict.
