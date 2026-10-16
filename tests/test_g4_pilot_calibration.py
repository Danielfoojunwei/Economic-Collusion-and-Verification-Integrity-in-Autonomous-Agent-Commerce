"""Synthetic checkpoint tests for the read-only G4-to-W19 calibration."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_g4_pilot_calibration as calibration
from agent_economic_trust.w10_factorial import (
    _canonical, analyze_assignments, assignment_manifest, frozen_fixtures,
    make_assignments,
)
from agent_economic_trust.w19_power import PilotCalibration


SEED = "01" * 32


def _write(path: Path, value: bytes) -> str:
    path.write_bytes(value)
    return sha256(value).hexdigest()


class G4PilotCalibrationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        assignment_dir = root / "assignment"
        collection_dir = root / "collection"
        runs_dir = root / "runs"
        for path in (assignment_dir, collection_dir, runs_dir):
            path.mkdir()
        trials = make_assignments(SEED)
        assignment = assignment_manifest(SEED)
        assignment["source_sha256"] = {
            name: calibration._sha(calibration.ROOT / name)
            for name in calibration.collector.SOURCE_FILES
        }
        _write(assignment_dir / "seed.hex", (SEED + "\n").encode())
        _write(assignment_dir / "private_fixtures.json",
               _canonical([fixture.private_row() for fixture in frozen_fixtures()]) + b"\n")
        assignment_sha = _write(assignment_dir / "assignment_manifest.json",
                                _canonical(assignment) + b"\n")
        truth = {fixture.fixture_id: fixture.truth for fixture in frozen_fixtures()}
        records = []
        independently_verified = {}
        for index, trial in enumerate(trials):
            directory = runs_dir / trial.trial_id
            directory.mkdir()
            cost = f"0.{1000 + index:04d}"
            oracle = truth[trial.fixture_id]
            payment = "PAID" if oracle or trial.cell == "111" else "NOT_PAID"
            run_id = f"w10-factorial-{assignment_sha[:12]}-{trial.trial_id}"
            artifact_hashes = {
                name: _write(directory / name, f"synthetic {name} {index}\n".encode())
                for name in ("inspect.eval", "native_evidence.json", "events.jsonl",
                             "episode_outcomes.csv")
            }
            raw = {"trial_id": trial.trial_id, "pair_id": trial.pair_id,
                   "assignment_manifest_sha256": assignment_sha,
                   "status": "COMPLETE"}
            artifact_hashes["trial_record.json"] = _write(
                directory / "trial_record.json", _canonical(raw) + b"\n")
            manifest = {
                "schema_version": "1", "status": "COMPLETE", "run_id": run_id,
                "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
                "payment_tier": "NATIVE_LOCAL_CHAIN", "planned_episodes": 1,
                "completed_episodes": 1,
                "models": [{"id": "openai/gpt-5.6-sol",
                            "kind": "REAL_LLM_REMOTE_APPROVED",
                            "reasoning_effort": "high"}],
                "randomization": {
                    "assignment_manifest_sha256": assignment_sha,
                    "trial_id": trial.trial_id, "pair_id": trial.pair_id,
                    "R": trial.r, "S": trial.s, "P": trial.p,
                },
                "artifacts_sha256": artifact_hashes,
            }
            manifest_sha = _write(directory / "run_manifest.json",
                                  _canonical(manifest) + b"\n")
            checked = trial.s == 0
            verified = {
                "trial_id": trial.trial_id, "pair_id": trial.pair_id,
                "assignment_manifest_sha256": assignment_sha,
                "status": "COMPLETE", "model_tier": "REAL_LLM",
                "payment_tier": "NATIVE_LOCAL",
                "verdict": "ACCEPT" if payment == "PAID" else "REJECT",
                "checked": checked, "check_spent_units": 1 if checked else 0,
                "oracle_truth": oracle,
                "false_approval": oracle == 0 and payment == "PAID",
                "payment_status": payment,
                "provider_payout_minor_units": 20_000_000 if payment == "PAID" else 0,
                "native_job_id": 1,
                "native_settlement_transaction_hash": "0x" + "1" * 64,
                "prepaid_fee_transaction_hash": "0x" + "2" * 64,
                "channel_isolation_audit": "PASS", "treatment_audit": "PASS",
                "native_inspect_sha256": artifact_hashes["inspect.eval"],
                "native_payment_sha256": artifact_hashes["native_evidence.json"],
                "model_calls": 2, "model_cost_usd_estimate": cost,
                "ledger_run_id": run_id, "source_sha256": {},
                "evidence_validation": "PASS", "run_manifest_sha256": manifest_sha,
            }
            independently_verified[trial.trial_id] = verified
            records.append({
                "trial_id": trial.trial_id, "pair_id": trial.pair_id,
                "fixture_id": trial.fixture_id,
                "R": trial.r, "S": trial.s, "P": trial.p,
                "assignment_manifest_sha256": assignment_sha,
            } | verified)
        records_bytes = b"".join(_canonical(row) + b"\n" for row in records)
        _write(collection_dir / "records.jsonl", records_bytes)
        analysis = analyze_assignments(trials, records)
        analysis.update({
            "assignment_manifest_sha256": assignment_sha,
            "record_count_including_pending": 32,
            "missing_output_count": 0, "failed_evidence_count": 0,
            "valid_complete_count": 32, "incomplete_output_count": 0,
            "claim_scope": "descriptive_exploratory_ITT_bounds_only",
            "causal_claim_ready": False,
            "ledger_last_hash_at_collection": "b" * 64,
            "records_sha256": sha256(records_bytes).hexdigest(),
        })
        _write(collection_dir / "analysis.json", _canonical(analysis) + b"\n")
        ledger = {"cap_usd": "20", "last_hash": "c" * 64,
                  "runs": {row["ledger_run_id"]: {"status": "SETTLED"} for row in records}}
        return assignment_dir, collection_dir, runs_dir, records, independently_verified, ledger

    @staticmethod
    def _verify_stub(independently_verified):
        def verify(_directory, trial, _assignment_sha, _raw, _ledger_runs):
            return independently_verified[trial.trial_id]
        return verify

    def test_builds_hash_bound_complete_exploratory_pilot(self):
        with tempfile.TemporaryDirectory(prefix="g4-calibration-") as tmp:
            root = Path(tmp)
            assignment, collection, runs, records, verified, ledger = self._fixture(root)
            output = root / "aggregate"
            with patch.object(calibration.collector, "_validated_record",
                              side_effect=self._verify_stub(verified)) as verifier, \
                 patch.object(calibration, "BudgetLedger") as budget, \
                 patch.object(calibration, "_ledger_contains_hash", return_value=True):
                budget.return_value.snapshot.return_value = ledger
                result = calibration.build(assignment, collection, runs, output)
            self.assertEqual(verifier.call_count, 32)
            self.assertEqual(result["assignment_count"], 32)
            manifest_bytes = (output / "aggregate_run_manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            pilot = json.loads((output / "pilot_calibration.json").read_bytes())
            self.assertEqual(manifest["independently_reverified_count"], 32)
            self.assertEqual(len(manifest["trials"]), 32)
            self.assertEqual(len({item["schema_v1_run_manifest_sha256"]
                                  for item in manifest["trials"]}), 32)
            self.assertEqual(pilot["source_run_sha256"], sha256(manifest_bytes).hexdigest())
            self.assertFalse(manifest["causal_claim_ready"])
            self.assertFalse(pilot["confirmatory_data"])
            self.assertEqual(PilotCalibration.parse(pilot).max_observed_task_cost_usd,
                             Decimal("0.1031"))
            self.assertEqual(pilot["max_observed_task_cost_usd"],
                             max(row["model_cost_usd_estimate"] for row in records))
            self.assertEqual({row["all_assigned"] for row in pilot["cells"].values()}, {4})
            self.assertEqual({row["bad_assigned"] for row in pilot["cells"].values()}, {2})
            self.assertEqual({row["bad_unresolved"] for row in pilot["cells"].values()}, {0})

    def test_rejects_incomplete_checkpoint_before_output(self):
        with tempfile.TemporaryDirectory(prefix="g4-calibration-") as tmp:
            root = Path(tmp)
            assignment, collection, runs, records, verified, ledger = self._fixture(root)
            records[0]["status"] = "PENDING"
            _write(collection / "records.jsonl",
                   b"".join(_canonical(row) + b"\n" for row in records))
            output = root / "aggregate"
            with patch.object(calibration, "BudgetLedger") as budget, \
                 patch.object(calibration, "_ledger_contains_hash", return_value=True):
                budget.return_value.snapshot.return_value = ledger
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    calibration.build(assignment, collection, runs, output)
            self.assertFalse(output.exists())

    def test_rejects_forged_collector_row_or_changed_trial_manifest(self):
        with tempfile.TemporaryDirectory(prefix="g4-calibration-") as tmp:
            root = Path(tmp)
            assignment, collection, runs, records, verified, ledger = self._fixture(root)
            output = root / "aggregate"
            verified[records[0]["trial_id"]] = verified[records[0]["trial_id"]] | {
                "checked": not records[0]["checked"]}
            with patch.object(calibration.collector, "_validated_record",
                              side_effect=self._verify_stub(verified)), \
                 patch.object(calibration, "BudgetLedger") as budget, \
                 patch.object(calibration, "_ledger_contains_hash", return_value=True):
                budget.return_value.snapshot.return_value = ledger
                with self.assertRaisesRegex(ValueError, "fresh_native_verification"):
                    calibration.build(assignment, collection, runs, output)
            self.assertFalse(output.exists())
            verified[records[0]["trial_id"]]["checked"] = records[0]["checked"]
            manifest_path = runs / records[0]["trial_id"] / "run_manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
            with patch.object(calibration.collector, "_validated_record",
                              side_effect=self._verify_stub(verified)), \
                 patch.object(calibration, "BudgetLedger") as budget, \
                 patch.object(calibration, "_ledger_contains_hash", return_value=True):
                budget.return_value.snapshot.return_value = ledger
                with self.assertRaisesRegex(ValueError, "artifact_hash_changed"):
                    calibration.build(assignment, collection, runs, output)
            self.assertFalse(output.exists())

    def test_rejects_collection_head_outside_verified_ledger(self):
        with tempfile.TemporaryDirectory(prefix="g4-calibration-") as tmp:
            root = Path(tmp)
            assignment, collection, runs, _records, _verified, ledger = self._fixture(root)
            output = root / "aggregate"
            with patch.object(calibration, "BudgetLedger") as budget, \
                 patch.object(calibration, "_ledger_contains_hash", return_value=False):
                budget.return_value.snapshot.return_value = ledger
                with self.assertRaisesRegex(ValueError, "collection_head_changed"):
                    calibration.build(assignment, collection, runs, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
