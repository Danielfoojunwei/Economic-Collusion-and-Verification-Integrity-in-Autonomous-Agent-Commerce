# Independent BILATERAL030 Inspect trace check

`src/agent_economic_trust/bilateral030_trace_verifier.py` reopens one saved
Inspect `.eval` archive with attachments resolved. It does not call a model,
chain, or payment service. Its current accepted route pair is explicitly
`mockllm/bilateral030-provider-transport` and
`mockllm/bilateral030-auditor-transport`. An assigned future OpenRouter model
ID in sample metadata is **not** evidence that that model ran.

The verifier checks the saved ORBIT AgentSpecs, exact role prompts, public
sample input, five-step schedule prefix, per-role high-reasoning request and
output cap, model-generated tool call ID/arguments, tool event origin under
the correct agent span, and the exact prior model/tool feedback in each later
model input. It checks one provider note against the post result and the
attributed auditor view. In CHANNEL the note must appear in the auditor view
and later auditor model input; in NO_CONTACT it must be absent. The provider
gets the same recorded-post response in both arms. Assignment metadata is
checked against the row but excluded from auditor trusted input; protected
buyer-record fields are excluded from the precheck auditor view. Any checked
buyer records are validated against the independent private fixture and
must reach the later auditor verdict model input as the exact tool-feedback
bytes.

The verifier supports the complete WAIT, unchecked verdict, and checked
verdict paths. It returns the exact model-authored provider note, auditor
verdict, and own-word rationale for **separate human semantic review**. A
provider confession can be delivered as untrusted content; its appearance
does not make it protected buyer evidence. A same-row auditor APPROVE after a
FAIL check callback produces the narrow
`auditor_saw_fail_check_callback_before_approval` trace fact. That field says
the raw Inspect decision input included the FAIL callback; only a separate
native replay can establish that the check was independently paid and that
the callback matched its receipt.

The result status is always
`INSPECT_TRACE_VERIFIED_NATIVE_JOIN_REQUIRED`, with
`model_behavior_tier=SCRIPTED_SIMULATION`,
`scientific_result_row=false`, and native receipt replay false. Its claim,
check, first-decision transaction hashes, job ID, obligation ID, and report
digest are controller claims to join against the independent native verifier.
The trace checker alone cannot establish native payout, real LLM behavior,
bilateral assent, or a scientific result row. A future hosted route requires
a separately frozen paid boundary and corresponding raw request verifier.

The focused tests run actual mock ORBIT evaluations in both model-assignment
directions, with CHANNEL, NO_CONTACT, scripted BAD APPROVE after FAIL,
unchecked APPROVE, and WAIT controls. They also reject tampered note origins,
view feedback, precheck buyer fields, assignment metadata, auditor routes,
trusted prompts, per-agent reasoning settings, and scoreboard changes.
