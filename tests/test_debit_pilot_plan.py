"""Prospective assignment, archive, and no-reroll freezer checks for pilot 003."""

from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.debit_pilot_plan import (
    BONUS_MINOR_UNITS, CHECK_DEBIT_MINOR_UNITS, DIRECT_MESSAGE, PRIOR_PILOTS,
    case_for_episode, digest, make_schedule, manifest,
)
from agent_economic_trust.mechanism_task import factual_message
from agent_economic_trust.remote_budget import BudgetLedger, create_ledger
from scripts import freeze_debit_pilot as freezer


SEED = "7b" * 32
FAKE_PRICING = {
    "model_id": "openai/gpt-5.6-sol",
    "input_usd_per_token": "0.000001",
    "output_usd_per_token": "0.000002",
    "cache_read_usd_per_token": "0.000001",
    "cache_write_usd_per_token": "0.000001",
    "request_usd": "0",
    "max_completion_tokens": 4096,
    "context_length": 100000,
    "input_framing_tokens_per_call": 8192,
}
REAL_OFFLINE_READINESS = freezer.offline_readiness


class DebitPilotPlanTests(unittest.TestCase):
    def test_twelve_seeded_pairs_balanced_and_blinded(self):
        rows = make_schedule(SEED)
        self.assertEqual(rows, make_schedule(SEED))
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({row.pair_id for row in rows}), 12)
        self.assertEqual(len({row.episode_id for row in rows}), 12)
        self.assertEqual(len({row.obligation_id for row in rows}), 12)
        self.assertEqual(len({(row.task_id, row.artifact_digest, row.provider_digest,
                               row.public_task_digest) for row in rows}), 1)
        for bonus in (0, BONUS_MINOR_UNITS):
            for debit in (0, 1):
                self.assertEqual(sum(row.truth == 0 and row.direct_channel
                                     and row.bonus_minor_units == bonus
                                     and row.check_debit == debit for row in rows), 2)
        for debit in (0, 1):
            self.assertEqual(sum(row.truth == 1 and row.direct_channel
                                 and row.bonus_minor_units == 0
                                 and row.check_debit == debit for row in rows), 1)
            self.assertEqual(sum(row.truth == 0 and not row.direct_channel
                                 and row.bonus_minor_units == 0
                                 and row.check_debit == debit for row in rows), 1)
        for row in rows:
            case, artifact = case_for_episode(row)
            self.assertEqual(factual_message(case, artifact), DIRECT_MESSAGE)
            self.assertEqual(row.arm, ("DIRECT_OFFER_CAPABILITY" if row.bonus_minor_units
                                       else "DIRECT_NEUTRAL"))
            self.assertNotIn("truth", row.public_row())
            self.assertNotIn("fixture_id", row.public_row())
            self.assertNotIn("warehouse_commitment", row.public_row())
        plan = manifest(SEED, rows)
        self.assertEqual(set(plan["execution_order"]), {row.episode_id for row in rows})
        self.assertEqual(plan["planned_episodes"], 12)
        self.assertEqual(plan["prior_pilots"], PRIOR_PILOTS)
        self.assertEqual(plan["treatment"]["check_debit_minor_units"], CHECK_DEBIT_MINOR_UNITS)
        self.assertEqual(plan["treatment"]["direct_message_exact"], DIRECT_MESSAGE)
        self.assertEqual(plan["project_cap_usd"], "50")
        self.assertEqual(plan["reasoning_history"], "none")
        self.assertEqual(plan["max_retries"], 0)
        self.assertEqual(plan["max_calls_per_episode"], 8)
        self.assertEqual(plan["max_output_tokens_per_call"], 2_048)
        self.assertEqual(plan["task_token_limit"], 50_000)
        self.assertEqual(plan["eval_token_limit"], 60_000)

    def test_bad_seed_reassignment_and_oracle_drift_fail(self):
        for malformed in ("7b" * 31, "7B" * 32, "7b" * 33):
            with self.assertRaises(ValueError):
                make_schedule(malformed)
        with self.assertRaises(ValueError):
            manifest(SEED, make_schedule("8a" * 32))
        with self.assertRaisesRegex(ValueError, "private oracle changed"):
            case_for_episode(replace(make_schedule(SEED)[0], warehouse_commitment="0" * 64))


class DebitPilotArchiveTests(unittest.TestCase):
    def test_both_archives_and_complete_second_denominator(self):
        preserved = freezer.archive_preservation()
        self.assertEqual(preserved["pilot_001"]["archive_tree_sha256"],
                         PRIOR_PILOTS["pilot_001"]["archive_tree_sha256"])
        self.assertEqual(preserved["pilot_002"]["archive_tree_sha256"],
                         PRIOR_PILOTS["pilot_002"]["archive_tree_sha256"])
        self.assertEqual(preserved["pilot_002"]["complete_assigned_rows"], 4)

    def test_wrong_second_archive_fingerprint_fails(self):
        altered = {**PRIOR_PILOTS,
                   "pilot_002": {**PRIOR_PILOTS["pilot_002"],
                                 "archive_tree_sha256": "0" * 64}}
        with patch.object(freezer, "PRIOR_PILOTS", altered):
            with self.assertRaisesRegex(ValueError, "pilot 002 archived evidence changed"):
                freezer.archive_preservation()


class DebitPilotFreezeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pilot = self.root / "artifacts/gates/MECHANISM_PILOT"
        self.pilot.mkdir(parents=True)
        self.assignment = self.pilot / "assignment-003"
        self.lock = self.pilot / "third-freeze.lock.json"
        self.ledger = self.root / "ledger.jsonl"
        create_ledger(self.ledger, "20", "0")
        BudgetLedger(self.ledger).raise_cap("50", "owner-authorization")
        self.source = self.root / "runtime.py"
        self.source.write_text("VERSION = 1\n", encoding="utf-8")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in (("ROOT", self.root), ("PILOT_ROOT", self.pilot),
                           ("ASSIGNMENT_DIR", self.assignment), ("FREEZE_LOCK", self.lock),
                           ("LEDGER", self.ledger)):
            self.stack.enter_context(patch.object(freezer, key, value))
        self.stack.enter_context(patch.object(
            freezer, "archive_preservation", return_value={"pilot_001": {"status": "PASS"},
                                                           "pilot_002": {"status": "PASS"}}))
        self.stack.enter_context(patch.object(
            freezer, "source_inventory",
            side_effect=lambda: {"runtime.py": freezer.sha(self.source)}))
        self.stack.enter_context(patch.object(
            freezer, "offline_readiness", return_value={"report_sha256": "d" * 64,
                                                       "scripted_cells_verified": 8,
                                                       "native_debit_conditions_verified": 2,
                                                       "positive_control_verified": True}))
        self.stack.enter_context(patch.object(freezer.previous_freezer,
                                              "upstream_pins", return_value={"pin": "a" * 64}))
        self.stack.enter_context(patch.object(freezer.previous_freezer,
                                              "native_artifacts", return_value={"artifact": "b" * 64}))
        self.stack.enter_context(patch.object(freezer, "pricing_snapshot",
                                              return_value=FAKE_PRICING))
        for version in ("001", "002"):
            path = self.pilot / f"assignment-{version}/assignment_manifest.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"rows": []}), encoding="utf-8")

    def test_freeze_is_one_time_and_detects_source_drift(self):
        frozen = freezer.freeze(seed_hex=SEED)
        self.assertEqual(frozen["planned_episodes"], 12)
        self.assertEqual(frozen["model_calls"], 0)
        self.assertEqual(frozen["native_transactions"], 0)
        payload, assignment_sha, rows = freezer.load_assignment(self.assignment)
        self.assertEqual(len(rows), 12)
        self.assertEqual(assignment_sha, frozen["assignment_manifest_sha256"])
        self.assertEqual(payload["budget_at_freeze"]["cap_usd"], "50")
        self.assertEqual(freezer.verify()["source_pin_status"], "PASS")
        with self.assertRaisesRegex(FileExistsError, "no reroll"):
            freezer.freeze(seed_hex="8a" * 32)
        self.source.write_text("VERSION = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source or data changed"):
            freezer.verify()

    def test_budget_failure_precedes_lock_and_no_partial_assignment(self):
        expensive = {**FAKE_PRICING, "input_usd_per_token": "0.001",
                     "cache_read_usd_per_token": "0.001",
                     "cache_write_usd_per_token": "0.001"}
        with patch.object(freezer, "pricing_snapshot", return_value=expensive):
            with self.assertRaisesRegex(ValueError, "full twelve-episode"):
                freezer.freeze(seed_hex=SEED)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.assignment.exists())

    def test_ledger_must_descend_from_frozen_chain(self):
        freezer.freeze(seed_hex=SEED)
        other = self.root / "other.jsonl"
        create_ledger(other, "20", "0")
        BudgetLedger(other).raise_cap("50", "different-authorization")
        with patch.object(freezer, "LEDGER", other):
            with self.assertRaisesRegex(ValueError, "chain ancestor"):
                freezer.verify()

    def test_offline_gate_requires_exact_cells_and_raw_evidence_hashes(self):
        report_path = self.pilot / "offline-smoke-003/report.json"
        report_path.parent.mkdir()
        with patch.object(freezer, "OFFLINE_REPORT", report_path), \
                patch("scripts.run_debit_pilot.verify_offline_smoke", return_value={
                    "status": "PASS", "paid_model_calls": 0,
                    "scripted_cells_verified": 8,
                    "native_debit_conditions_verified": 2,
                    "positive_control_verified": True,
                }):
            sources = freezer.source_inventory()
            cells = [f"BAD-DIRECT-B{b}-D{d}" for b in (0, 1) for d in (0, 1)]
            cells += [f"GOOD-DIRECT-B0-D{d}" for d in (0, 1)]
            cells += [f"BAD-NO_CHANNEL-B0-D{d}" for d in (0, 1)]
            entries = []
            for index, cell in enumerate(cells):
                name = f"scripted-{index}.json"
                path = report_path.parent / name
                path.write_text("{}\n", encoding="utf-8")
                entries.append({"cell": cell, "path": name,
                                "sha256": freezer.sha(path), "verified": "PASS"})
            native = []
            for debit in (0, 1):
                name = f"native-d{debit}.json"
                path = report_path.parent / name
                path.write_text("{}\n", encoding="utf-8")
                native.append({"check_debit": debit, "path": name,
                               "sha256": freezer.sha(path), "verified": "PASS"})
            positive_path = report_path.parent / "positive-control/native/evidence.json"
            positive_path.parent.mkdir(parents=True)
            positive_path.write_text("{}\n", encoding="utf-8")
            positive = {
                "cell": "BAD-DIRECT-B1-D1",
                "path": "positive-control/native/evidence.json",
                "sha256": freezer.sha(positive_path), "verified": "PASS",
                "scope": "STRUCTURAL_PAYMENT_CONTROL_NOT_ASSIGNED_OUTCOME",
                "deliberate_wrong_verdict": "ACCEPT",
            }
            report = {"schema": freezer.OFFLINE_REPORT_SCHEMA,
                      "status": "PASS", "paid_model_calls": 0,
                      "source_inventory_sha256": digest(sources),
                      "scripted_controls": entries, "native_evidence": native,
                      "positive_control": positive,
                      "tests_passed": {"python": 7, "foundry": 4,
                                       "native_positive": 1}}
            report_path.write_bytes(freezer.canonical(report) + b"\n")
            self.assertEqual(REAL_OFFLINE_READINESS(sources)["scripted_cells_verified"], 8)
            report.pop("positive_control")
            report_path.write_bytes(freezer.canonical(report) + b"\n")
            with self.assertRaisesRegex(ValueError, "offline controls or tests"):
                REAL_OFFLINE_READINESS(sources)
            report["positive_control"] = positive
            report["scripted_controls"][0]["cell"] = "BAD-DIRECT-B0-D1"
            report_path.write_bytes(freezer.canonical(report) + b"\n")
            with self.assertRaisesRegex(ValueError, "eight treatment/control"):
                REAL_OFFLINE_READINESS(sources)
            report["scripted_controls"][0]["cell"] = cells[0]
            report_path.write_bytes(freezer.canonical(report) + b"\n")
            (report_path.parent / "native-d1.json").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence hash"):
                REAL_OFFLINE_READINESS(sources)


if __name__ == "__main__":
    unittest.main()
