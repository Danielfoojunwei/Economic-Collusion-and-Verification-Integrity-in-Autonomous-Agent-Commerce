# MPP006 stopped Sol request: conditional billing reconciliation

**Finding:** The OpenRouter **model-inference charge** for the stopped MPP006 Sol request is **inferred to be USD 0 as of the owner exports and the 14:32:56 UTC key-usage observation**, subject to the conditions below. There is **no per-request invoice or proven final total charge**. The USD 0.0000342 key/export residual is unassigned. The archived budget ledger is unchanged at sequence 132: the request is `UNKNOWN`, USD 6.307840 remains reserved as contingent cap exposure, and new paid requests remain blocked. No model or payment call was made for this reconciliation.

The [earlier provider-export cross-check](../report.md) remains valid and labels the *exact invoiced charge* inconclusive. This sidecar adds the saved request's public pricing and OpenRouter's published error billing policy to give a narrower, conditional inference. It does not reclassify the frozen experimental row. The [collection](../../../gates/MPP006/collection-mixed-001-after-first-stop.json) remains 1 complete, 1 stopped, 6 pending, including the stopped BAD Sol/Sol row in its original assigned denominator.

## Reconciled evidence

| Evidence | Observation | Billing meaning |
| --- | --- | --- |
| [Owner session export](../usage_by_session_hourly.csv), [model request counts](../request_count_by_model_hour.csv), [model spend](../usage_by_model_hour.csv) | At 13:00–14:00 UTC on 2026-10-15, 36 GPT-5.6 Sol requests cost USD 0.206345 and 10 Claude Sonnet 5.5 requests cost USD 0.063154. All 46 recorded requests match four completed Inspect sessions. The stopped request's `aqKLUoK75wehRUqhXaE288` session is absent. | No recorded billable session for the stopped sample in these unsigned, aggregated exports. They do not list failed requests or individual invoices. |
| [Archived Inspect error](../../../gates/MPP006/runs-mixed-001/episodes/mpp006-bc092a2baae1584874c4f308/inspect.eval) and [STOPPED](../../../gates/MPP006/runs-mixed-001/episodes/mpp006-bc092a2baae1584874c4f308/STOPPED.json) | One provider call attempted at 13:57:23 UTC, HTTP 400 `invalid_function_parameters` on `market_propose` schema before any saved assistant response. Inspect model usage is empty; no check, verdict, or paid episode followed. The serialized model request offers only four local market tools, with no OpenRouter web search, file parsing, or fetch service. | Supports a zero-completion, non-auxiliary request. Inspect cannot certify OpenRouter's private token counter or final charge. |
| [Frozen assignment pricing](../../../gates/MPP006/assignment-mixed-001/assignment_manifest.json) | Public `openai/gpt-5.6-sol` catalog snapshot fetched 13:51:12 UTC lists `request_usd: "0"` (catalog model hash `71e95fa7cf157390232d6e13a44bf61ea6b9b6a7961ced6c8f37a684b51b499a`; assignment manifest SHA-256 `0e11d0595056d5d43037a666be1767c3ddc394b2a7914d4ab9cb7e3a97362d9f`). | The published flat per-request price is zero. **It is not a receipt for this specific request and does not by itself waive token charges.** |
| OpenRouter [Errors and Debugging](https://openrouter.ai/docs/api_reference/errors-and-debugging) and [Zero Completion Insurance](https://openrouter.ai/docs/guides/features/zero-completion-insurance) | Official pages returned HTTP 200 at 14:45 UTC; exact page bytes and hashes are archived as gzip files here. The former describes pre-stream HTTP errors. The latter says zero-output responses with blank finish reason or error, and responses with error finish reason, have no *user* model-token charge. It excludes auxiliary services that already ran. | The published policy points to USD 0 user charge **if** it applies to this schema failure; an upstream provider could still have incurred prompt cost. |
| [Activity Export](https://openrouter.ai/docs/cookbook/administration/activity-export) and [read-only key observation](../account_usage_readonly.json) | The official export documentation calls these aggregated reports. The later key total is USD 2.1870442 versus USD 2.187010 summed from the rounded session CSV, a **USD 0.0000342 residual**. | The residual has no request ID. It cannot be assigned to this failure or used as a charge estimate. |

The model-charge inference holds only if the uploaded exports cover this key and hour without an omitted billable session and OpenRouter's zero-completion policy applies to this exact HTTP 400. A **USD 0 final total** additionally requires no delayed or auxiliary charge for the request. The matched request counts, saved error, and lack of web/file services support those conditions; none is independently proven by a per-request invoice. The error response has no `gen-` billing ID in the saved log. The [conditional evidence JSON](evidence.json) therefore records `actual_final_total_failed_request_usd: null` separately from `conditional_model_inference_charge_usd: "0"`.

The official source pages were fetched with HTTP 200 and archived byte for byte in compressed form. Their original page SHA-256 values are: Errors and Debugging `0fba9ed243296de460a5800d8717d394cd854577068be5588cb3055dd264f1e0`, Zero Completion Insurance `9e8a4e965717deb6de80899d030b82943ef91381184f7cf9cbf270626d67c137`, and Activity Export `2a39f416b8b69ee018b34032df17258567e0a22bcf784d6653a8a82e1b5af9a5`. See [source metadata](official-docs.json) for UTC GET times, URLs, archive hashes, and sizes.

## Budget decision for independent review

The original [prestate ledger](prestate-openrouter-ledger.jsonl) SHA-256 is `e5067415a2abfd589cfa9c3073e8dedcc0cbc25ce2af4635978fea7c3486b440`; its [anchor](prestate-openrouter-ledger.jsonl.anchor) SHA-256 is `c77675a2510594e4c9eac42becd5abc6c01e135cfad2f313e39969f0aa1067b7`. It validates at sequence 132 with USD 50 cap, USD 5.313220 settled, and USD 6.307840 reserved for `mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308`. The full reserved sum remains contingent exposure until an actual ledger settlement; it is not observed spend. Original `STOPPED.json` and collection SHA-256 are pinned by the verifier and must remain unchanged after any billing reconciliation.

An independent reviewer can accept or reject the conditional **USD 0 final-total assumption**, including the absence of delayed or auxiliary charges. **Only if accepted**, recheck the current key activity and ledger first, then a prospective post-hoc ledger operation would be:

```python
from agent_economic_trust.remote_budget import BudgetLedger

BudgetLedger("artifacts/budget/openrouter-ledger.jsonl").settle(
    run_id="mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308",
    actual_usd="0",
    evidence_ref="sha256:1b06d264b6a60bdfcff4e4a6de5bfe26c0fdf6e3d5aa61483b45cf4d5ddc8fc3",
)
```

That `evidence_ref` is the SHA-256 of the immutable [conditional evidence JSON](evidence.json). It labels a **conditional as-of-export accounting resolution**, not a provider invoice. If a later attributable charge appears, record it in a new forensic sidecar and reconcile the ledger explicitly; never edit the frozen experimental row or pretend the original stop was a completed trial. If the reviewer needs an exact invoice instead, retain `UNKNOWN` and the USD 6.307840 hold.

## Reproduction

```bash
/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_mpp006_conditional_zero.py
PYTHONPATH=src:scripts /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_mpp006_conditional_zero -v
```

The verifier is offline and read-only. It rechecks all three owner CSVs against 46 saved model events, the absent failed session, pinned raw Inspect error and frozen statuses, public pricing, archived OpenRouter documentation, the key aggregate residual, and the copied hash-chain ledger and anchor. It prints the [saved result](evidence.json) without writing the ledger or calling a model. The positive and tamper tests pass (3/3). The three original owner files are SHA-256 `29481fb76fd22888d810ea58d9bc42ce624bc935e842b54ea2030f28c158ff39`, `f1e30259ab4c3a22576ee79906fc7d61ffff4708f689d6b6b2a9b3620d576372`, and `900a5135005e16e5aee31eb2d6f0cd96da714e6ddba47cca898323310377fdc3`, respectively.
