"""Fail-closed pre-view funding proof binding without hosted or chain calls."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_economic_trust.bilateral030_native import Bilateral030NativeBridge
from agent_economic_trust import bilateral030_funding_verifier
from agent_economic_trust.bilateral030_plan import (
    BONUS_MINOR, CHANNEL, HIGH_RISK, NO_ACCEPT_BONUS, NO_CONTACT,
    SOL, SONNET, canonical, make_schedule,
)
from agent_economic_trust.bilateral030_task import (
    bilateral030_orbit, confirm_public_funding, public_funding_assignment,
    public_input, role_system_prompts,
)


ROWS = make_schedule("b3" * 32)
HOOK = "0x" + "55" * 20
TX = "0x" + "11" * 32
REPORT = "0x" + "22" * 32
BONUS_TX = "0x" + "33" * 32


def _row(group: str, provider_model: str):
    return next(row for row in ROWS if row.group == group
                and row.provider_model_id == provider_model)


def _prefix(row):
    bonus = bool(row.accept_bonus_minor)
    return {"status": "FUNDED", "obligation_id": row.obligation_id,
            "job_id": 1, "report_digest": REPORT,
            "job_funding_tx_hash": TX, "job_budget_minor": 20_000_000,
            "claim_cumulative_minor": 10_000_000, "evaluator_fee_bp": 1_000,
            "check_price_minor": 200_000, "auditor_endowment_minor": 500_000,
            "bonus_amount_minor": row.accept_bonus_minor,
            "bonus_trigger": "EARLY_APPROVE" if bonus else "NONE",
            "bonus_funded": bonus,
            "bonus_funding_tx_hash": BONUS_TX if bonus else None,
            "bonus_funding_receipt_sha256": (
                sha256(canonical({"kind": "bonus", "id": 1})).hexdigest()
                if bonus else None),
            "hook_address": HOOK if bonus else None}


def _verified(row, prefix, archive_path):
    raw = archive_path.read_bytes()
    archive = json.loads(raw)
    job = next(tx for tx in archive["transactions"] if tx["step"] == "job.fund")
    bonus = next((tx for tx in archive["transactions"]
                  if tx["step"] == "bonus.fund"), None)
    return {"status": "FUNDING_LIVE_CONFIRMED",
            "episode_id": row.episode_id,
            "obligation_id": row.obligation_id,
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id,
            "bonus_minor": row.accept_bonus_minor,
            "job_id": prefix["job_id"], "hook": HOOK,
            "report_digest": prefix["report_digest"],
            "public_prefix_sha256": sha256(canonical(prefix)).hexdigest(),
            "job_funding_tx_hash": prefix["job_funding_tx_hash"],
            "job_funding_receipt_sha256": sha256(canonical(job["raw_receipt"])).hexdigest(),
            "bonus_funding_tx_hash": prefix["bonus_funding_tx_hash"],
            "bonus_funding_receipt_sha256": (
                sha256(canonical(bonus["raw_receipt"])).hexdigest() if bonus else None),
            "archive_transactions_replayed": 19 if row.accept_bonus_minor else 17,
            "live_chain_checked": True,
            "read_only_rpc_source": "loopback",
            "model_view_independently_verified": False,
            "archive_sha256": sha256(raw).hexdigest(),
            "verifier_source_sha256": sha256(Path(
                bilateral030_funding_verifier.__file__).read_bytes()).hexdigest()}


class Bilateral030FundingTaskTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="bilateral030-proof-source-", dir="/tmp")
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)

    def _archive(self, row, prefix):
        path = self.temp / (row.episode_id + ".json")
        transactions = [{"step": "job.fund", "raw_receipt": {"kind": "job", "id": 1}}]
        if row.accept_bonus_minor:
            transactions.append({"step": "bonus.fund",
                                 "raw_receipt": {"kind": "bonus", "id": 1}})
        path.write_text(json.dumps({
            "public_assignment": public_funding_assignment(row),
            "public_prefix": prefix,
            "public_prefix_sha256": sha256(canonical(prefix)).hexdigest(),
            "hook": HOOK, "transactions": transactions}, sort_keys=True) + "\n")
        return path

    def test_direct_live_verifier_and_shared_public_proof(self):
        for group, provider_model in ((HIGH_RISK, SOL), (NO_CONTACT, SONNET),
                                      (NO_ACCEPT_BONUS, SOL)):
            with self.subTest(group=group, provider=provider_model):
                row = _row(group, provider_model)
                prefix = _prefix(row)
                archive = self._archive(row, prefix)
                result = _verified(row, prefix, archive)
                with patch("agent_economic_trust.bilateral030_funding_verifier.verify_funding_file",
                           return_value=result) as verify:
                    proof = confirm_public_funding(row, prefix, archive)
                verify.assert_called_once_with(
                    archive,
                    public_funding_assignment(row), confirm_live=True)
                self.assertEqual(proof["status"], "FUNDING_LIVE_CONFIRMED")
                self.assertEqual(proof["public_prefix_sha256"],
                                 sha256(canonical(prefix)).hexdigest())
                self.assertNotIn("provider_model_id", proof)
                self.assertNotIn("auditor_model_id", proof)
                self.assertEqual(proof["bonus_amount_minor"],
                                 BONUS_MINOR if group != NO_ACCEPT_BONUS else 0)
                public = public_input(row, prefix, proof)
                self.assertIn(json.dumps(proof, sort_keys=True, separators=(",", ":")),
                              public)
                trusted_auditor = public + role_system_prompts(row, prefix, proof)["auditor"]
                for forbidden in ('"truth"', '"group"', '"contact"',
                                  '"buyer_records"', '"purchase_order_amount_cents"',
                                  '"credit_note_amount_cents"', '"net_amount_cents"'):
                    self.assertNotIn(forbidden, trusted_auditor)

    def test_native_builder_refuses_missing_archive_and_scripted_tier_downgrade(self):
        row = _row(HIGH_RISK, SOL)
        prefix = _prefix(row)
        bridge = object.__new__(Bilateral030NativeBridge)
        bridge.hook = HOOK
        with patch.object(Bilateral030NativeBridge, "public_prefix", return_value=prefix), \
             patch.dict(os.environ, {"OPENROUTER_API_KEY": "",
                                  "ALLOW_EXTERNAL_MODEL_CALLS": "false"}):
            with self.assertRaisesRegex(ValueError, "requires live-confirmed"):
                bilateral030_orbit(row, public_funding=prefix, bridge=bridge,
                                   transaction_tier="NATIVE_LOCAL_PROTOCOL")
            with self.assertRaisesRegex(ValueError, "cannot use scripted"):
                bilateral030_orbit(row, public_funding=prefix, bridge=bridge,
                                   transaction_tier="SCRIPTED_SIMULATION")

    def test_archive_only_fake_or_changed_funding_proof_fails_closed(self):
        row = _row(HIGH_RISK, SOL)
        prefix = _prefix(row)
        archive = self._archive(row, prefix)
        good = _verified(row, prefix, archive)
        changes = [
            ("status", "FUNDING_ARCHIVE_REPLAYED"),
            ("status", "FUNDING_LIVE_TEST_REPLAY"),
            ("live_chain_checked", False),
            ("read_only_rpc_source", "injected_test"),
            ("model_view_independently_verified", True),
            ("bonus_minor", 0),
            ("provider_model_id", row.auditor_model_id),
            ("auditor_model_id", row.provider_model_id),
            ("bonus_funding_tx_hash", TX),
            ("bonus_funding_receipt_sha256", "dd" * 32),
            ("job_funding_tx_hash", BONUS_TX),
            ("job_funding_receipt_sha256", "invalid"),
            ("job_funding_receipt_sha256", "dd" * 32),
            ("public_prefix_sha256", "ee" * 32),
            ("archive_sha256", "invalid"),
            ("archive_sha256", "dd" * 32),
            ("verifier_source_sha256", "dd" * 32),
            ("episode_id", "bilateral030-" + "0" * 24),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                bad = deepcopy(good)
                bad[key] = value
                with patch("agent_economic_trust.bilateral030_funding_verifier.verify_funding_file",
                           return_value=bad):
                    with self.assertRaises(ValueError):
                        confirm_public_funding(row, prefix,
                                               archive)

    def test_native_task_binds_attestation_to_both_role_frames(self):
        row = _row(NO_CONTACT, SONNET)
        prefix = _prefix(row)
        bridge = object.__new__(Bilateral030NativeBridge)
        bridge.hook = HOOK
        archive = self._archive(row, prefix)
        with patch.object(Bilateral030NativeBridge, "public_prefix", return_value=prefix), \
             patch("agent_economic_trust.bilateral030_funding_verifier.verify_funding_file",
                   return_value=_verified(row, prefix, archive)) as verify, \
             patch.dict(os.environ, {"OPENROUTER_API_KEY": "",
                                  "ALLOW_EXTERNAL_MODEL_CALLS": "false"}):
            task = bilateral030_orbit(row, public_funding=prefix, bridge=bridge,
                                      transaction_tier="NATIVE_LOCAL_PROTOCOL",
                                      funding_archive_path=archive)
        verify.assert_called_once_with(archive, public_funding_assignment(row),
                                       confirm_live=True)
        sample = task.dataset[0]
        marker = sample.metadata["bilateral030"]
        proof = json.loads(sample.input)["funding_attestation"]
        self.assertEqual(marker["status"],
                         "SCRIPTED_MODEL_NATIVE_PREVIEW_ATTESTED_PROBE")
        self.assertTrue(marker["funding_live_attestation"])
        self.assertFalse(marker["bonus_funding_controller_claim_only"])
        self.assertEqual(marker["funding_attestation_sha256"],
                         sha256(json.dumps(proof, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(proof["archive_sha256"], sha256(archive.read_bytes()).hexdigest())
        agents = sample.metadata["experiment"]["setup"]["agents"]
        self.assertEqual([agent["model"] for agent in agents],
                         ["mockllm/bilateral030-provider-transport",
                          "mockllm/bilateral030-auditor-transport"])
        for agent in agents:
            self.assertIn("independent read-only verifier", agent["system_prompt"])
            self.assertNotIn("controller reports", agent["system_prompt"].lower())
        self.assertNotIn('"contact"', sample.input)
        self.assertNotIn("NO_CONTACT", sample.input)
        self.assertEqual(json.loads(sample.input)["funding_attestation"], proof)

    def test_no_bonus_native_hook_mismatch_fails_closed(self):
        row = _row(NO_ACCEPT_BONUS, SOL)
        prefix = _prefix(row)
        self.assertIsNone(prefix["hook_address"])
        archive = self._archive(row, prefix)
        with patch("agent_economic_trust.bilateral030_funding_verifier.verify_funding_file",
                   return_value=_verified(row, prefix, archive)):
            with self.assertRaisesRegex(ValueError, "native hook differs"):
                confirm_public_funding(row, prefix, archive,
                                       expected_hook="0x" + "66" * 20)

    def test_archive_changed_after_live_verifier_fails_closed(self):
        row = _row(HIGH_RISK, SOL)
        prefix = _prefix(row)
        archive = self._archive(row, prefix)
        verified = _verified(row, prefix, archive)
        changed = json.loads(archive.read_text())
        changed["transactions"][0]["raw_receipt"]["id"] = 2
        archive.write_text(json.dumps(changed, sort_keys=True) + "\n")
        with patch("agent_economic_trust.bilateral030_funding_verifier.verify_funding_file",
                   return_value=verified):
            with self.assertRaises(ValueError):
                confirm_public_funding(row, prefix, archive)


if __name__ == "__main__":
    unittest.main()
