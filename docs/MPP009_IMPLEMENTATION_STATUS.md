# MPP009 implementation checkpoint

**Status: prospective source and local payment feasibility, 2026-10-15.** The MPP009
assignment has not been frozen. No MPP009 model request, live-agent result,
or collusion finding exists. A separate local-chain native check is described below. MPP006 and MPP008 assignments and evidence
remain separate. The existing frozen MPP008 source was not changed here.

## Implemented interface

- `mpp009_plan.py` constructs ten deterministic fresh role pairs: eight BAD
  bonus × check-price × cross-vendor direction cells, two GOOD base-only anchors,
  a GOOD compatibility gate, and HMAC-randomized BAD execution order. The
  bounded call schedule is `P,P,A,A,P,A,A,A` with high reasoning required at
  the raw model boundary. The input cap was raised prospectively to 32,768 bytes
  after MPP008's first paid row attempted 28,345 bytes against a 24,576-byte cap.
  At the catalog prices recorded in the prospective
  proposal, full-block reservation is USD 29.491200, before the USD 2 ordinary
  contingency. The prior MPP006 hold must be retained inside the canonical
  ledger's `CONTINGENT` state; MPP009 must not deduct it a second time.
- `mpp009_budget.py` verifies that first-class `CONTINGENT` state and its
  evidence, then requires all ten row reservations, USD 2 contingency, and the
  USD 0.0000342 unresolved provider-export residual to fit the **already
  reduced** ledger available balance. At the recorded model prices this is
  USD 31.4912342 of new headroom. It does not authorize freezing while MPP008
  still has executable pending rows or the AP2 study has priority on the shared
  balance. AP2's prospective full headroom is USD 35.4233942; both prospective
  blocks cannot fit concurrently in the USD 37.99432 available snapshot.
- `PressureBookingMarket` keeps the buyer calendar controller-private, binds
  every valid proposal to the assigned 10,000 base and 0/20,000 ACCEPT bonus,
  and charges the assigned 2,000/4,000 check price in controller replay. The
  provider can write its own bounded message. `select_mpp_flow` admits charge
  only. The model prompt does not direct a false approval or skipped check.
- Versioned Python/Node MPP009 service helpers bind study, episode, assigned
  terms, price, source hash, prepare proof, exact receipt amount, payer/payee,
  historical balances, and answer release. Provider-to-auditor base/bonus
  compensation uses local MPP charge. Client release on ACCEPT and conditional
  bonus are trusted **application** rules, not protocol-native escrow.
- Separate MPP009 raw role boundary rejects model-route swaps, non-high
  reasoning, extra turns, failed tools, private notice leaks, and tool-schema
  drift before normalization for the legacy single-model replay verifier.

## Offline verification

From the repository root, with the pinned ORBIT/Inspect environment installed:

```sh
PYTHONPATH=src:. PYTHON_DOTENV_DISABLED=1 /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_mpp009_pressure -v
node --check protocols/mpp/mpp009-meeting-service.mjs
node --check protocols/mpp/mpp009-verify-meeting-service.mjs
node --check protocols/mpp/mpp009-meeting-local.mjs
node --check protocols/mpp/mpp009-verify-meeting-evidence.mjs
node --check protocols/mpp/mpp009-decision-preflight.mjs
```

Ten offline tests passed on 2026-10-15. They cover factorial assignment,
fresh pair identity, reserve arithmetic, a GOOD/BAD private oracle, strict
terms, check price, charge-only selection, eight-turn ORBIT task construction,
provider-only notice, request-guard rejection of altered episode terms, price,
private calendar, preparation proof or verdict, and preflight rejection of
tampered prices, bonus terms, or same-model role swaps. A budget test confirms
the old contingent hold is counted only inside the canonical ledger. These
tests do not establish native transfer success.

## Isolated native feasibility

The pinned `ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`
image was initially started in a **separate** container on host port 19667 with
`--block-time 100ms`. It exited before RPC bootstrap with:

```text
Error: failed to fund the localnet bootstrap account
nonce manager error: expiring nonce valid_before (...) too far in the future: must be within 300s of block timestamp (0)
```

`--bare --block-time 100ms` resolved the timestamp-zero bootstrap failure.
Because bare mode disables `tempo_fundAddress`, the MPP009 signer now makes
recorded, independently verified native TIP-20 transfers from the test genesis
account to the four local actors. It caps the auditor's wallet to 6,000 before
the trial. An isolated direct 4,000-unit BAD check on port 19667 passed:
auditor balance before check 5,681; exact check transfer 4,000; gas 29; and
independently verified protected oracle status FAIL. Its local evidence is at
`artifacts/prospective/mpp009-native-feasibility-001/price4000-bare/`. This
is a **zero-model native feasibility control**, not a live outcome. The MPP008
chain and ports 19567/19559 were left untouched. Complete scripted ORBIT
GOOD/ACCEPT and BAD/REJECT controls at both prices and both role directions,
plus unchecked BAD/ACCEPT and tamper negatives, **before any MPP009 freeze**.
Measure each scripted model input against the new 32,768-byte cap. Then add
source-sealed freezer, one-row paid runner and read-only collector against the
canonical USD 50 `CONTINGENT` ledger. The entire ten-row block and ordinary
contingency must fit after AP2 and MPP008 allocation decisions; a smaller
selected subset is not an allowed substitute.
