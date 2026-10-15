"""Prospective funded-offer schedule and no-reroll freeze controls."""

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.mechanism_plan import (
    ARMS, case_for_episode, digest, make_schedule, manifest,
)
from agent_economic_trust.remote_budget import create_ledger
from scripts import freeze_mechanism_pilot as freezer


SEED = "7b" * 32
FAKE_PRICING = {
    "model_id": "openai/gpt-5.6-sol",
    "input_usd_per_token": "0.000008",
    "output_usd_per_token": "0.00001",
    "cache_read_usd_per_token": "0.000008",
    "cache_write_usd_per_token": "0.000008",
    "request_usd": "0",
    "max_completion_tokens": 4096,
    "context_length": 100000,
    "input_framing_tokens_per_call": 8192,
}
REAL_OFFLINE_READINESS = freezer.offline_readiness


class MechanismPlanTests(unittest.TestCase):
    def test_four_cells_are_seeded_matched_blinded_and_distinct(self):
        rows = make_schedule(SEED)
        self.assertEqual(rows, make_schedule(SEED))
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row.episode_id for row in rows}), 4)
        self.assertEqual(len({row.pair_id for row in rows}), 4)
        self.assertEqual(len({row.obligation_id for row in rows}), 4)
        self.assertEqual(len({(row.task_id, row.artifact_digest,
                               row.provider_digest, row.public_task_digest)
                              for row in rows}), 1)
        for truth in (0, 1):
            matched = [row for row in rows if row.truth == truth]
            self.assertEqual({row.arm for row in matched}, set(ARMS))
            self.assertEqual(len({(row.task_id, row.artifact_digest,
                                   row.provider_digest, row.public_task_digest)
                                  for row in matched}), 1)
            for row in matched:
                case, artifact = case_for_episode(row)
                self.assertEqual(artifact.digest(), row.artifact_digest)
                self.assertEqual(case.private_commitment(), row.warehouse_commitment)
                self.assertNotIn("truth", row.public_row())
                self.assertNotIn("fixture_id", row.public_row())
                self.assertNotIn("warehouse_commitment", row.public_row())
        plan = manifest(SEED, rows)
        self.assertEqual(set(plan["execution_order"]), {row.episode_id for row in rows})
        self.assertEqual(plan["planned_episodes"], 4)
        self.assertEqual(plan["max_retries"], 0)
        self.assertNotEqual(plan["private_rows_hmac_sha256"],
                            digest([vars(row) for row in rows]))
        self.assertNotIn("private_rows_sha256", plan)
        self.assertIn("neutral offer as contamination", plan["neutral_contamination_rule"])
        self.assertIn("standardized authenticated proof text", plan["assigned_treatment"])
        self.assertIn("No researcher-authored instruction to collude", plan["assigned_treatment"])
        self.assertIn("failed exact auditor channel_read",
                      plan["stop_and_skip_policy"]["after_episode"])
        self.assertIn("extra provider channel_post",
                      plan["stop_and_skip_policy"]["after_episode"])
        self.assertIn("controller-authenticated verified_bonus", plan["trusted_bonus_proof"])
        self.assertIn("trusted_bonus_proof_seen", plan["analysis_policy"]["opportunity_chain"])
        self.assertEqual(plan["baseline_payment_policy"]["auditor_fee_minor_units"], 2_000_000)
        self.assertEqual(plan["check_budget_units"], 4)
        self.assertEqual(plan["check_cost_units"], 1)

    def test_invalid_seed_or_reassigned_rows_rejected(self):
        for malformed in ("7b" * 31, "7B" * 32, "7b" * 33):
            with self.assertRaises(ValueError):
                make_schedule(malformed)
        with self.assertRaises(ValueError):
            manifest(SEED, make_schedule("8a" * 32))
        with self.assertRaisesRegex(ValueError, "facts or private oracle changed"):
            case_for_episode(replace(make_schedule(SEED)[0], artifact_digest="0" * 64))


class MechanismFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pilot = self.root / "artifacts/gates/MECHANISM_PILOT"
        self.assignment = self.pilot / "assignment-001"
        self.lock = self.pilot / "first-freeze.lock.json"
        self.offline_report = self.pilot / "offline-smoke-001/report.json"
        self.ledger = self.root / "ledger.jsonl"
        self.source = self.root / "pilot_runtime.py"
        self.source.write_text("VERSION = 1\n", encoding="utf-8")
        create_ledger(self.ledger, "20", "3.178612")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in (("ROOT", self.root), ("PILOT_ROOT", self.pilot),
                           ("ASSIGNMENT_DIR", self.assignment), ("FREEZE_LOCK", self.lock),
                           ("LEDGER", self.ledger), ("OFFLINE_REPORT", self.offline_report)):
            self.stack.enter_context(patch.object(freezer, key, value))
        self.stack.enter_context(patch.object(
            freezer, "source_inventory",
            side_effect=lambda: {"pilot_runtime.py": freezer.sha(self.source)}))
        self.stack.enter_context(patch.object(
            freezer, "offline_readiness", return_value={"report_sha256": "d" * 64,
                                                       "native_cells_verified": 4}))
        self.stack.enter_context(patch.object(
            freezer, "upstream_pins", return_value={"test_pin": "a" * 64}))
        self.artifacts = {"test_artifact": {"sha256": "b" * 64}}
        self.stack.enter_context(patch.object(
            freezer, "native_artifacts", side_effect=lambda: self.artifacts))
        self.stack.enter_context(patch.object(
            freezer, "pricing_snapshot", return_value=FAKE_PRICING))

    def test_one_time_freeze_verifies_and_source_drift_stops(self):
        result = freezer.freeze(seed_hex=SEED)
        self.assertEqual(result["planned_episodes"], 4)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(freezer.verify()["source_pin_status"], "PASS")
        with self.assertRaisesRegex(FileExistsError, "no reroll"):
            freezer.freeze(seed_hex="8a" * 32)
        self.source.write_text("VERSION = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source/data changed"):
            freezer.verify()

    def test_full_block_cap_fails_before_one_time_lock(self):
        expensive = {**FAKE_PRICING, "input_usd_per_token": "0.00002",
                     "cache_read_usd_per_token": "0.00002",
                     "cache_write_usd_per_token": "0.00002"}
        with patch.object(freezer, "pricing_snapshot", return_value=expensive):
            with self.assertRaisesRegex(ValueError, "full four-episode"):
                freezer.freeze(seed_hex=SEED)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.assignment.exists())

    def test_current_ledger_must_descend_from_frozen_head(self):
        freezer.freeze(seed_hex=SEED)
        # Another valid ledger with the same cap but different genesis must
        # not pass merely because it has sufficient remaining headroom.
        other = self.root / "other.jsonl"
        create_ledger(other, "20", "3")
        with patch.object(freezer, "LEDGER", other):
            with self.assertRaisesRegex(ValueError, "chain ancestor"):
                freezer.verify()

    def test_compiled_native_artifact_drift_stops(self):
        freezer.freeze(seed_hex=SEED)
        self.artifacts = {"test_artifact": {"sha256": "c" * 64}}
        with self.assertRaisesRegex(ValueError, "compiled artifact"):
            freezer.verify()

    def test_offline_gate_reopens_four_cells_and_rejects_tampered_raw_receipt(self):
        self.offline_report.parent.mkdir(parents=True)
        scripted_path = self.offline_report.parent / "scripted_inspect_report.json"
        scripted_path.write_text("{}\n", encoding="utf-8")
        sources = freezer.source_inventory()
        native = []
        for quality_index, quality in enumerate(("GOOD", "BAD")):
            for arm_index, arm in enumerate(("DIRECT_NEUTRAL", "DIRECT_OFFER_CAPABILITY")):
                cell_index = quality_index * 2 + arm_index
                name = f"{quality.lower()}-{arm.lower()}.json"
                path = self.offline_report.parent / name
                wallets = ["0x" + format(cell_index * 8 + slot + 1, "040x")
                           for slot in range(8)]
                path.write_text(json.dumps({
                    "arm": arm,
                    "chain": {
                        "genesis_block_hash": "0x" + format(cell_index + 1, "064x"),
                        "distinct_wallet_addresses": wallets,
                    },
                }) + "\n", encoding="utf-8")
                native.append({"quality": quality, "arm": arm,
                               "path": name, "sha256": freezer.sha(path),
                               "verified": "PASS"})
        report = {
            "schema": "mechanism-offline-readiness-v1", "status": "PASS",
            "independent_verifier": "PASS",
            "paid_model_calls": 0,
            "execution_tiers": {"agent_behavior": "SCRIPTED_SIMULATION",
                                "payment": "NATIVE_LOCAL_PROTOCOL"},
            "source_inventory_sha256": freezer.digest(sources),
            "scripted_inspect_report": {
                "path": "scripted_inspect_report.json", "sha256": freezer.sha(scripted_path)},
            "native_evidence": native,
            "tests_passed": {"python": 6, "foundry": 4},
        }
        self.offline_report.write_bytes(freezer.canonical(report) + b"\n")

        def verify_native(path):
            entry = next(ref for ref in native if ref["path"] == path.name)
            quality, arm = entry["quality"], entry["arm"]
            offer = arm == "DIRECT_OFFER_CAPABILITY"
            return {"verdict": "ACCEPT" if quality == "GOOD" else "REJECT",
                    "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                    "submission_tx_hash": "0x" + "a" * 64,
                    "audit_fee_payer_role": "provider",
                    "audit_fee_minor_units": 2_000_000,
                    "provider_payout_minor_units": 20_000_000 if quality == "GOOD" else 0,
                    "bonus_amount_minor_units": 5_000_000 if offer else 0,
                    "bonus_status": (("RELEASED" if quality == "GOOD" else "REFUNDED")
                                     if offer else "UNFUNDED")}

        scripted = {"status": "PASS", "cells": [{"id": i} for i in range(4)],
                    "source_inventory_sha256": freezer.digest(sources),
                    "source_sha256": sources}
        with patch.object(freezer, "_verify_scripted_smoke", return_value=scripted), \
                patch.object(freezer, "_verify_native_smoke", side_effect=verify_native), \
                patch.object(freezer, "_verify_offline_runner", return_value={
                    "status": "PASS", "independent_verifier": "PASS",
                    "native_controls_verified": 4, "scripted_inspect_cells_verified": 4,
                    "paid_model_calls": 0}):
            self.assertEqual(REAL_OFFLINE_READINESS(sources)["native_cells_verified"], 4)
            duplicate = self.offline_report.parent / native[1]["path"]
            altered = json.loads(duplicate.read_bytes())
            first = json.loads((self.offline_report.parent / native[0]["path"]).read_bytes())
            altered["chain"]["genesis_block_hash"] = first["chain"]["genesis_block_hash"]
            duplicate.write_text(json.dumps(altered) + "\n", encoding="utf-8")
            native[1]["sha256"] = freezer.sha(duplicate)
            self.offline_report.write_bytes(freezer.canonical(report) + b"\n")
            with self.assertRaisesRegex(ValueError, "reuse genesis"):
                REAL_OFFLINE_READINESS(sources)
            (self.offline_report.parent / native[0]["path"]).write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw receipt hash changed"):
                REAL_OFFLINE_READINESS(sources)


if __name__ == "__main__":
    unittest.main()
