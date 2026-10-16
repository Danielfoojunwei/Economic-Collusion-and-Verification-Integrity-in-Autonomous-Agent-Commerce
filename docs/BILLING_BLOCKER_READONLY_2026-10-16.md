# OpenRouter billing blocker — read-only review, 2026-10-16

**Ledger state:** canonical `artifacts/budget/openrouter-ledger.jsonl` sequence 226
holds USD **39.903074** across seven runs under the owner's USD 50 lifetime cap;
available headroom is **USD 0**. Held amounts are worst-case reservations, not
provider charges. The previously settled USD 10.096926 is project usage-based
accounting, not a per-request provider invoice. This review made no model or
payment calls, changed no ledger event or hold, and made one read-only OpenRouter
analytics metadata request.

All times below are **2026-10-15 UTC**. For the six Inspect-backed rows, the
window is the first-to-last archived sample event, rounded outward to whole
seconds. It identifies a provider-search interval, not the exact billable
request time. The MPP012 interval is the incident's retained outer time bound.

| Held run | Search interval UTC | Status | Held USD | Billing limitation |
| --- | --- | --- | ---: | --- |
| MPP006 stopped Sol request | 13:57:23–13:57:26 | CONTINGENT | 6.307840 | HTTP 400, no generation ID; absence from owner session export does not prove final zero charge. |
| FEE011 hold for FEE010 stopped request | 17:03:34–17:04:01 | RESERVED | 3.379164 | The saved sample has no provider generation IDs or final failed-request charge. |
| x402011 stopped row | 17:21:26–17:21:51 | CONTINGENT | 4.407296 | Six saved model events have no provider generation IDs or individual charges. |
| FEE014 stopped row | 20:14:53–20:15:14 | CONTINGENT | 4.292608 | Five saved model events have no provider generation IDs or final failed-request charge. |
| XHIGH017 stopped row | 21:41:31–21:41:39 | CONTINGENT | 4.718592 | One saved model event has no provider generation ID or final charge. |
| PRESSURE016 stopped row | 22:09:14–22:09:34 | CONTINGENT | 3.981312 | Eight saved model events have no provider generation IDs or individual charges. |
| MPP012 unguarded source test | 22:17:20–22:19:21 | UNKNOWN | 12.816262 | Seven to eight model activations are inferred, but the raw Inspect log was deleted by test cleanup; no request IDs or exact model usage survive. |

The six saved Inspect archives contain no `gen-` billing IDs in model-output
metadata. OpenRouter's public OpenAPI describes `GET /api/v1/generation?id=…`
for individual request and usage metadata, but requires a generation ID and
offers no generation-list endpoint. Its `/api/v1/analytics/meta` and
`/api/v1/analytics/query` endpoints require a management key. The existing
project key returned **HTTP 403**, `Only management keys can access analytics`,
on the read-only metadata request; sanitized response SHA-256:
`9d663cf212d4a816176529ea95ea3c18a4761f2ac62b2f7dd55ba6ae860140a1`.
`/api/v1/activity` also requires a management key and groups activity by
endpoint; it is not an individual request invoice.

The latest owner-supplied model/hour request-count and usage CSVs contain only
**05:00–13:00 UTC** rows. Their SHA-256 digests are respectively
`f1e30259ab4c3a22576ee79906fc7d61ffff4708f689d6b6b2a9b3620d576372`
and `900a5135005e16e5aee31eb2d6f0cd96da714e6ddba47cca898323310377fdc3`.
They omit the 17:00–22:00 holds. Their hourly totals cannot attribute the
MPP006 failed call either.

**Evidence needed to close a hold:** an owner export of individual OpenRouter
requests/generations for the project key across the listed intervals, with
generation/request ID, UTC time, model, success/error status, and final USD
charge, including an explicit record or provider confirmation for failed
requests with no generation ID. For MPP012, ask OpenRouter support to match the
key and 22:17:20–22:19:21 UTC interval because no local raw request archive
survives. Hash the provider evidence, independently match each record to its
run and saved model-event count, then append a separate ledger settlement under
the existing final-billing rule. Do not set a failed request to USD 0 solely
because an aggregate export lacks it. Billing reconciliation does not change
any frozen scientific outcome or turn MPP012 into a valid experiment.
