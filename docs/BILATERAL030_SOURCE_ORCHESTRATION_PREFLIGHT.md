# BILATERAL030 source-only block and row preflight

`bilateral030_orchestration.preflight_proposal(identity_seed, assignment_seed)`
computes a read-only proposal for the planned 30 fresh agent pairs. It derives
the exact rows from the current planner, records a SHA-256 inventory of required
local sources, a commitment to the private rows and public execution order,
the anchored project-ledger head, and the historical full-block price ceiling.
`local_source_inventory_clean` is one necessary check only; a future freeze
must also pin and review the external ORBIT, Inspect, OpenRouter SDK and official
ERC-8183 dependency versions.
The two seeds must differ. Neither seed, private treatment, nor protected buyer
truth is written to the public report. `write_preflight_report` creates a
`HOLD_SOURCE_ONLY_UNFROZEN` report once and refuses overwrite.
Future study seeds must be independently generated 256-bit random values and
kept private until the predeclared unblinding point; the deterministic strings
in unit tests are test fixtures only.

The report is **not a freeze, reservation, funding attestation, execution
permit, or model result**. It always lists all 30 rows as `PENDING` with missing
scientific outcomes. `pre_view_row_hold` applies the same hard stop to any one
planned row. A controller-supplied object saying `FUNDING_LIVE_CONFIRMED` remains
a claim and cannot open a model view. This is deliberate: the separate verifier
must replay the raw pre-view funding transcript and confirm the live local job
before its proof is trusted. The report currently records a blocked USD 50
ledger, USD 0 available, unsettled prior billing, and a historical full-block
Sol/Sonnet quote around USD 36.02. It never calls `BudgetLedger.reserve`.

## Required successor contract

Before a genuine hosted call, a reviewed successor must perform these checks
against **the actual objects passed to ORBIT and Inspect**, not only preview
metadata:

1. Commit a clean source inventory and exact private 30-row assignment,
   including distinct identity and assignment seeds, model direction, prompts,
   task, fixtures, analysis and execution order. Verify this seal again before
   each row. The analysis module's frozen-assignment schema is separate from
   this public proposal; converting a proposal to `FROZEN` by editing JSON is
   invalid.
2. Reconcile attributable prior provider billing and refresh the model catalog.
   Reserve the **entire** 30-row worst case plus margin in the anchored lifetime
   USD 50 ledger before the first hosted request. A row reservation is
   insufficient. A bounded row-local failed call retains its attributable
   charge or worst-case hold and can advance only after independent first-stop
   review; genuinely unknown or unbounded billing globally halts the block.
   Neither case permits retry or replacement of the assigned row.
3. Start a fresh local ERC-8183 job for the assigned row. Independently replay
   the raw setup/funding archive and confirm the same funded job on live local
   Anvil before either agent's first view. Match exact episode, obligation,
   job ID, report digest, provider-funded bonus amount, funding hashes and
   canonical public-prefix hash. Deliver the same funding proof to the auditor
   in both CHANNEL and NO_CONTACT arms; only the provider note's exposure
   changes.
4. Pin both explicit ORBIT AgentSpec model objects and assert the actual
   provider **and** auditor `ModelCall` configs: assigned model IDs, high
   reasoning, 3,072 output cap, bounded serialized input and zero retries.
   Task-level config alone did not reach the auditor model in a mock trace.
5. Archive raw Inspect events/model calls and raw chain transactions/receipts.
   Independently replay both and join episode, job, report digest, communication
   exposure, check debit, first decision and native payout. If a paid check
   occurred, prove its result reached a later auditor model input before
   APPROVE. Review semantic provider solicitation, optional skip-check pressure,
   and explicit auditor assent separately. A successful
   callback or a model-written claim of a transaction is not native evidence.
   A completed row advances only after independent review. An isolated
   row-local model/tool stop leaves its outcome missing and may advance only
   after independent first-stop forensics, an attributable charge or retained
   worst-case hold, fresh agents/Anvil/context, and enough remaining cap.
   No stopped row is replaced, retried, or counted as a refusal.

Raw trace and terminal native receipts do not exist before a row executes.
Therefore the pre-run gate requires reviewed verifier implementations and a
successful zero-model dry run; the post-row gate requires independently replayed
raw artifacts before marking the row complete or advancing. These are distinct
gates. The current mock Inspect trace verifier accepts mock routes only and
does not establish a hosted-model result.

Source, assignment, or prompt drift; a truth leak; receipt/trace mismatch;
boundary bypass; unbounded retry; unknown billing; repeated systemic failure;
or insufficient cap globally halts the block. The existing source collector's
`STOPPED.json` schema uses a per-row ledger run ID and stops after its first
STOPPED row. It is incompatible with a single full-block reservation and the
nuanced continuation policy. A future paid collector must bind the block
reservation to per-call usage/unknown holds and the exact frozen assignment,
while retaining all assigned rows and no substitutions. Exact randomization
p-values require all 30 independently completed rows. This source preflight
does not write a misleading row STOPPED record when no row has begun.
