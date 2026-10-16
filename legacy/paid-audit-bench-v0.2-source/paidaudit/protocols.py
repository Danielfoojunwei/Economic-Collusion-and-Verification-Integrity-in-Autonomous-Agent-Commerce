"""Offline *protocol-shaped* state machines.

These are NOT deployed SDKs, Solidity contracts, cryptographic validators, conformance
implementations, or evidence of bugs in named standards. All money is fictional.
"""
from __future__ import annotations
from dataclasses import dataclass
from .model import Ledger, Trace, Task, Judgment, PaymentResult, ProtocolViolation, digest
from .tasks import evaluate

@dataclass(frozen=True)
class ProtocolInfo:
    name: str
    kind: str
    foundation: str
    payment_stage: str # 'before_service' | 'after_service' | 'on_evaluator_approval'
    source: str
    note: str
    local_status: str = "protocol-shaped simulation only"

PROTOCOLS: dict[str,ProtocolInfo] = {i.name:i for i in [
    ProtocolInfo("x402_v2", "payment rail", "x402", "after_service", "https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md", "HTTP 402 + PAYMENT-REQUIRED/PAYMENT-SIGNATURE; models v2 authorization flow, not every scheme"),
    ProtocolInfo("x402_v2_upfront", "payment rail", "x402", "before_service", "https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md", "x402 v2 paymentFlow=upfront; simulated commit before execution, not an EVM transaction"),
    ProtocolInfo("x402_v2_escrow", "payment rail", "x402", "after_service", "https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md", "x402 v2 paymentFlow=escrow deposit before resource, final charge after execution; simulated scheme"),
    ProtocolInfo("mpp", "payment rail", "MPP", "before_service", "https://github.com/tempoxyz/mpp-specs", "HTTP 402 WWW-Authenticate: Payment / Authorization: Payment; modeled charge route"),
    ProtocolInfo("ap2_v02", "payment authorization", "AP2", "before_service", "https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/specification.md", "Simulated mandate/receipt flow; genuine SD-JWT and ES256 omitted"),
    ProtocolInfo("ucp_ap2", "commerce composition", "AP2", "before_service", "https://github.com/universal-commerce-protocol/ucp", "UCP checkout orchestration over simulated AP2 mandates, not standalone payment rail"),
    ProtocolInfo("erc8183_draft", "work escrow", "ERC-8183", "on_evaluator_approval", "https://eips.ethereum.org/EIPS/eip-8183", "Client funds escrow; provider submits; single evaluator completes/rejects; no real EVM"),
    ProtocolInfo("virtuals_acp_v2", "work escrow", "ERC-8183", "on_evaluator_approval", "https://whitepaper.virtuals.io/acp/acp-changelogs", "Virtuals Agent Commerce Protocol v2; modeled ERC-8183 jobs and hooks"),
    ProtocolInfo("openai_stripe_acp", "retail checkout", "OpenAI/Stripe ACP", "before_service", "https://github.com/agentic-commerce-protocol/agentic-commerce-protocol", "OpenAI/Stripe ACP 2026-04-17 checkout; not Virtuals ACP, no auditor escrow"),
    ProtocolInfo("a2a_x402", "transport + payment", "x402", "after_service", "https://github.com/a2aproject/A2A", "A2A v1.0 task transport with separate x402 v2 rail; A2A itself is not payment"),
    ProtocolInfo("a2a_erc8183", "transport + escrow", "ERC-8183", "on_evaluator_approval", "https://github.com/a2aproject/A2A", "A2A v1.0 messages with ERC-8183 evaluator-settled escrow"),
    ProtocolInfo("erc8183_erc8004", "identity overlay + escrow", "ERC-8183", "on_evaluator_approval", "https://eips.ethereum.org/EIPS/eip-8004", "ERC-8004 draft identity/reputation/validation overlay, not an independent payment rail"),
]}

# Out-of-scope or separately implemented protocols cannot be called 'tested'.
ROADMAP = [
    {"name":"OpenAI/Stripe ACP wire-level merchant integration", "status":"SKIP", "reason":"requires installed reference server, MCP/payment token provider and full checkout schema conformance"},
    {"name":"Virtuals ACP v2 SDK / ERC-8183 EVM", "status":"SKIP", "reason":"requires contract ABI, local Anvil/EVM chain, wallet and signed tx; local state machine only"},
    {"name":"x402 v2 real facilitator", "status":"SKIP", "reason":"requires scheme SDK and valid EIP-712/EIP-3009 or equivalent testnet payment signature"},
    {"name":"MPP real Tempo / Stripe", "status":"SKIP", "reason":"requires official SDK payment-method credential validation and test merchant account"},
    {"name":"AP2 full SD-JWT / VDC", "status":"SKIP", "reason":"requires standards-conformant mandate schemas, signature chains and credential provider"},
    {"name":"Visa Trusted Agent Protocol (TAP)", "status":"SKIP", "reason":"agent identity and transaction trust layer, not standalone escrow payment protocol; network access/partner spec needed"},
    {"name":"Mastercard Agent Pay", "status":"SKIP", "reason":"network/tokenization product; integration would require provider credentials and documented test environment"},
    {"name":"L402 / Lightning", "status":"SKIP", "reason":"distinct Lightning payment method; requires local regtest Lightning node and macaroon check"},
    {"name":"A402 research prototype", "status":"SKIP", "reason":"research architecture requires TEE/channel setup; not an interoperable baseline without its implementation"},
    {"name":"ASP/RAILS/TessPay research proposals", "status":"SKIP", "reason":"research mechanisms, separate experimental track from deployed payment standard comparisons"},
    {"name":"ERC-8004 standalone payment", "status":"NOT_PAYMENT", "reason":"identity/reputation/validation registry, explicitly states payments are orthogonal"},
    {"name":"A2A standalone payment", "status":"NOT_PAYMENT", "reason":"agent communication and tasks standard, not money movement"},
]

class Session:
    """State transition simulator with guardrails and observability.

    A 'verdict' is the agent's decision, not necessarily correct. The protocol does
    not access hidden ground truth. 'objective_recheck' is a non-native, separately
    funded verifier that *can* access the benchmark's safe deterministic oracle.
    """
    def __init__(self, protocol: str, task: Task, trial_id: str, fault: str="none"):
        if protocol not in PROTOCOLS:
            raise ProtocolViolation("unknown protocol")
        self.info = PROTOCOLS[protocol]
        self.task = task
        self.id = trial_id
        self.ledger = Ledger()
        self.trace = Trace(trial_id)
        self.state = "new"
        self.submitted_hash = ""
        self.payment_key = f"work:{trial_id}"
        self.guard_failed = False
        self.fault = fault
        self.trace.log("bench", "SANDBOX_ONLY", real_money=False, cryptographic_signatures=False, actual_sdk=False)

    @property
    def escrow(self) -> bool:
        return self.info.payment_stage == "on_evaluator_approval"

    def begin(self):
        if self.state != "new":
            raise ProtocolViolation("cannot begin twice")
        n = self.info.name
        self.trace.log("client", "ISSUE_TASK", task_id=self.task.task_id, price_credits=self.task.price)
        if self.fault in ("recipient", "amount") or (self.fault == "expiry" and self.info.payment_stage == "before_service"):
            self.trace.log("protocol_verifier", "PREAUTH_BLOCKED", fault=self.fault, no_money_moved=True)
            self.state = "blocked"
            return
        if n.startswith("a2a_"):
            self.trace.log("a2a", "A2A_TaskCreated", version="1.0.0", message_id=digest(self.id)[:16])
        if n in ("erc8183_erc8004",):
            self.trace.log("erc8004", "identityResolved", agent_id="SIMULATED_ID:provider")
            self.trace.log("erc8004", "validationRequest", request_hash=digest(self.task.specification))
        if n == "ucp_ap2":
            self.trace.log("ucp", "checkout_create", cart_id=digest(self.id)[:12])
        if n in ("x402_v2", "a2a_x402", "x402_v2_upfront", "x402_v2_escrow"):
            payment_flow = ("upfront" if n=="x402_v2_upfront" else "escrow" if n=="x402_v2_escrow" else "authorization")
            self.trace.log("resource_server", "HTTP_402", **{
                "PAYMENT-REQUIRED": {"x402Version":2,
                    "resource":{"url": "https://example.invalid/task/"+self.task.task_id},
                    "accepts":[{"scheme":"exact","network":"eip155:84532",
                      "amount":str(self.task.price),"asset":"SIM_CREDITS_NOT_ERC20",
                      "payTo":"sandbox:provider","maxTimeoutSeconds":60,
                      "extra":{"paymentFlow":payment_flow}}],"extensions":{}}})
            self.trace.log("client", "PAYMENT-SIGNATURE", credential="MOCK_NOT_CRYPTOGRAPHIC", nonce=digest(self.id)[:16])
            if payment_flow=="authorization":
                self.trace.log("facilitator", "verify_authorization", result="mock-valid", settled=False)
            elif payment_flow=="upfront":
                self.ledger.transfer("client", "provider", self.task.price, self.payment_key)
                self.trace.log("facilitator", "settle_upfront", success=True, mock_only=True)
            else:
                self.ledger.transfer("client", "escrow", self.task.price, self.payment_key+":deposit")
                self.trace.log("facilitator", "settle_deposit", success=True, mock_only=True,
                               escrow_is_a_synthetic_payment_flow_not_erc8183=True)
        elif n == "mpp":
            self.trace.log("server", "HTTP_402", header="WWW-Authenticate: Payment", method="charge", id=self.id)
            self.trace.log("client", "Authorization: Payment", credential="MOCK_NOT_CRYPTOGRAPHIC")
            self.ledger.transfer("client", "provider", self.task.price, self.payment_key)
            self.trace.log("server", "mpp_charge_complete", credits=self.task.price, settled=True)
        elif n in ("ap2_v02", "ucp_ap2"):
            self.trace.log("trusted_surface", "OPEN_CHECKOUT_MANDATE", vct="mandate.checkout.open.1", authorized_constraints={"amount_max":self.task.price})
            self.trace.log("merchant", "CHECKOUT_JWT", checkout_digest=digest({"task":self.task.task_id,"price":self.task.price}), signed=False)
            self.trace.log("shopping_agent", "CLOSED_CHECKOUT_MANDATE", vct="mandate.checkout.1")
            self.trace.log("shopping_agent", "CLOSED_PAYMENT_MANDATE", vct="mandate.payment.1", amount=self.task.price)
            self.trace.log("credential_provider", "CHECKOUT_PAYMENT_MANDATES_VALIDATED", verification="mock-only")
            self.ledger.transfer("client", "provider", self.task.price, self.payment_key)
            self.trace.log("merchant_processor", "PAYMENT_RECEIPT", reference=self.payment_key, settled=True)
        elif n == "openai_stripe_acp":
            self.trace.log("commerce", "create_checkout_session", version="2026-04-17", items=[self.task.task_id])
            self.trace.log("commerce", "set_payment_handler", token="MOCK_NOT_NETWORK_TOKEN")
            self.ledger.transfer("client", "provider", self.task.price, self.payment_key)
            self.trace.log("commerce", "checkout_complete", receipt=self.payment_key)
        elif self.escrow:
            self.trace.log("erc8183", "createJob", provider="provider", evaluator="verifier", expiredAt=100)
            self.trace.log("erc8183", "setBudget", amount=self.task.price)
            if n == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "beforeAction", hook_target="fund")
            self.ledger.transfer("client", "escrow", self.task.price, self.payment_key+":fund")
            self.trace.log("erc8183", "fund", expectedBudget=self.task.price, status="Funded")
            if n == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "afterAction", hook_target="fund")
        else:
            raise ProtocolViolation(f"missing session implementation for {n}")
        self.state = "begun"

    def submit(self, artifact: dict, caller:str="provider"):
        if caller != "provider":
            raise ProtocolViolation("only assigned provider may submit work")
        if self.state != "begun":
            raise ProtocolViolation("submit before begin / twice")
        self.submitted_hash = digest(artifact)
        self.trace.log("provider", "WORK_SUBMITTED", task_id=self.task.task_id,
                       deliverable_digest=self.submitted_hash, content=artifact)
        if self.escrow:
            if self.info.name == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "beforeAction", hook_target="submit")
            self.trace.log("erc8183", "submit", deliverable=self.submitted_hash, status="Submitted")
            if self.info.name == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "afterAction", hook_target="submit")
        elif self.info.name in ("x402_v2","a2a_x402","x402_v2_upfront","x402_v2_escrow"):
            self.trace.log("resource_server", "RESOURCE_HANDLER_COMPLETED", response_digest=self.submitted_hash,
                           reply_not_yet_released=True, settlement_pending=True)
        elif self.info.name == "mpp":
            self.trace.log("server", "HTTP_200_resource_response", receipt=self.payment_key)
        else:
            self.trace.log("merchant", "FULFILMENT_RESPONSE", receipt=self.payment_key)
        self.state = "submitted"

    def settle(self, judgment: Judgment, final_artifact: dict, guard: str="none", fault: str="none", caller:str="verifier") -> PaymentResult:
        if self.escrow and caller != "verifier":
            raise ProtocolViolation("only designated evaluator may complete/reject")
        if self.state != "submitted":
            raise ProtocolViolation("settle requires submitted state")
        self.state = "terminal"
        result = PaymentResult(attempted=True)
        self.trace.log("verifier", "VERDICT", accept=judgment.verdict,
                       tool_used=judgment.performed_check, reasons=judgment.reasons,
                       evidence=judgment.claimed_evidence)
        if fault == "swap":
            self.trace.log("provider", "DELIVERABLE_SWAP", initial_digest=self.submitted_hash,
                           final_digest=digest(final_artifact))
        if fault in ("recipient", "amount", "expiry"):
            self.trace.log("attacker", "BAD_PAYMENT_INPUT", type=fault)
            result.blocked = True
            result.reason = {"recipient":"payee != authorized provider",
                             "amount":"requested amount != authorized amount",
                             "expiry":"authorization/job expired"}[fault]
            result.status = "protocol_validation_blocked"
            if self.escrow or self.info.name=="x402_v2_escrow":
                self.ledger.transfer("escrow", "client", self.task.price, self.payment_key+":refund")
                result.refunded = True
                if self.escrow:
                    self.trace.log("erc8183", "claimRefund" if fault=="expiry" else "reject", reason=result.reason)
                else:
                    self.trace.log("facilitator", "SIMULATED_ESCROW_REFUND", reason=result.reason)
            self.trace.log("settlement", "BLOCKED", reason=result.reason)
            return result

        # This is an optional RESEARCH EXTENSION, not native to any listed protocol.
        # It is applied before settlement where the flow permits; otherwise it is post-hoc.
        effective_accept = judgment.verdict
        if guard == "receipt_binding" and judgment.verdict:
            bound = self.submitted_hash == digest(final_artifact)
            self.guard_failed = not bound
            self.trace.log("independent_guard", "RECEIPT_HASH_CHECK", matched=bound,
                           hypothetical_not_native=True, does_not_prove_semantic_quality=True)
            if not bound:
                effective_accept = False
        elif guard == "objective_recheck" and judgment.verdict:
            correct, reason = evaluate(self.task, final_artifact)
            bound = self.submitted_hash == digest(final_artifact)
            self.guard_failed = not(correct and bound)
            self.trace.log("independent_oracle", "OBJECTIVE_RECHECK", conforms=correct,
                           artifact_bound=bound, oracle_detail=reason, hypothetical_not_native=True)
            if self.guard_failed:
                effective_accept = False
        elif guard not in ("none", "receipt_binding", "objective_recheck"):
            raise ProtocolViolation("unknown guard")

        if self.escrow:
            if self.info.name == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "beforeAction", hook_target="complete" if effective_accept else "reject")
            if effective_accept:
                self.ledger.transfer("escrow", "provider", self.task.price, self.payment_key+":settle")
                result.paid = True
                result.status = "Completed"
                self.trace.log("erc8183", "complete", role="designated_evaluator", reason_hash=digest(judgment.claimed_evidence), status="Completed")
            else:
                self.ledger.transfer("escrow", "client", self.task.price, self.payment_key+":refund")
                result.refunded = True
                result.status = "Rejected"
                self.trace.log("erc8183", "reject", role="designated_evaluator", status="Rejected")
            if self.info.name == "virtuals_acp_v2":
                self.trace.log("virtuals_hook", "afterAction", hook_target="complete" if effective_accept else "reject")
            if self.info.name == "erc8183_erc8004":
                self.trace.log("erc8004", "validationResponse", reported_valid=effective_accept,
                               attestation_hash=digest(judgment.claimed_evidence))
                self.trace.log("erc8004", "recordReputation", score=1 if effective_accept else 0)
        elif self.info.payment_stage == "after_service":
            # x402 v2 DEFAULT authorization: verify -> resource handler -> settle -> respond.
            # Optional, non-native application guards can veto BEFORE settlement.
            if effective_accept if guard in ("objective_recheck", "receipt_binding") else True:
                payer_account = "escrow" if self.info.name=="x402_v2_escrow" else "client"
                payment_key = self.payment_key+":final" if self.info.name=="x402_v2_escrow" else self.payment_key
                self.ledger.transfer(payer_account, "provider", self.task.price, payment_key)
                result.paid = True
                result.status = "settled_after_resource_execution"
                self.trace.log("facilitator", "settle", success=True, mock_only=True)
                self.trace.log("resource_server", "HTTP_200_resource_response", settled=True,
                               resource_digest=digest(final_artifact))
            else:
                result.blocked = True
                result.status = "research_guard_blocked_settlement"
                result.reason = "optional verifier veto; not x402 default"
                self.trace.log("facilitator", "settlement_withheld_by_optional_guard", mock_only=True)
                if self.info.name=="x402_v2_escrow":
                    self.ledger.transfer("escrow", "client", self.task.price, self.payment_key+":guard_refund")
                    result.refunded=True
                    self.trace.log("facilitator", "SIMULATED_ESCROW_REFUND",reason="research_guard")
                self.trace.log("resource_server", "HTTP_NOT_SUCCESS", settled=False)
        else:
            # MPP charge, AP2 authorization and retail checkout already paid in begin().
            result.paid = self.payment_key in self.ledger.paid_keys
            result.status = "prepaid_before_verification"
            if self.guard_failed:
                self.trace.log("bench", "POST_PAYMENT_EVIDENCE_FAILURE", reversible=False)
        result.native_verification = False
        if fault == "replay":
            # Real schemes have different nonce/receipt defenses; only local idempotence is tested.
            dst = "provider" if not self.escrow else "provider"
            src = "escrow" if self.escrow or self.info.name=="x402_v2_escrow" else "client"
            key = (self.payment_key+":final" if self.info.name=="x402_v2_escrow" else
                   self.payment_key if not self.escrow else self.payment_key+":settle")
            if key in self.ledger.paid_keys:
                second = self.ledger.transfer(src, dst, self.task.price, key)
                assert not second
                self.trace.log("attacker", "REPLAY_BLOCKED_BY_LEDGER", key=key)
            else:
                self.trace.log("attacker", "REPLAY_ATTEMPT_NO_SETTLEMENT_TO_REPLAY", key=key)
        return result
