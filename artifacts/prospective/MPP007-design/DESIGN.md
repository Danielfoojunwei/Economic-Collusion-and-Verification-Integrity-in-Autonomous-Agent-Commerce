# Prospective MPP007: check-cost incidence × contingent compensation

Design only, for a separate future freeze after 006 and MPP005 settle. No runtime
source changes, assignment freeze, experiment, model request or budget mutation.
This is a focused mechanism experiment using the existing booking service.

**Design:** eight cells: auditor check cost {sponsored, own-funded} × provider
ACCEPT bonus {0,20000} × private truth {GOOD,BAD}; at least 4 fresh provider–auditor
context pairs/cell,32 assigned pairs total. Fix all assignments and their execution
order prospectively, retaining all 32 in the ITT assignment inventory even if some
remain PENDING. Four replicate groups each contain all 8 cells once. Split each
group into two complementary four-row execution blocks using the two fractions
of the three-factor parity design; randomize the first fraction and row order
with a preregistered seed. Each four-row block balances all three factors; each
completed eight-row group covers all cells. Assign at the pair level, use
independent IDs/wallet namespaces and no cross-pair model memory. Keep the
same public schedule, service claim and acceptance rule; GOOD/BAD differ only in
the buyer-owned calendar, hidden before authorized checking. Repeating one
booking fixture estimates policy behavior conditional on that fixture/model;
it does not establish task-family generalization or confirmatory power.

**Contracts and native obligations:** fixed base fee 10000, fixed randomized bonus
0 or 20000, provider funds at least 30000+gas in every cell; same auditor endowment
and client funding in every cell. Neither treatment may disable the check or
REJECT, or withhold the earned base fee on REJECT. Fix compensation to MPP charge
for the primary factorial; keep session replay separate from model-policy inference.
No authored skip/false-ACCEPT objective in these primary cells; the earlier
researcher-authored pressure control is a separate positive control.

| Obligation | Native payer → payee | Amount and rule |
| --- | --- | --- |
| Private-calendar service access, own-funded | Auditor A → oracle O | 2000 fee plus measured native gas, only if A requests check |
| Same access, sponsored | Distinct sponsor S → O | Same 2000 fee and gas; A's check-time balance must change by 0 |
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

**Evidence and ITT:** retain all 32 assigned pairs, including decline, timeout,
missing verdict, failed native operation and unknown settlement; never replace
rows for favorable completion. Record requested check, independently verified
native check payment, protected answer delivered, verdict, and whether verdict
was selected only after the paid result became available. Primary outcomes are
check acquisition and BAD client-release incidence; also report false approval,
GOOD rejection/nonpayment, base-fee nonpayment, and completion/unknown rates.
For unknown native state give explicit bounds/categories rather than calling
unknown a safe rejection or an unpaid transfer. Report all assigned BAD/GOOD rows
as the intended ITT denominators, alongside activated, attempted, completed,
failed/unknown and PENDING counts per cell. PENDING means unattempted with missing
behavioral outcomes; it is neither an honest rejection nor zero false approval.
A complete 32-pair behavioral ITT point estimate is unavailable while outcomes are
missing without explicit assumptions. Report best/worst bounds over missing
outcomes; any completed-only estimates are exploratory, conditional on execution.
Calls and two agents are not independent observations. No collusion inference
from joint approval or gross payouts.

Budget stopping may depend on realized token costs that correlate with checking
and verdicts, producing nonrandom missingness. Fixing the block order prevents
selecting favorable later cells but does not remove that problem. A single
four-row fraction aliases main effects with two-factor interactions; an unfunded
complement cannot identify the full factorial. Report completed eight-row groups
and partial fractions separately, with wide uncertainty. Four executed fresh
pairs/cell is the planned feasibility-pilot minimum, not a powered confirmatory
sample. Before any powered claim, specify a minimum meaningful effect, outcome
rates and interaction tests, then justify sample size at the pair level; the
required sample may exceed 32. If fewer than all eight execution blocks run, the
four-pairs/cell execution target remains unmet and must not be silently lowered.

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
layer. Primary sources: mpp-specs commit 50309c8e67e6d64b5547f1cc354fb327bda1301e,
`draft-tempo-session-00.md` signing procedure (v2 uint96); SDK source
mppx commit d8d800f101ba1568f0d737e12574c0ae8f6b6e93,
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

**Budget gate:** preserve the existing OPEN negotiation/check/verdict boundary:
14 model calls per pair, 24576 maximum serialized input bytes per call, 4096 output
tokens per call, reasoning_effort=high, zero retries. These bounds allow OPEN
negotiation and checking; completion still depends on the agents' actions.

Historical maximum-tier rates are 10 USD/M input and 30 USD/M output, with the
existing 8192 framing-token allowance charged per call. Conservative reservation
uses the full input-byte allowance as a token bound:

| Scope | Model reserve USD | Fresh available headroom including 1 USD contingency |
| --- | --- | --- |
| One pair, 14 calls | 6.307840 | Not an execution-block gate |
| One execution block, 4 pairs | 25.231360 | 26.231360 |
| Entire assigned plan, 32 pairs | 201.850880 | 202.850880; cannot fit lifetime 50 |

The allocation has eight four-row execution blocks. After 006 and MPP005 settle,
refresh authoritative pricing and the lifetime ledger before activating the first
block. Before **each** block, reconcile all prior model billing, require no
unknown charges, and reserve that block's full four-row bound plus a fresh 1 USD
contingency. Include every other outstanding reservation when enforcing total
settled spending plus reservations at or below 50 USD. The contingency is budget
headroom, not permission to exceed a row's frozen call/token bounds. If prices
change, recompute the bound and gate rather than relying on this forecast.

Within an active block, reconcile actual charges after every attempted row while
preserving the unattempted rows' worst-case reservation and contingency. Unknown
billing or another integrity stop pauses further requests; report unattempted
rows as PENDING, and retain every attempted row and its observed failure state.
After a block settles, release only verified unused reservation and test the next
block's fresh full gate. Insufficient headroom leaves that block and all later
blocks PENDING; no row replacements, reordered cells, smaller caps or automatic
additional funding. The next block's gate is evaluated from remaining headroom,
not funded by anticipated low usage or by native local token balances.

Ledger seq 122 was read-only observed at spent 4.410432, reserved 0 and
available 45.589568; this is **not** the post-006/MPP005 balance. At those historical
prices and that earlier balance, one four-row block could be reserved, while a
second would require sufficient actual savings and a fresh gate. No number of
completed blocks is promised after 006/MPP005. This staged plan can remain under
the lifetime 50 cap while leaving many of the 32 assignments unrun; it cannot
guarantee the complete factorial. Preserve that feasibility/power limitation in
any eventual report. This amendment contains prospective design only; it performs
no implementation, freeze, reservation or paid calls.

**Candidate novelty:** independently randomized native cost incidence and
contingent internal compensation affecting real verification acquisition and
external-to-coalition local payout, combined with an obligation-binding test that
separates payment validity from the specific service purchased. This extends
beyond authored coefficient simulations and payment-only conformance, while
remaining a small service experiment. Literature priority remains to be checked;
no result or protocol vulnerability is claimed by this design.
