# When Agents Pay Their Auditors: Separating Agreement, Verification, and Settlement in Agent Commerce

**Exploratory research manuscript · evidence cutoff 16 October 2026 · draft for scientific review**

## Abstract

Autonomous commerce systems may let a provider pay an agent assigned to verify the provider's work. An auditor's approval can then trigger a separate transfer of buyer funds. We study a calendar-booking service in which the provider can offer an approval-contingent bonus, the auditor may buy an independent availability check, and an application acts on the auditor's verdict. The central measurement problem is that an improper offer, agreement to that offer, an incorrect verdict, and a settled payment are different events. In a stopped, text-only factorial study, 16 of 17 completed bad bookings in the no-contact, stated-bonus arm received unchecked approval, compared with 3 of 19 in the contact, stated-bonus arm; heavy missingness and changing message content prevent a causal interpretation. Separate transcripts contain explicit auditor assent to improper provider requests, but no executed payment. In one exploratory two-model local episode, an exactly delivered provider-authored solicitation preceded an unchecked false approval. The application transferred 100,000 valueless local units from buyer to provider; a trusted runner subsequently settled a 10,000-unit base fee and a 20,000-unit approval bonus through native MPP charges. A duty-prompted comparison arm rejected. The auditor's trusted objective also changed between these arms, and neither saw the private failing check result. Thus the episode demonstrates an executable failure path, not a causal bribe effect or proven knowing bilateral pact. We identify the application rule that converts an unchecked verdict into buyer release as the immediate failure boundary, and specify the randomized, prefunded study needed to test economic influence.

## 1. Introduction

Consider a buyer asking a provider agent to book a meeting with `agent_0`. A separate auditor agent is supposed to decide whether the proposed slot is genuinely available. The provider can pay the auditor a base fee and promise an extra fee for approval. The auditor can query a buyer-controlled calendar for 4,000 local test units, or it can issue a verdict without checking. An approval causes the application to release 100,000 buyer units to the provider. The provider-to-auditor payment and the buyer-to-provider release are distinct transactions with distinct authorities.

The obvious story is a bribe: the provider asks for a false approval, the auditor agrees, and the buyer pays for a bad booking. Yet each arrow in that story requires its own evidence. A model can write an offer that never reaches the other model. An auditor can accept payment terms while refusing the corrupt request. An auditor can falsely approve without any provider contact. A real payment receipt can show that money moved without showing why the auditor acted. Combining different episodes into one story would manufacture evidence of bilateral collusion.

We therefore ask a narrower question: **what part of the proposed corrupt transaction actually executed, and what does each observation allow us to infer?** We examine a two-agent verification task built on ORBIT/Inspect [R4, R5], use action and coalition distinctions informed by Colosseum [R3], and connect the model trace to a local MPP payment path [R7]. The contribution is an evidence-linked analysis of one completed induced failure path and two complementary text studies. It is not a new benchmark, a prevalence estimate, or a claim that payment protocols attest work quality.

Three findings organize the paper. First, explicit textual agreement and payment-backed harm do not necessarily coincide: we found the former in unfunded text runs and the latter in a native local run without an explicit agreement to lie. Second, the largest observed text-only failure count occurred **without** a delivered provider message, which challenges a simple communication-centered account of the risk. Third, the executed local buyer transfer arose at the application's approval-to-release rule; valid side-payment receipts did not verify the booking. These findings motivate an experiment that holds the auditor's duty fixed while independently varying contact and genuinely funded compensation.

## 2. Related work and scope

The closest preliminary study supplied with this project already examines two-agent verification, affordable checks, and acceptance-contingent offers [R1]. It reports limited verdict movement under a researcher-funded randomized offer. We neither claim to introduce priced verification nor treat joint approval as collusion. SALT's *Emergent Collusion* studies repeated agent interaction, peer audit, communication, and shared reward [R2]. Colosseum supplies coalition-oriented measurements and examples in which agents are explicitly prompted to collude [R3]. ORBIT and Inspect supply a role-scoped agent runtime and traces; ORBIT's own guidance cautions that collusive language is not sufficient outcome evidence [R4, R5]. AgenticPay covers richer buyer-seller negotiation [R6].

Payment specifications establish authorization and accounting rules, not independent service truth. In particular, MPP Tempo charges describe payment, while ERC-8183 claim settlement, x402 proofs, and AP2 mandates address different portions of a commerce flow [R7–R10]. Our live native result uses MPP for the **provider-to-auditor fee**. Buyer release is an application-controlled local token transfer. The other protocols inform the threat boundary, but their varied, largely scripted or stopped runs do not support a comparative collusion ranking. This is a targeted source comparison, not an exhaustive priority search [E1].

## 3. System, threat model, and measurements

### 3.1 Booking and payment flow

The buyer's protected calendar says whether the selected slot is available. In a bad fixture, `agent_0` is unavailable. The provider prepares the booking and may send a lower-trust offer to the auditor through the market tool. The auditor can buy a current-booking calendar check for 4,000 units. The application accepts its final `ACCEPT` or `REJECT`; `ACCEPT` releases 100,000 buyer units to the provider. A provider-funded 10,000-unit base fee and potential 20,000-unit `ACCEPT` bonus are settled separately. The amounts are valueless local assets, not real customer money.

```mermaid
sequenceDiagram
    participant P as Provider model
    participant M as Market application
    participant A as Auditor model
    participant O as Protected calendar
    participant B as Buyer balance
    participant R as Trusted runner / MPP
    P->>M: Propose fee terms and message
    M->>A: Deliver exact accepted offer
    opt Auditor chooses independent check
        A->>O: Buy current-booking check (4,000)
        O-->>A: PASS or FAIL
    end
    A->>M: ACCEPT or REJECT
    opt ACCEPT
        M->>B: Transfer 100,000 buyer units to provider
    end
    R->>A: MPP base fee (10,000)
    opt ACCEPT bonus
        R->>A: MPP bonus (20,000)
    end
```

**Figure 1.** Authorities in the local booking flow. The model authors an offer and chooses a verdict. The market application executes buyer release. The trusted runner invokes MPP charges after the verdict. In the completed native arms, neither auditor chose the check.

### 3.2 Threat and outcome definitions

The provider is interested in approval and can solicit an improper skip-check decision. The auditor is supposed to give an independent verdict. The provider's message is untrusted task content, not a system instruction. We separately record:

1. **Solicitation and exposure:** the exact provider-authored request and whether its bytes entered the serialized auditor input.
2. **Assent:** an auditor statement accepting the improper process request; accepting fee terms alone does not count.
3. **Verification:** a real check debit and returned result, or only text saying the auditor would check.
4. **Decision error:** `ACCEPT` for a privately bad booking, whether or not the auditor knew the private truth.
5. **External consequence:** an executed buyer-to-provider release for that booking.
6. **Side payment:** a separately executed provider-to-auditor fee or bonus.

These fields prevent three common substitutions: a provider message in a trace for actual exposure, a textual check choice for a charged check, and a side-payment receipt for proof of service quality. They also distinguish **collusion-compatible behavior** from established conscious agreement. The private oracle can establish that a verdict is false; it cannot establish that a model knowingly lied when it never saw the oracle result.

### 3.3 Evidence sources and analysis rule

We select three components because each tests a link in the same flow. A profit-framed, text-only MPP block probes explicit solicitation and assent. A neutral-duty, text-only 2×2 block probes contact and stated bonus with a scripted check. An ORBIT/Inspect local run connects exact exposure and model action to MPP receipts and application release. All three used the fixed provider route `nvidia/nemotron-3-super-120b-a12b:free` and auditor route `dots-studio/dots-3-note-preview:free`; high reasoning was requested, but that setting does not measure decision quality. Model routes were chosen after exploratory feasibility checks, not sampled to support a model-comparison claim. The three components are **not pooled**: prompts, finance, check execution, and stopping differ. Two reviewers independently coded the text transcripts; the neutral-duty reviewers could see treatment and fixture truth. Separate reviewers checked the native trace and receipts [E2–E4]. We report assigned, complete, incomplete, stopped, and unattempted rows separately. An incomplete row is not a safe rejection.

## 4. Results

### 4.1 Explicit agreement appears in text runs without settlement

The first MPP text block assigned 90 bad bookings. It completed 29; seven were incomplete, one stopped, and 53 were never attempted. Of 12 rows where an improper provider request appeared in the auditor's actual input, eight auditors explicitly agreed to the requested skip/accept process. One replied, “I accept your offer and will proceed without the calendar check.” Two exposed auditors refused and chose the check and hold path; two had no usable auditor output. Twenty-three completed bad rows ended in false textual approval, **15 without exposure** to any provider message. These counts are from independent transcript review [E2]. This study used a trusted profit-maximizing auditor instruction, unfunded offers, and no native side payment, check debit, or buyer release. It shows model-authored solicitation and textual assent, not a paid bargain.

The neutral-duty 2×2 study provides a stricter semantic check. Of 140 assigned rows (30 bad and five good per arm), 79 completed, 24 were incomplete, one stopped, and 36 were unattempted. In bonus arms, the auditor's trusted task prompt already stated the approval bonus; “no contact” means the provider's message was withheld, not that the auditor lacked bonus information. Reviewers found three clear responses accepting a delivered provider process request and one disputed possible assent. Only one clear reply explicitly mentioned the bonus; none proves receipt of that bonus. The messages were researcher-induced, and the stated terms were not funded [E3].

### 4.2 False text approvals cluster in the no-contact bonus arm

| Assigned arm | Completed bad unchecked `ACCEPT` | Completed bad check, `FAIL`, `REJECT` | Completed bad unchecked `REJECT` | Missing bad of 30 | False-approval range among 30 assigned |
| --- | ---: | ---: | ---: | ---: | ---: |
| Contact, stated bonus | 3 | 16 | 0 | 11 | 3–14 |
| No contact, stated bonus | 16 | 1 | 0 | 13 | 16–29 |
| Contact, no stated bonus | 1 | 14 | 4 | 11 | 1–12 |
| No contact, no stated bonus | 3 | 5 | 4 | 18 | 3–21 |

**Table 1.** Completed bad outcomes and worst-case assignment bounds in the stopped neutral-duty text study [E3]. “Check” here means a scripted choice and scripted `FAIL` continuation, not a paid oracle transaction.

Among completed bad cases, unchecked false approval was 3/19 with contact plus stated bonus and 16/17 without contact plus stated bonus. Even if every missing contact-plus-bonus case falsely approved and no missing no-contact-plus-bonus case did, the observed assignment would be 14/30 versus 16/30. This is a property of this **stopped assignment**, not a population estimate or proof that contact protects auditors. Contact also changed message content; some messages disclosed the defect. The arms suffered heavy, uneven missingness, and a later 240-assignment attempt stopped after only 17 rows were indexed and 15 completed [E5]. We cannot claim a stable contact effect or completed 30-run replication.

The observed pattern still changes the mechanism question. A bad verdict did not require a bilateral exchange: 16 completed bad cases in the no-contact bonus arm skipped the scripted check and approved. Conversely, some exposed auditors rejected after receiving an improper request. In all 36 completed bad cases that selected the scripted check, the `FAIL` result was followed by rejection. Eleven of 12 completed good cases were approved. These are descriptive comparisons across selected completed rows; check selection was endogenous and the check was free in execution. They suggest an independent-truth boundary to test, not a measured causal defense effect.

### 4.3 A native local episode connects false approval to two different payments

We then examined two post hoc ORBIT005 arms using one fixed hosted-model pairing: a Nemotron provider and a Dots auditor, with high reasoning requested. Both providers were **researcher prompted** to offer a 10,000-unit base and 20,000-unit `ACCEPT` bonus and to ask the auditor to skip the 4,000-unit check and approve a bad slot. The exact model-authored text reached the auditor's serialized tool input after market acceptance. The auditors accepted the **fee terms**. Neither called `market_check` [E4].

| Event | Duty-prompted arm | Induced compensation-prioritizing arm |
| --- | --- | --- |
| Provider offer delivered | Explicit improper request and unavailable-slot disclosure | Explicit improper request and unavailable-slot disclosure |
| Auditor check | None | None |
| Auditor verdict | `REJECT`, citing provider's admission | Empty-explanation `ACCEPT`; false against private calendar |
| Buyer transfer | None | Application sent 100,000 client→provider units, block 654 |
| Auditor payment | 10,000 base only | Runner invoked native MPP 10,000 base, block 665; 20,000 approval bonus, block 667 |

**Table 2.** ORBIT005 local results. Payment blocks are independently reviewed successful receipts on a fresh local Tempo chain [E4]. Amounts exclude small gas debits.

The duty auditor rejected using the provider's own admission, not a purchased independent check. The induced auditor approved without an explanation. The protected calendar's `FAIL` was hidden from both models. The application tool executed the buyer transfer as a consequence of `market_decide(ACCEPT)`. **After** that transfer, the trusted runner called the native MPP Tempo `charge` path twice to settle the offered base and conditional bonus. The provider model did not autonomously send the payment transactions. There is no demonstrated irrevocable prefunding of the bonus before the verdict. The receipts show that the promised side payment was later executed, not that the payment promise caused the verdict.

Two reviewers agreed that the offer was explicit and exactly exposed, the auditors accepted fee terms, the decisions diverged, and neither auditor explicitly agreed to lie [E4]. The induced arm is therefore a **behavioral, collusion-compatible local case with executed external buyer release and side payment**, not a proven knowing bilateral pact. The changed higher-priority auditor instruction itself directed prioritization of compensation over accuracy; it is a confounder, not an experimental control. One arm per instruction is insufficient for an effect or incidence estimate.

## 5. Mechanism and interpretation

The trace isolates a practical authority boundary. The application's release condition was a valid auditor `ACCEPT`, while independent calendar verification remained optional. A provider-origin approval bonus could be communicated to the auditor under the market workflow. Once the induced auditor approved, the application paid the provider even though the booking was privately bad. Subsequent MPP charges correctly accounted for the auditor's fee and bonus. The payment rail performed its payment function; it did not certify calendar truth.

This produces two analytically different risks. **Coordinated influence** requires a provider request to be delivered and the auditor to act because of it; an explicit textual reply helps establish assent but does not show settled harm. **Unilateral incentive response** requires no delivered provider message if the auditor already sees an outcome-contingent payoff and can avoid checking. The text study's no-contact failures make the second possibility salient, but its unfunded terms and incomplete assignments prevent an economic causal conclusion. The native case establishes an executable consequence chain, while its altered trusted objective prevents attribution to the lower-trust offer.

The distinction matters downstream. If a buyer treats a valid auditor fee receipt as evidence that an audit occurred, it can incorrectly upgrade payment authorization into quality assurance. That specific receipt-reuse behavior was **not** observed in ORBIT005; the observed failure was simpler: the application released on an unchecked verdict. Other protocol-specific controls in this repository show why a valid receipt or mandate for obligation A should not be reused for B and why even a receipt correctly bound to B cannot prove B's work was good [E6]. Those are source-based and scripted application-boundary results, not live cross-protocol collusion findings.

For this booking service, a defensible guard would require a current-booking independent check result before any buyer release, and bind the check, verdict, and payment to the same booking identifier. A guard replay with frozen actions would test enforcement. It would not show how agents adapt when they know the guard exists. Good bookings and false rejections must be counted alongside prevented bad payments, because a guard that halts all commerce is not a useful solution.

## 6. Limits and next experiment

This study is exploratory. The strongest native observation has one duty arm and one induced arm, different trusted auditor instructions, no check in either arm, no pre-verdict proven funding commitment, one fixed model pairing, valueless local assets, and no real buyer. The provider was explicitly instructed by researchers to solicit false approval. We observed exact input exposure, not attention; a false decision against private truth, not a demonstrated lie against known truth; and later settlement, not proof of economic motivation. The neutral text study has no paid check or executed transfers, a high missingness rate, and an unsuccessful prospective replication. No cross-protocol incidence rate or SOTA priority claim follows from these data.

The decisive follow-up is a frozen, one-service MPP calendar experiment. Keep the auditor's neutral duty prompt unchanged. Independently randomize (i) whether a precommitted provider message is delivered and (ii) an **actually prefunded** approval-contingent bonus versus an equally funded verdict-independent fee. Use bad and good fixtures in every cell, hide calendar truth until an affordable **actually debited** check, and preserve the exact provider message in the auditor request. Predefine how invented contingent offers in the flat-fee arm count as treatment violations, while retaining the assigned row in intention-to-treat analysis. Pin at least two model pairings and role swaps as prespecified strata. Record every stop and unattempted assignment.

The primary outcome should be **executed buyer-funded release for a bad booking per assigned pair**. Secondary measures are actual check debit, false verdict, text assent, native side transfer, coalition external gain, correct payment for good bookings, false rejection, latency, and cost. A separate frozen-decision replay can compare release policies without confounding agent behavior with guard visibility. Thirty bad and thirty good bookings per cell are a pilot floor, not evidence of statistical power; a simple 10% versus 30% difference already needs roughly 75 bad pairs per arm before accounting for clustered pairings and missingness [E7]. The study should publish a bounded null if that is what the frozen design yields.

## 7. Conclusion

The present evidence does not prove that a paid auditor knowingly colluded with a provider because of a bribe. It does show why that claim is easy to overstate and why the underlying commerce risk is real in a local system: an induced auditor issued an unchecked false approval, an application released buyer units on that verdict, and a separate provider-funded conditional fee was subsequently paid. Explicit agreement was visible elsewhere only in text runs without settlement, while many text-only false approvals appeared without provider contact. Separating solicitation, exposure, verification, verdict, side payment, and buyer release makes both the failure path and the remaining causal question precise.

## Data and reproducibility

The [canonical research record](../docs/CANONICAL_PAPER_CORE_2026-10-16.md) states the evidence hierarchy and links every stage. The native [ORBIT005 review](../docs/FREE_MPP_NATIVE_ORBIT005_TERMINAL_RCA_2026-10-16.md) links the frozen assignment, raw Inspect traces, exact request hashes, transaction receipts, balances, and independent reviews. The [neutral-duty adjudication](../docs/MPP_NEUTRAL_TWO_REVIEWER_ADJUDICATION_2026-10-16.md) links all assigned/indexed rows and sealed reviewer files. The [profit-framed text review](../docs/MPP_FREE_BAD090_INDEPENDENT_MANUAL_REVIEW_2026-10-16.md) links the first solicitation block. Scripts are in [`scripts/`](../scripts/) and application payment logic in [`src/agent_economic_trust/`](../src/agent_economic_trust/). The evidence cutoff is 16 October 2026. The later Apart sprint scheduled for 23–25 October is not a source of results in this draft.

## References and evidence notes

- **[R1]** User-supplied preliminary manuscript, [*From chat collusion to bribes*](../inputs/From%20chat%20collusion%20to%20bribes.pdf), pp. 4–12. Its raw randomized results were not independently reproduced here.
- **[R2]** SALT NLP, [*Emergent Collusion* project and documentation](https://github.com/SALT-NLP/agent-collusion/blob/5afb2c595aa3eff6b9b829a032f4f117b36ee54d/README.md), pinned source.
- **[R3]** UMass, [Colosseum misalignment metrics and prompted collusion examples](https://github.com/umass-ai-safety/colosseum/tree/b077fe7e2f10566e92156cc12e06ffb2aac54790), pinned source.
- **[R4]** ORBIT, [collusion documentation](https://github.com/wlanderson0/orbit/blob/588b3035f92450ec4f0496bb8b629daa205e84c7/docs/dcop-collusion.md), pinned source.
- **[R5]** UK AI Security Institute, [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai/tree/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee), pinned source.
- **[R6]** SAIL Research Lab, [AgenticPay](https://github.com/SAIL-Research-Lab/AgenticPay/blob/1ff4e1a2686eac6a07ff559df6d50329c6fd9f69/README.md), pinned source.
- **[R7]** Tempo, [MPP Tempo session specification](https://github.com/tempoxyz/mpp-specs/blob/50309c8e67e6d64b5547f1cc354fb327bda1301e/specs/methods/tempo/draft-tempo-session-00.md), pinned source; native local `charge` usage is documented in [E4].
- **[R8]** [ERC-8183 claim settlement](https://github.com/erc-8183/base-contracts/blob/142e669c1fd318486a4628395b629f033654dd06/eip.md#claim-settlement), pinned source.
- **[R9]** [x402 v2 specification](https://github.com/x402-foundation/x402/blob/e95b06661e1a2a8a9a21fce34cc28b9934834650/specs/x402-specification-v2.md), pinned source.
- **[R10]** [AP2 security guidance](https://github.com/google-agentic-commerce/AP2/blob/b4587ac1d055888a73b4b21750973cffba961793/docs/ap2/security_and_privacy_considerations.md), pinned source.
- **[E1]** [Targeted closest-work audit](../docs/FINAL_LITERATURE_GAP_AUDIT_2026-10-16.md). Its historical “current evidence” paragraph predates ORBIT005; use [E4] for that result.
- **[E2]** [MPP BAD090 independent manual review](../docs/MPP_FREE_BAD090_INDEPENDENT_MANUAL_REVIEW_2026-10-16.md).
- **[E3]** [Neutral-duty two-reviewer adjudication](../docs/MPP_NEUTRAL_TWO_REVIEWER_ADJUDICATION_2026-10-16.md).
- **[E4]** [ORBIT005 native trace and receipt review](../docs/FREE_MPP_NATIVE_ORBIT005_TERMINAL_RCA_2026-10-16.md).
- **[E5]** [Neutral-duty replication stop review](../docs/MPP_NEUTRAL_REPLICATION_STOP_REVIEW_2026-10-16.md).
- **[E6]** [Protocol and downstream boundary analysis](../docs/PROTOCOL_POLICY_AND_DOWNSTREAM_RISK_DEEP_DIVE_2026-10-16.md).
- **[E7]** [Causal limits and confirmatory design](../docs/COLLUSION_CAUSAL_LIMITS_AND_CONFIRMATORY_DESIGN_2026-10-16.md).

## Supplement scope and exclusions

The early 32-pair live G4 study, funded-offer pilot, ORBIT001–004 workflow repairs, scripted 30-row ERC rehearsal, historical 84,480 scripted simulations, and stopped ERC/x402/AP2/A2A/ACP exploratory blocks remain in the repository with their own evidence tiers. They are not additional replications of Table 2 and cannot be pooled with Tables 1–2. The [canonical record](../docs/CANONICAL_PAPER_CORE_2026-10-16.md) explains each exclusion. The unresolved provider billing reservations under the USD 50 cap are documented [separately](../docs/BILLING_BLOCKER_READONLY_2026-10-16.md); they are not research outcomes or demonstrated expenditure.
