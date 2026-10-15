# What the high-reasoning setting measured

The independent raw-Inspect audit of completed MPP011 and x402 LIVE012 found
66 successful OpenRouter calls: 33 GPT-5.6 Sol provider calls and 33 Claude
Sonnet 5.5 auditor calls. Every saved call requested `reasoning_effort=high`
with `max_tokens=4096` and no model retry. The pinned Inspect OpenRouter
adapter maps that setting to OpenRouter's `reasoning.effort=high`. Both models'
public catalog entries list reasoning effort as supported.

| Role and route | Completed calls | Reported reasoning tokens | Calls reporting zero |
| --- | ---: | ---: | ---: |
| Provider, `openai/gpt-5.6-sol` | 33 | 3,207 | 6 |
| Auditor, `anthropic/claude-sonnet-5.5` | 33 | 615 | 21 |

The x402 block alone accounts for 26 calls and just 34 reported Sonnet
reasoning tokens across 13 auditor calls. OpenRouter currently marks Sonnet's
reasoning as mandatory, so zero reported tokens do **not** establish zero
private computation. Saved Inspect outputs and usage are an incomplete proxy
for internal thought. The low model-use estimates also are not attributable
provider invoices.

OpenRouter's public catalog lists `xhigh` for both routes, and the pinned
adapter passes it as `reasoning.effort=xhigh`. That raises an allowed effort
ceiling within the same `max_tokens`; it does not guarantee longer reasoning,
unsafe behavior, or a collusive choice. A later effort comparison needs a new
assignment, fixed tasks/roles, a predeclared high versus xhigh contrast, and
the same ledger and receipt checks. The frozen high-reasoning rows remain
unaltered. Report returned reasoning tokens and content separately from the
requested setting in any successor study.
