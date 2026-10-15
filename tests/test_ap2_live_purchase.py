"""Scope, replay, amount, payee and raw receipt negatives for AP2 live control."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_economic_trust.ap2_live_purchase import (
    NativeAuditPurchase, validate_ap2_authorization)
from agent_economic_trust.ap2_live_purchase_verifier import verify_native_audit_purchase


AP2_PYTHON = Path("/workspace/upstreams/ap2-w15/.venv/bin/python")
ROOT = Path(__file__).resolve().parents[1]
OBLIGATION = "invoice-test-afe214c71809"
ARTIFACT = "12" * 32
OTHER = "invoice-test-2e79fb823a05"


class Ap2LivePurchaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="ap2-live-test-", dir="/tmp"))
        cls.auth = cls.root / "authorization.json"
        subprocess.run([
            str(AP2_PYTHON), "-m", "scripts.ap2_live_authorization", "issue",
            "--obligation", OBLIGATION, "--artifact-digest", ARTIFACT,
            "--cross-obligation", OTHER, "--output", str(cls.auth),
        ], cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
           check=True, timeout=45)
        cls.record = json.loads(cls.auth.read_text())
        cls.issuer = cls.record["trusted_issuer_public_sha256"]

    def test_valid_signed_scope_and_wrong_obligation_or_issuer(self):
        self.assertEqual(validate_ap2_authorization(
            self.auth, obligation_id=OBLIGATION, artifact_digest=ARTIFACT,
            issuer_public_sha256=self.issuer)["payment_execution"], "NONE")
        for changed in ({"obligation_id": OTHER},
                        {"artifact_digest": "34" * 32},
                        {"issuer_public_sha256": "00" * 32}):
            kwargs = dict(obligation_id=OBLIGATION, artifact_digest=ARTIFACT,
                          issuer_public_sha256=self.issuer)
            kwargs.update(changed)
            with self.assertRaisesRegex(ValueError, "scope differs"):
                validate_ap2_authorization(self.auth, **kwargs)

    def test_amount_and_payee_tampering_are_rejected(self):
        for name, field, changed in (
            ("amount", "amount_minor", 2501),
            ("payee", "payee_id", "other-merchant"),
        ):
            record = deepcopy(self.record)
            record["proposed_payment"][field] = changed
            path = self.root / f"tampered-{name}.json"
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "scope differs"):
                validate_ap2_authorization(
                    path, obligation_id=OBLIGATION, artifact_digest=ARTIFACT,
                    issuer_public_sha256=self.issuer)

    def test_one_purchase_then_replay_rejected_and_raw_receipt_verified(self):
        output = self.root / "native"
        with NativeAuditPurchase(
            output, self.auth, obligation_id=OBLIGATION,
            artifact_digest=ARTIFACT, issuer_public_sha256=self.issuer,
        ) as controller:
            receipt = controller.buy()
            self.assertEqual(receipt["amount_minor"], 25_000_000)
            with self.assertRaisesRegex(ValueError, "already used"):
                controller.buy()
        verified = verify_native_audit_purchase(
            output, self.auth, expected_obligation_id=OBLIGATION,
            expected_artifact_digest=ARTIFACT,
            expected_issuer_public_sha256=self.issuer)
        self.assertEqual(verified["status"], "PASS")
        evidence = json.loads((output / "native-audit-purchase.json").read_text())
        from hashlib import sha256

        def write_purchase(value):
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            (output / "native-audit-purchase.json").write_bytes(raw + b"\n")
            (output / "native-audit-purchase.sha256").write_text(
                f"{sha256(raw).hexdigest()}  native-audit-purchase.json\n")

        for variant in ("forged_sender", "reversed_blocks", "forged_deployment"):
            forged = deepcopy(evidence)
            if variant == "forged_sender":
                tx = forged["transactions"][-1]
                tx["actor_role"] = "evaluator"
                tx["raw_transaction"]["from"] = forged["roles"]["evaluator"]
                tx["raw_receipt"]["from"] = forged["roles"]["evaluator"]
                forged["raw_transaction"] = deepcopy(tx["raw_transaction"])
                forged["raw_receipt"] = deepcopy(tx["raw_receipt"])
            elif variant == "reversed_blocks":
                tx = forged["transactions"][-1]
                tx["raw_transaction"]["blockNumber"] = "0x0"
                tx["raw_receipt"]["blockNumber"] = "0x0"
                forged["raw_transaction"] = deepcopy(tx["raw_transaction"])
                forged["raw_receipt"] = deepcopy(tx["raw_receipt"])
            else:
                forged["transactions"][0]["raw_transaction"]["input"] = "0x00"
            write_purchase(forged)
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                verify_native_audit_purchase(
                    output, self.auth, expected_obligation_id=OBLIGATION,
                    expected_artifact_digest=ARTIFACT,
                    expected_issuer_public_sha256=self.issuer)
        write_purchase(evidence)
        evidence["local_amount_minor"] = 25_000_001
        write_purchase(evidence)
        with self.assertRaisesRegex(ValueError, "amount or payee mapping"):
            verify_native_audit_purchase(
                output, self.auth, expected_obligation_id=OBLIGATION,
                expected_artifact_digest=ARTIFACT,
                expected_issuer_public_sha256=self.issuer)


if __name__ == "__main__":
    unittest.main()
