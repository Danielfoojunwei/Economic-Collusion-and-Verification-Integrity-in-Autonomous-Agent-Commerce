# BILATERAL030 bonus trigger: source and receipt diagnostic

**Status:** read-only diagnostic. No new model request, local-chain transaction,
assignment, or bilateral collusion observation. The proposed provider-funded
**early-approval** bonus treatment is **HOLD_UNIMPLEMENTED**.

## Finding

The existing application contract
[`ProviderAuditorBonusEscrow.sol`](../protocols/side_escrow/src/ProviderAuditorBonusEscrow.sol)
does **not** pay on an ERC-8183 milestone `approveClaim`. Its `settle()` method
can run only after the official job is terminal: `Completed` transfers the
funded bonus to the evaluator, whereas `Rejected` or `Expired` refunds it to
the provider. The bonus has no way to see an earlier `ClaimApproved` event.

The pinned official ERC-8183 implementation
[`ERC8183.sol`](../../upstreams/erc8183/contracts/ERC8183.sol)
allows a claim approval while the job remains `Funded`. The already archived
scripted BAD partial-claim control records this exact sequence:

| Step | Local MockUSDC result |
| --- | ---: |
| Evaluator approves first cumulative 10,000,000-unit claim | Provider receives 9,000,000; evaluator receives 1,000,000 native fee |
| Evaluator later rejects the full job | Client receives the remaining 10,000,000; first payout is retained |

The separate archived bonus-escrow control records a terminally rejected
official job and a 5,000,000-unit provider-funded bonus returned to the
provider, with **zero** bonus for the evaluator. These are **different local
jobs**. Source semantics therefore predict that attaching the existing bonus
escrow to the BAD early-APPROVE/final-REJECT path would refund the bonus to the
provider. There is **no same-job combined native receipt** in this diagnostic.

The first 1,000,000-unit evaluator payment above is the **buyer-funded native
evaluator fee**, not a provider-funded bonus or evidence of bribery. Calling
this combination an early-approval bonus treatment would confound the two
payment sources. A rational auditor anticipating final rejection has no
provider-funded bonus to collect under these existing terms.

## Evidence and reproduction

- The [partial-claim receipt](../artifacts/prospective/ERC8183_PARTIAL_CLAIM013/offline-native-001/scripted-bad-native-unchecked-approval-then-reject/native-evidence.json)
  is `SCRIPTED_SIMULATION` plus `NATIVE_LOCAL_PROTOCOL`. Its raw
  `ClaimApproved` transaction sends 9,000,000 to the provider and 1,000,000 to
  the evaluator; raw `JobRejected` refunds 10,000,000 to the client. The
  protected invoice oracle says BAD (350 submitted, 300 net).
- The [separate bonus receipt](../protocols/side_escrow/evidence/local-native-001/evidence.json)
  is scripted local-chain evidence. The existing read-only verifier checks its
  raw `BonusFunded`, `BonusSettled`, ERC-20 transfer, terminal rejection and
  recipient fields.
- [`diagnose_bilateral030_bonus.py`](../scripts/diagnose_bilateral030_bonus.py)
  pins source SHA-256 hashes, checks the relevant partial-claim raw events and
  balances, calls the existing bonus receipt verifier, and explicitly marks
  `same_job_joint_bonus_control: false`. Run
  `python scripts/diagnose_bilateral030_bonus.py` to print the report.
- `python -m unittest tests.test_bilateral030_bonus_diagnostic -v` checks the
  read-only result and rejects mutated early transfer and bonus payee records.

The disposable Anvil chains no longer exist. Archived receipts and source
hashes permit replay of saved fields; they are not remote-chain attestations.
The partial-claim diagnostic checks the decisive receipts and balances rather
than the entire archived sequence. The separate bonus verifier checks its
archived transcript, but it does not independently reconstruct the deployed
runtime bytecode from a preserved `eth_getCode` payload. Neither archive shows
an LLM choosing a false approval.

## Why a replacement trigger needs design review

The official core's `settledAmount` alone cannot authenticate an evaluator's
`approveClaim`: it also increases when the **client** calls `settleClaim`, and
the core permits either the client or evaluator to call `approveClaim`. After
approval, the pending claim hash is cleared. A side escrow paying merely when
`settledAmount >= 10,000,000` could release a bonus without the claimed
auditor approval, or for a different report.

A stronger native option is an admin-whitelisted application hook installed
when the official job is created. The core calls `afterAction` with the
`approveClaim` selector and encoded actor, amount and deliverable after the
official settlement. Such a hook could require the bound evaluator, exact
first cumulative amount and report digest before releasing a separately
funded bonus. It changes job creation and adds new contract trust, callback,
authorization and refund paths, so it needs its own source review, official
integration tests, raw receipt verifier and negative controls. A controller
that reads a prior receipt and triggers a side payout is another possible
research fixture, but must be labeled **controller-mediated**: an ordinary
contract cannot inspect an earlier transaction's receipt on chain.

Until one of those paths is designed and independently replayed, BILATERAL030
must not describe the existing terminal escrow as a provider-funded
first-approval incentive. No live run should use that mislabeled treatment.
