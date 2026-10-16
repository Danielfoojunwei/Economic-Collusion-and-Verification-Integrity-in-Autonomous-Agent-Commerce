"""Small local ACP checkout contract probe using the released upstream schema.

This merchant has no payment provider. Its completion operation records a
synthetic order and an attempted capture count so idempotency can be checked.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


SPEC_VERSION = "2026-04-17"
SPEC_COMMIT = "7fdd78df677a94dce04c770644b0fbbb1401272b"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Response:
    status: int
    body: dict
    replayed: bool = False


class LocalCheckoutMerchant:
    """Probe ACP checkout and idempotency state with upstream example payloads."""

    def __init__(self, upstream: Path):
        upstream = upstream.resolve()
        schema_file = upstream / "spec" / SPEC_VERSION / "json-schema" / "schema.agentic_checkout.json"
        example_file = upstream / "examples" / SPEC_VERSION / "examples.agentic_checkout.json"
        self.schema_bytes = schema_file.read_bytes()
        self.example_bytes = example_file.read_bytes()
        self.schema = json.loads(self.schema_bytes)
        self.examples = json.loads(self.example_bytes)
        self.cache: dict[tuple[str, str], tuple[str, Response]] = {}
        self.session: dict | None = None
        self.capture_attempts = 0

    def validate(self, kind: str, value: object) -> None:
        Draft202012Validator({**self.schema, "$ref": f"#/$defs/{kind}"}).validate(value)

    def _post(self, endpoint: str, key: str | None, payload: dict, action) -> Response:
        if not key or len(key) > 255:
            return Response(400, {"code": "idempotency_key_required"})
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        cache_key = (endpoint, key)
        prior = self.cache.get(cache_key)
        if prior:
            if prior[0] != digest:
                return Response(422, {"code": "idempotency_conflict"})
            return Response(prior[1].status, deepcopy(prior[1].body), replayed=True)
        response = action()
        if response.status < 500:
            self.cache[cache_key] = (digest, response)
        return response

    def create(self, key: str | None, payload: dict) -> Response:
        def action() -> Response:
            self.validate("CheckoutSessionCreateRequest", payload)
            if self.session is not None:
                return Response(409, {"code": "session_exists"})
            self.session = deepcopy(self.examples["create_checkout_session_response"])
            self.validate("CheckoutSession", self.session)
            return Response(200, deepcopy(self.session))

        return self._post("create", key, payload, action)

    def complete(self, key: str | None, payload: dict) -> Response:
        def action() -> Response:
            self.validate("CheckoutSessionCompleteRequest", payload)
            if self.session is None:
                return Response(404, {"code": "session_not_found"})
            if self.session["status"] != "ready_for_payment":
                return Response(405, {"code": "session_not_completable"})
            # Synthetic counter only; no payment credential is exercised.
            self.capture_attempts += 1
            self.session = deepcopy(self.examples["complete_checkout_session_response"])
            self.validate("CheckoutSessionWithOrder", self.session)
            return Response(200, deepcopy(self.session))

        return self._post("complete", key, payload, action)

    def cancel(self, key: str | None, payload: dict | None = None) -> Response:
        payload = payload or {}

        def action() -> Response:
            self.validate("CancelSessionRequest", payload)
            if self.session is None:
                return Response(404, {"code": "session_not_found"})
            if self.session["status"] in {"canceled", "completed"}:
                return Response(405, {"code": "session_not_cancelable"})
            self.session = deepcopy(self.examples["cancel_checkout_session_response"])
            self.validate("CheckoutSession", self.session)
            return Response(200, deepcopy(self.session))

        return self._post("cancel", key, payload, action)
