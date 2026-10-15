# Contingent billing in the shared model-spend ledger

`CONTINGENT` means an UNKNOWN request has a reviewed, content-addressed
provisional billing assessment, while its exact final charge remains unknown.
It is **not** a zero-dollar settlement, a provider invoice, or a model outcome.
The original research row remains STOPPED in its own archive. The ledger holds
the request's **entire original reservation** in `reserved_usd`, `committed_usd`
and `available_usd`; no `actual_usd` is recorded by this transition.

An operator first independently verifies the provisional evidence bundle and
its `sha256` digest against a specific ledger snapshot. The operator passes
that snapshot's `seq` and `last_hash` to
`BudgetLedger.mark_contingent(run_id, "sha256:<64 lowercase hex>",
expected_seq=seq, expected_last_hash=last_hash)`. Both preconditions are
required and checked while holding the ledger's exclusive lock, before an
event is appended. If another writer has changed the ledger since review,
the transition fails without altering either the ledger or its anchor. For an
unchanged UNKNOWN run it appends one hash-chained `contingent` event. The
replayed snapshot exposes `contingent_run_ids`, the
run's `status`, `evidence_ref`, `contingent_evidence_ref` and
`prior_unknown_reason`. A duplicate or malformed transition fails. Subsequent
`reserve` calls may proceed only if **all** UNKNOWN runs are resolved or made
contingent and the full new reservation still fits beneath the owner cap. A
CONTINGENT run with a full held reservation is not itself a blocking UNKNOWN
charge. This is a controlled way to use the remaining budget without assuming
what the stopped request cost.

For the MPP006 stopped request, the current USD 50 cap, USD 5.313220 already
settled, and USD 6.307840 original hold leave USD 38.378940 available in
either UNKNOWN or CONTINGENT state. The proposed MPP008 eight-row reservation
of USD 34.865152 plus USD 2 contingency fits inside that **remaining** amount
and leaves USD 1.513788. The proposed reserve is a bound calculated from the
assigned model prices and request limits; it is not a target or a guarantee
of provider charges. Freeze and runner controls must independently bind this
specific MPP006 run and the reviewed evidence digest. A generic ledger
transition alone does not authorize an experiment.

If the provisional evidence is discredited, `mark_unknown(run_id,
"evidence_discredited")` appends a new event, removes the active
`evidence_ref` from the run snapshot, preserves the historical
`contingent_evidence_ref`, **keeps the reservation**, and blocks further
reservations. A second contingent transition for that run is rejected. The
hash-chained event history also retains both assessments.

Only an attributable final provider bill can close a run that was ever
CONTINGENT. `settle(run_id, actual_usd,
"provider-billing:sha256:<64 lowercase hex>")` records its actual charge and
releases the original hold. The operator must verify that the hashed bytes
really are final billing evidence attributable to this request: the ledger
checks the reference syntax and arithmetic, **not** the invoice's authenticity
or its request mapping. This requirement also applies after reblocking. If
the actual charge exceeds the hold, the ledger records the true charge even
when it makes `over_cap=true`; subsequent reservations then fail closed.

This transition does not change the behavior of older `RESERVED`, `UNKNOWN`
or `SETTLED` events. Existing hash-chain and anchor checks replay both old and
new histories from the same canonical ledger. No archived event is rewritten.
