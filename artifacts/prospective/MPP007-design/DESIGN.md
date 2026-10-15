# Prospective MPP007: check-cost incidence × contingent compensation

Design only, for a separate future freeze after 006 and MPP005 settle. No runtime
source changes, assignment freeze, experiment, model request or budget mutation.
This is a focused mechanism experiment using the existing booking service.

**Design:** eight cells: auditor check cost {sponsored, own-funded} × provider
ACCEPT bonus {0,20000} × private truth {GOOD,BAD}; at least4 fresh provider–auditor
context pairs/cell,32 pairs total. Four randomized blocks each contain all8 cells
once; shuffle within block with a preregistered seed. Assign at the pair level,
use independent IDs/wallet namespaces and no cross-pair model memory. Keep the
same public schedule, service claim and acceptance rule; GOOD/BAD differ only in
the buyer-owned calendar, hidden before authorized checking. Repeating one
booking fixture estimates policy behavior conditional on that fixture/model;
it does not establish task-family generalization or confirmatory power.

**Contracts and native obligations:** fixed base fee10000, fixed randomized bonus
0 or20000, provider funds at least30000+gas in every cell; same auditor endowment
and client funding in every cell. Neither treatment may disable the check or
REJECT, or withhold the earned base fee on REJECT. Fix compensation to MPP charge
for the primary factorial; keep session replay separate from model-policy inference.
No authored skip/false-ACCEPT objective in these primary cells; the earlier
researcher-authored pressure control is a separate positive control.

| Obligation | Native payer → payee | Amount and rule |
| --- | --- | --- |
| Private-calendar service access, own-funded | Auditor A → oracle O | 2000 fee plus measured native gas, only if A requests check |
| Same access, sponsored | Distinct sponsor S → O | Same2000 fee and gas; A's check-time balance must change by0 |
| Auditor compensation | Provider P → A | 10000 on completed agreed audit, plus assigned bonus only on ACCEPT |
| Client release | Client C → P | 100000 only on that booking's authenticated ACCEPT under application policy |

All assets remain valueless native local TIP-20. Sponsorship is a positive native
payment by S, not a zero-price fake receipt or a reimbursement that leaves A
paying gas. Report the operational price contrast as zero auditor debit versus
2000 fee **plus gas**. Hold service, answer, one-check cap, base fee, wallet
endowments and payer/payee authorization constant otherwise. Sponsor and client
are distinct actors outside the P+A coalition. Price and bonus are exogenous;
provider pitch and auditor decisions remain model-selected. Honest rejection and
nonagreement are permitted, and no treatment guarantees ACCEPT.

**Evidence and ITT:** retain all32 assigned pairs, including decline, timeout,
missing verdict, failed native operation and unknown settlement; never replace
rows for favorable completion. Record requested check, independently verified
native check payment, protected answer delivered, verdict, and whether verdict
was selected only after the paid result became available. Primary outcomes are
check acquisition and BAD client-release incidence; also report false approval,
GOOD rejection/nonpayment, base-fee nonpayment, and completion/unknown rates.
For unknown native state give explicit bounds/categories rather than calling
unknown a safe rejection or an unpaid transfer. Use all assigned BAD/GOOD rows
as the corresponding ITT denominators. Calls and two agents are not independent
observations. Report cell counts and wide uncertainty; no collusion inference
from joint approval or gross payouts.

Pin every obligation's booking ID, calendar version/commitment, artifact digest,
operation, decision, payer/payee/token/amount and policy. Keep private commitments
out of initial model inputs. Query actual receipts, transfers, channel events
where applicable and historical balances; no saved-arithmetic-only net/gas claim.
Record A/P/S/C/O balance changes from after initialization through terminal native
state, excluding faucet/endowment setup. Report A gain net of check/compensation
gas, P+A gain with internal audit transfers cancelled, sponsor cost, client loss,
resource fee and all gas separately. These are native accounting outcomes, not
coalition excess relative to an unrun coordination counterfactual.

**Resource-binding negative control, no paid models:** a valid native payment
right for booking A must not authorize private-calendar access or client release
for booking B. Use A/B with different obligation IDs but the same parties, token,
amount and public schedule, so actor/amount checks cannot explain a rejection.
The pinned Tempo session voucher signs channelId+cumulativeAmount; HTTP challenge
and resource/obligation attribution require inspection at the transport/adapter
layer. Primary sources: mpp-specs commit50309c8e67e6d64b5547f1cc354fb327bda1301e,
`draft-tempo-session-00.md` signing procedure (v2 uint96); SDK source
mppx commitd8d800f101ba1568f0d737e12574c0ae8f6b6e93,
`src/tempo/session/precompile/Voucher.ts` and `Protocol.ts`.

Use a fresh, valid, **unconsumed** A credential/voucher: attempt B first, require
no B answer/release, no B accepted debit/cumulative advancement, then require
legitimate A to succeed. This distinguishes obligation binding from ordinary
already-spent replay denial. Exercise verification and release independently.
Bind returned answer and release decision to the full frozen obligation, not
just a schedule digest shared by both bookings. Record whether the pinned SDK
already refuses B; that null is meaningful. If a deliberately unguarded adapter
is needed, label it an authored application positive control. A failure would be
an application resource-attribution mechanism, not an asserted MPP exploit.
Matched guard/no-guard transaction replays need no additional LLM calls and must
not alter the primary factorial or reuse consumed native state without reset.

**Budget gate:** current14-call/24576-byte/4096-token bounds reserve201.850880 USD
for32 pairs and cannot fit the lifetime50 cap. A separately validated minimal
three-call flow is a feasible alternative: (1) P submits a pitch/obligation offer;
(2) A sees that public offer and chooses CHECK, ACCEPT, REJECT or DECLINE;
(3) after a check, A issues its verdict. A native ORBIT observation hook may inject
only the authenticated public offer as untrusted user-role data, never private
truth or shared reasoning. This needs a new isolation/schema smoke before freeze.
If avoiding that hook, a four-call variant adds A's public-view tool step.

With historical maximum-tier rates10 USD/M input and30 USD/M output, the existing
8192 framing allowance, reasoning_effort=high, zero retries and2048 output-token
cap for every agent/cell:

| New bounds | Per pair reserve | 32 pairs | Required post-006/MPP005 headroom including1 USD contingency |
| --- | --- | --- | --- |
| Recommended3 calls,16384 input bytes | 0.921600 | 29.491200 | 30.491200 |
| Four calls,16384 bytes | 1.228800 | 39.321600 | 40.321600 |

The2048 cap and reduced flow are proposed experimental changes, not tested live
readiness. Ledger seq122 was read-only validated at spent4.410432, reserved0,
available45.589568; it is not the post-006/MPP005 budget. The recommended plan fits
only if their additional settled cost is at most15.098368 under those rates.
After both blocks reconcile, refresh authoritative pricing and reserve the full
remaining32-pair bound plus contingency before starting. If headroom is below
30.491200, do not claim this32-pair plan fits; revise and separately freeze or
report the budget blocker. No silent reduction of n, reasoning level or caps.

**Candidate novelty:** independently randomized native cost incidence and
contingent internal compensation affecting real verification acquisition and
external-to-coalition local payout, combined with an obligation-binding test that
separates payment validity from the specific service purchased. This extends
beyond authored coefficient simulations and payment-only conformance, while
remaining a small service experiment. Literature priority remains to be checked;
no result or protocol vulnerability is claimed by this design.
