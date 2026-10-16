# Independent reaudit: MPP neutral text replication v2

**GO for freezing a prospective assignment and starting the one-shot live text run under the stated execution gates.** This decision applies only to the seven source/test files at the SHA-256 values below. It supersedes the [earlier NO-GO](MPP_NEUTRAL_REPLICATION_INDEPENDENT_CODE_AUDIT_2026-10-16.md) for executor `030cd2ee…`; it is not evidence of live model behavior, a native MPP payment, or a final billing clearance. I made no external model call, native transaction, or assignment freeze in this audit.

| Reviewed file | SHA-256 |
| --- | --- |
| `src/agent_economic_trust/free_collusion_probe.py` | `45b10b24d6bfdcd86eecb39e8c16d420b39477625363ce0a5fa02cd775262b11` |
| `src/agent_economic_trust/free_mpp_neutral_probe.py` | `2c41a10f07d60f10fc8b4906cff407901b0795f3ef99593ad0b3a138ef26c44c` |
| `src/agent_economic_trust/mpp_neutral_replication_plan.py` | `b40c03dcc1ba6bb443ef3795e7ad8c9c6284f1da3c87dd9687bd7acc000417d6` |
| `src/agent_economic_trust/mpp_neutral_replication_execute.py` | `2c15bfba1c00375a1bb8f95913c379791aa54387640c8925eb77d4269e65a319` |
| `scripts/run_mpp_neutral_replication.py` | `921bd0e2fa117bf70fa0434aa8473833a2be7c6a7c2ed303df3557c818bf456b` |
| `tests/test_mpp_neutral_replication_plan.py` | `dc4d653ba72d5ffadaaa33e1de81d47cc0661346fcba9d277c678eda41e15d21` |
| `tests/test_mpp_neutral_replication_execute.py` | `da70f825c0adb12ece1156f25ec99e6d1536d8f2257a9bc9334370ba55a9425e` |

## Offline evidence

I matched all seven local SHA-256 values to the [v2 source seal](MPP_NEUTRAL_REPLICATION_SOURCE_SEAL_2026-10-16.md). The plan and runner use 240 unique assignments in randomized order: 30 BAD and 30 GOOD for each of the four contact × bonus arms. The network-free dry run reported those counts, the fixed `:free` provider/auditor routes, 8,192 output tokens, high reasoning requested, and zero calls/transactions. The focused plan and executor unit suite passed **17/17**; `git diff --check` passed.

I independently repeated the two former attacks in temporary output directories. Starting from a scripted all-complete run, I relabeled an actual BAD `SKIP/ACCEPT` as `INCOMPLETE`, then separately a last BAD `SKIP/ACCEPT` as `STOPPED`; in each case I removed the classification and recomputed all affected row, index, terminal, and chain hashes. The revised `verify_run` rejected both with `replication row status differs from saved decision state`. Its `_replay_terminal` now derives terminal state from saved responses on **every** indexed row, and `_verify_check_record` binds the purchased-check continuation to its request and fixture even for missing rows.

I checked legitimate terminal states against runner-produced artifacts too. A zero-cost `finish_reason=length` response yielded one `INCOMPLETE` and a valid `COMPLETE_WITH_MISSING` terminal. A positive response cost stopped at one indexed row with 239 unattempted assignments; the verifier accepted that genuine `STOPPED` record. Whitespace-only provider text with `finish_reason=stop` produced 240 verified `INCOMPLETE` rows, including all 120 contact rows. Forced catalog failures after one usable provider call, and after usable provider plus auditor initial calls, each produced a verified `STOPPED` row with two and three saved call records respectively. These checks matter because rejecting fabricated missing rows alone would not show that normal missing and stopped paths remain replayable.

## Source controls and scope

The exact request contains `max_tokens=8192`, `reasoning={"effort":"high"}`, no route fallback, and zero maximum price for prompt/completion/request. A fresh catalog cap and zero-price proof precedes each POST. Saved responses must have the exact route, a usable choice/finish, numeric zero reported cost, and stable immediate account usage to score; API error markers, unknown cost/route/finish, failed account checks, and catalog failures stop globally. Incomplete text is permitted only after a zero-cost route/account proof. The auditor initial request carries no private BAD/GOOD fixture truth; provider text reaches it only in contact arms. The scripted check result appears only in the purchased-check continuation. Requests, assignments, source pins, row files, index links, terminal counts, and decision classifications are replayed from the saved evidence. Output creation is exclusive and there is no automatic retry/resume path in the CLI.

This is a **source-readiness** GO. The high reasoning setting is a request, not proof of a model's internal effort. OpenRouter's immediate zero cost/account checks cannot exclude delayed billing. A successful response body `id` is retained but is not independently validated as a generation ID. The local hash chain detects accidental alteration and inconsistent relabeling; it is not an external signature against replacement of an entire archive. A different new output directory could reuse the seed if an operator chose to do so, so retain the one-shot execution record. The catalog accepts either advertised `reasoning` or `reasoning_effort` support although the actual request uses the nested `reasoning` form. These limits do not overturn the offline GO but should be carried into outcome and cost interpretation. This replication is text-only and cannot establish a native MPP payment effect.
