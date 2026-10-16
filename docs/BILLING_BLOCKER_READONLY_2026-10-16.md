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

A further owner-supplied [session/hour usage export](../artifacts/billing/openrouter-session-usage-2026-10-15-13h-followup.csv)
(SHA-256 `01cbaf4b1c030c6f790a433eba0f7a37ac7a49eea4bdd24902fc16efd2c3fb46`)
also ends at 13:00 UTC. Its four named 13:00 sessions and USD 0.269499 total
match the prior [MPP006 session reconciliation](../artifacts/budget/provider-reconciliation-mpp006-001/report.md):
all 46 recorded requests belong to completed runs. The stopped 13:57 MPP006
sample has no matching session in this export. Absence from a grouped export
does not establish its final charge. The new export has no 17:00–22:00 rows,
so none of the seven holds can be settled from it; the ledger is unchanged.
Another owner-supplied [session/hour export](../artifacts/billing/openrouter-session-usage-2026-10-15-15h-followup.csv)
(SHA-256 `08037a0c397f3e3e69b3e40359e9978da86d38c43d4770bed3dd30b1cc972fe9`)
extends coverage through 15:00 UTC, with six named sessions at 15:00.
Its named 13:00 sessions are the same completed runs already matched above;
the 13:57 stopped sample remains unattributed. It has no 17:00–22:00 rows
and changes no hold or scientific outcome.
If OpenRouter Explore is still set to the GMT+8 timezone shown in the owner's
dashboard screenshot, the six later UTC intervals appear on **October 16,
01:03–06:19 GMT+8**. An export ending on October 15 local time will miss them;
include October 16 when exporting. This timezone conversion does not replace
the request-level billing evidence needed for settlement.

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

## Read-only follow-up at 2026-10-16 10:33:54 UTC

An authenticated `GET https://openrouter.ai/api/v1/key` with the currently
injected key returned HTTP 200 and reported `data.usage=4.0299155`,
`data.usage_daily=0`, `data.usage_weekly=4.0299155`,
`data.usage_monthly=4.0299155`, `data.limit=250`, and
`data.limit_remaining=245.9700845` (USD as represented by this API).
This is the same `usage` value recorded around the recent zero-price studies.
The provider's per-key limit is **not** the owner's USD 50 lifetime project
authorization. This aggregate key counter cannot allocate charges to the seven
historical held runs, establish final cost for a failed request, or show that
the current key was the only key used in the project. It releases no hold.

An independent local search decompressed all 459 archived Inspect `.eval`
files and found no `gen-...` identifier in any member. A separate scan of
non-exploratory raw artifacts found no paid-run generation ID; its only
`gen-...` matches were in a review file for a newer free-model study. The
current free-model row JSON files do contain generation IDs, but they cannot
identify the earlier paid calls. Because the held requests lack IDs,
`GET /api/v1/generation?id=...` cannot reconcile them. The previous HTTP 403
from management-only analytics still applies; no further analytics request was
made. No POST, model call, ledger change, or paid charge was made in this
follow-up. The USD 50 ledger therefore retains USD 0 positive-price headroom.
