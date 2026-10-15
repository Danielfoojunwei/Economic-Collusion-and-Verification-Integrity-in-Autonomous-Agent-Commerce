# Booking A → B obligation-binding control

**PASS:** eight zero-model controls and twelve native evidence/tamper tests. Final
evidence is `zero-model-006/`; earlier diagnostic runs are not current-source
results. This is separate prospective source, with no changes to existing 006 or
MPP005 runners, task files, dependency lock, freezes or budget ledger.

## Question and sequence

Can a fresh payment proof for booking A authorize private-calendar verification
or client release for booking B when payer, payee, token, amount and public
schedule are the same? A and B have different booking/obligation IDs and private
calendar commitments. A is available; B conflicts at agent_0/MTG-1/slot 0. Both
release controls have a separately committed scripted ACCEPT, so rejection
cannot be explained by an absent B ACCEPT or a different amount/recipient.

For each control:

1. Obtain unpaid A and B challenges; neither exposes a calendar answer or service
   result. Fund only local synthetic actors, before the recorded initial state.
2. Create a valid, unconsumed A credential. Charge uses the pinned SDK's `pull`
   mode: a signed transaction, with broadcast deferred until server acceptance.
   Session uses a signed channel-open transaction plus initial voucher. Signing
   changes no native balance or accepted service credit.
3. Submit that exact A credential to B **first**. Require refusal, unchanged
   historical balances, unchanged server credit/replay store, no B answer and no
   B client-release attribution. The session channel is still unopened.
4. Submit the **same** credential to A. Require successful protected A delivery
   and native payment; close each session and verify actual settlement/refund.

The valid subsequent A operation prevents an invalid signature, expired proof or
already-consumed replay from explaining B's refusal. The charge native memo is
independently checked against A's challenge ID. The session opening, channel
descriptor, receipt, close event, actual transfers and historical balances are
bound to the same fixed actors/token/channel. The exact serialized A transaction
is hashed against the actual executed native receipt; the initial session voucher
signature is independently verified.

## Two separately labeled mechanisms

| Mechanism | Where B is refused | B response | A response |
| --- | --- | --- | --- |
| `SDK_EXPLICIT_OBLIGATION_SCOPE` | SDK challenge binding rejects authenticated opaque scope mismatch | 402 | 200 |
| `AUTHORED_ADAPTER_OBLIGATION_GUARD` | Researcher-authored trusted challenge-issuance registry rejects wrong full obligation before SDK call | 403 | 200 |

Each mechanism runs charge/session × check/release: four controls per mechanism.
The full obligation includes booking ID, calendar version/commitment, attendance
digest, operation, decision commitment when relevant, payer, payee, token, amount
and application policy. The SDK `scope` is **application-supplied configuration**.
Its native challenge verification performs the scope comparison. The separate
adapter guard uses an issuance registry; the SDK still verifies the legitimate
credential before delivery. Their rejection origins are checked independently.

Inspection of installed `mppx@0.13.4` found no automatic path attachment in bare
`Mppx.toNodeListener`. This control configures explicit obligation binding; it
does not test an unguarded adapter or claim every default adapter rejects B.
No payment standard exploit or SDK vulnerability is claimed. The session voucher
itself authenticates channel/cumulative amount; service obligation attribution
remains an application/transport responsibility.

## Native accounting

Amounts are valueless local pathUSD atomic units. Both guard mechanisms produced
the following independently verified costs:

| Flow and obligation | Gross A payment | Payer total debit | Payer gas | Payee net gain | Payee close gas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Charge calendar access, auditor → oracle | 2000 | 2029 | 29 | 2000 | 0 |
| Charge client release, client → provider | 100000 | 100029 | 29 | 100000 | 0 |
| Session calendar access, auditor → oracle | 2000 | 2043 | 43 | 1948 | 52 |
| Session client release, client → provider | 100000 | 100043 | 43 | 99948 | 52 |

In every control, B has zero accepted service credit/delivery; the valid native
operation occurs after the rejected B snapshot and is attributed to A. A session
deposit is gross obligation plus 10000; close refunds the unused 10000. Neither
faucet funding nor deposits count as service revenue. All four actor namespaces
are separate from the existing task wallets, using public local mnemonic indices
21–52. No real calendar, wallet secret, client funds or external service is used.
Release remains `APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW`.

## Commands and provenance

Run from the repository root, with the existing pinned `protocols/mpp`
dependencies (`mppx@0.13.4`, `viem@2.57.1`, unchanged package lock), a retained
local Tempo chain, and an unused service port. Output directory creation refuses
overwrite. For a new run, replace the final directory name and set
`MPP_BINDING_EVIDENCE_DIR` for the tests accordingly.

```bash
node protocols/mpp/booking-obligation-control.mjs artifacts/prospective/mpp-booking-obligation-control/zero-model-006
node protocols/mpp/verify-booking-obligation-control.mjs artifacts/prospective/mpp-booking-obligation-control/zero-model-006/report.json artifacts/prospective/mpp-booking-obligation-control/zero-model-006/verified-report.json
node --test protocols/mpp/test-booking-obligation-control.mjs
```

Executed Node v24.19.0; RPC `http://127.0.0.1:19567`, service
`http://127.0.0.1:19569`. Both scripts enforce loopback HTTP and chain 1337. The
existing container `open-mpp-booking-service-debug` was reused without restart;
its inspected local Docker image ID is
`sha256:085da3bc19f0d51ab2b0206e4d4d7ccdf788dd2f0987b044f1243c87e5e21093`.
The inspected registry digest is
`ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`.
Each evidence file pins the actual executable SDK files, both new scripts and the
existing dependency lock by SHA-256. `validation-report.json` records the source
inventory and commands. `runner.*`, `verifier.*`, `tests.*` preserve process output.

**Verifier:** the separate read-only script imports no runner and performs no
signing, funding, model request or mutation. It fetches raw native receipts and
historical balances from retained RPC, validates pinned identities, transfers and
session state, verifies challenge provenance/scope, and checks trace ordering,
protected responses and accepted-credit snapshots. Twelve tests passed, zero failed
or skipped: all eight genuine controls plus eleven forgeries covering leaked B
data, B release credit, consumed-proof order, payee, erased session gas, channel,
receipt emitter, changed challenge scope mislabeled rejection origin, invalid session voucher and substituted signed transaction.

## Diagnostic and evidence limits

An early run stopped because the receipt wait helper's default replacement
detection returned a different transaction during faucet setup. The next state
snapshot exposed late funding rather than an unauthorized payment. Retained
`diagnostics/funding-race-002.*` includes its STOPPED partial state and logs. The
new helper disables replacement detection and requires receipt.transactionHash
to equal the requested hash. Final controls independently verify all faucet
receipts precede initial state. Earlier completed diagnostic runs used earlier
source hashes and are not counted in the final current-source result.

All decisions and proof submissions are scripted controls. Model execution tier
is `NOT_APPLICABLE`; transaction tier is `NATIVE_LOCAL_PROTOCOL`. Remote model
calls and real spending are zero; this is no live-agent behavioral result or
factorial execution. Native receipts establish payment/state claims. HTTP
nondelivery and application resource attribution rely on retained trace and
source provenance, not an on-chain confidentiality proof. Reverification of
historical RPC facts requires the retained chain; an offline JSON snapshot alone
does not authenticate those facts. A separate reviewer has not yet reviewed this
new component.
