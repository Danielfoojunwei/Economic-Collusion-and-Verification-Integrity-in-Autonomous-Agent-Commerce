# FEE011: zero-call successor to the frozen ERC-8183 fee assignment

Status: **prospective code only**. FEE011 has no saved readiness, no frozen
assignment, no model calls, no native episode receipts and no ledger entries.
The original FEE010 assignment remains frozen and is closed administratively
as eight `STOPPED_BEFORE_EXECUTION` rows. Its [separate closure archive](../artifacts/gates/ERC8183_FEE010/verification-stop-001.json)
binds the original assignment, lock, readiness, source commit, zero-call ledger
state and the read-only verifier failure. Those rows are not stopped model trials.

The FEE010 freezer intentionally wrote a frozen `schema` and `status` over the
unfrozen preview. Its default verifier checked those two frozen values, then
compared **all** preview keys, including the two overwritten keys, to their
unfrozen values. The original read-only verifier returns
`ValueError: frozen fee study assignment/source differs`. The independent
closure verifier confirms that these are the **only** differing preview keys;
the FEE010 source and assignment are not repaired or overwritten.

FEE011 inherits the **exact FEE010 seed, eight private rows, public row IDs and
execution order**. It does not draw a new seed, reroll an outcome, change
models, change prompts, change payment terms or alter the no-contact controls.
Its `expected_preview()` rewrites the expected `schema`, `status` and successor
`study` fields before comparison. The regression suite rejects changes to any
of those values or to the inherited row order.

FEE011 has a new independent readiness record, assignment manifest and lock,
new `fee011-` ledger run IDs, and a separate `ERC8183_FEE011/runs-001` archive.
It reuses the unchanged FEE010 ORBIT/Inspect task, official local ERC-8183
controller, model boundary and native receipt verifier. All 28 original source
hashes remain sealed and the additional FEE011 sources are included in the
successor inventory. The freezer and paid runner require the canonical checkout
that owns the shared USD 50 ledger. Read-only readiness may run in an isolated
development checkout; saving readiness and freezing assignments require the
canonical checkout and committed sealed sources.

At any later freeze and at each attempted row, the shared ledger and fresh
public pricing must still support the **entire remaining eight-row block**, the
USD 2 contingency, the MPP006 contingent hold and the unassigned residual.
MPP010 or other spending may make FEE011 unaffordable; that is a stop, not
grounds to trim or reroll its rows. One row is attempted per explicit invocation
with no SDK retry. A technical or billing stop blocks later rows and remains
in the assigned denominator. The saved Inspect, native receipts and ledger
settlement must independently replay before a row is counted as complete.

The FEE010 closure's zero-call finding is supported by its first-freeze lock,
absent local run directory and absence of `fee010-` IDs in the shared ledger.
It does not establish whether an unrelated off-ledger account was charged.
FEE011 therefore labels future real model behavior only from its own archived
Inspect/provider events and native payment evidence.
