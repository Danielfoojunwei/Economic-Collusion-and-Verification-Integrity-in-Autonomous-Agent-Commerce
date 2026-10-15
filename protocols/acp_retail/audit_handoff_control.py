"""Local ACP mock order and invoice-audit application handoff controls.

The ACP checkout is the pinned specification's example-backed local merchant.
It performs no PSP capture. Its order reference is a caller convention, not an
ACP attestation of audit quality or of a separate ERC-8183 job.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .local_checkout import LocalCheckoutMerchant


SERVICE_ITEM = "independent-invoice-audit-local-v1"


def intent_reference(obligation_id: str, artifact_digest: str) -> str:
    """Commit one caller-defined purchase intent to one task and report."""
    if not isinstance(obligation_id, str) or not obligation_id.strip():
        raise ValueError("purchase obligation is missing")
    if not isinstance(artifact_digest, str) or len(artifact_digest) != 64:
        raise ValueError("report digest must be SHA-256 hex")
    try:
        int(artifact_digest, 16)
    except ValueError as exc:
        raise ValueError("report digest must be SHA-256 hex") from exc
    canonical = json.dumps({"obligation_id": obligation_id,
                            "artifact_digest": artifact_digest.lower()},
                           sort_keys=True, separators=(",", ":")).encode()
    return "audit-intent-sha256:" + sha256(canonical).hexdigest()


def execute_mock_checkout(upstream: Path, *, obligation_id: str,
                          artifact_digest: str) -> dict:
    """Exercise the existing ACP example merchant for a scoped service order."""
    reference = intent_reference(obligation_id, artifact_digest)
    merchant = LocalCheckoutMerchant(upstream)
    suffix = sha256(reference.encode()).hexdigest()[:16]
    session_id, order_id = "checkout_audit_" + suffix, "ord_audit_" + suffix
    for key in ("create_checkout_session_response", "complete_checkout_session_response"):
        example = merchant.examples[key]
        example["id"] = session_id
        item = example["line_items"][0]
        item["item"]["id"] = SERVICE_ITEM
        item["name"] = "Independent invoice audit service"
    order = merchant.examples["complete_checkout_session_response"]["order"]
    order["id"] = order_id
    order["checkout_session_id"] = session_id
    order["client_reference_id"] = reference
    create_request = deepcopy(merchant.examples["create_checkout_session_request"])
    create_request["line_items"][0]["id"] = SERVICE_ITEM
    complete_request = deepcopy(merchant.examples["complete_checkout_session_request"])
    # This is the upstream example's synthetic payment-data token. It stays in
    # the local mock process; no PSP or remote endpoint receives it.
    created = merchant.create("create-" + suffix, create_request)
    completed = merchant.complete("complete-" + suffix, complete_request)
    replayed = merchant.complete("complete-" + suffix, complete_request)
    if (created.status != 200 or completed.status != 200
            or replayed.status != 200 or not replayed.replayed
            or replayed.body != completed.body or merchant.capture_attempts != 1):
        raise ValueError("ACP local mock did not create and replay one order")
    result = {
        "schema": "acp-retail-mock-audit-order-v1",
        "execution_tier": "SCRIPTED_SIMULATION",
        "psp_capture": "NONE; synthetic merchant counter only",
        "intent": {"obligation_id": obligation_id,
                   "artifact_digest": artifact_digest.lower(),
                   "client_reference_id": reference},
        "create_request": create_request,
        "create_response": created.body,
        "complete_request": complete_request,
        "complete_response": completed.body,
        "replay_response": replayed.body,
        "replay_flag": replayed.replayed,
        "synthetic_capture_attempts": merchant.capture_attempts,
    }
    validate_mock_checkout(result, upstream)
    return result


def validate_mock_checkout(evidence: dict, upstream: Path) -> dict:
    """Reopen the official schema and reject a malformed or mismatched order."""
    if (evidence.get("schema") != "acp-retail-mock-audit-order-v1"
            or evidence.get("execution_tier") != "SCRIPTED_SIMULATION"
            or evidence.get("psp_capture") != "NONE; synthetic merchant counter only"
            or evidence.get("synthetic_capture_attempts") != 1
            or evidence.get("replay_flag") is not True):
        raise ValueError("mock checkout provenance or replay differs")
    merchant = LocalCheckoutMerchant(upstream)
    for kind, key in (
        ("CheckoutSessionCreateRequest", "create_request"),
        ("CheckoutSession", "create_response"),
        ("CheckoutSessionCompleteRequest", "complete_request"),
        ("CheckoutSessionWithOrder", "complete_response"),
        ("CheckoutSessionWithOrder", "replay_response"),
    ):
        merchant.validate(kind, evidence[key])
    intent = evidence["intent"]
    expected_ref = intent_reference(intent["obligation_id"], intent["artifact_digest"])
    created, completed = evidence["create_response"], evidence["complete_response"]
    order = completed["order"]
    if (intent["client_reference_id"] != expected_ref
            or created["status"] != "ready_for_payment"
            or completed["status"] != "completed"
            or order["checkout_session_id"] != created["id"]
            or completed["id"] != created["id"]
            or order["client_reference_id"] != expected_ref
            or evidence["replay_response"] != completed
            or evidence["create_request"]["line_items"][0]["id"] != SERVICE_ITEM
            or created["line_items"][0]["item"]["id"] != SERVICE_ITEM
            or completed["line_items"][0]["item"]["id"] != SERVICE_ITEM):
        raise ValueError("completed order is not bound to the local purchase intent")
    return {"order_id": order["id"], "checkout_session_id": completed["id"],
            "client_reference_id": expected_ref}


def dispatch_invoice_verdict(*, checkout: dict, target_obligation_id: str,
                             target_artifact_digest: str, oracle_status: str | None,
                             strict: bool) -> dict:
    """Compare deliberately permissive and task-plus-oracle bound app policies."""
    response = checkout["complete_response"]
    order = response["order"]
    completed = (response["status"] == "completed"
                 and order["checkout_session_id"] == response["id"])
    bound = order["client_reference_id"] == intent_reference(
        target_obligation_id, target_artifact_digest)
    if not completed:
        return {"verdict": "REJECT", "reason": "CHECKOUT_NOT_COMPLETED",
                "order_bound": bound, "oracle_consulted": False}
    if not strict:
        return {"verdict": "ACCEPT", "reason": "SCRIPTED_COMPLETED_ORDER_ONLY",
                "order_bound": bound, "oracle_consulted": False}
    if not bound:
        return {"verdict": "REJECT", "reason": "WRONG_OBLIGATION_OR_ARTIFACT",
                "order_bound": False, "oracle_consulted": False}
    if oracle_status not in {"PASS", "FAIL"}:
        raise ValueError("strict app policy needs an independent oracle")
    return {"verdict": "ACCEPT" if oracle_status == "PASS" else "REJECT",
            "reason": "ORACLE_PASS" if oracle_status == "PASS" else "ORACLE_FAIL",
            "order_bound": True, "oracle_consulted": True}
