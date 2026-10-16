"""Read-only planned-denominator collection and tamper rejection."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from scripts.collect_w10_factorial import collect  # noqa: E402
from scripts.run_w10_factorial import LEDGER, freeze  # noqa: E402
from agent_economic_trust.w10_factorial import make_assignments  # noqa: E402


SEED = "01" * 32


class W10FactorialCollectTests(unittest.TestCase):
    def _workspace(self, root: Path):
        assignment = root / "assignment"
        runs = root / "runs"
        freeze(assignment, SEED, LEDGER)
        runs.mkdir()
        return assignment, runs, make_assignments(SEED)

    def test_empty_run_directory_keeps_all_32_itt_rows(self):
        with tempfile.TemporaryDirectory(prefix="w10-collect-", dir="/workspace") as tmp:
            root = Path(tmp)
            assignment, runs, trials = self._workspace(root)
            result = collect(assignment, runs, root / "collection")
            records_path = root / "collection" / "records.jsonl"
            rows = [json.loads(line) for line in records_path.read_text().splitlines()]
            analysis = json.loads((root / "collection" / "analysis.json").read_text())
            self.assertEqual(len(rows), len(trials))
            self.assertEqual({row["trial_id"] for row in rows},
                             {trial.trial_id for trial in trials})
            self.assertEqual({row["status"] for row in rows}, {"PENDING"})
            self.assertEqual(result["valid_complete_count"], 0)
            self.assertEqual(analysis["missing_output_count"], 32)
            self.assertEqual(analysis["assignment_count"], 32)
            self.assertEqual(analysis["reported_count"], 32)
            self.assertEqual(analysis["cells"]["000"]["bad_wrong_payment_itt_bounds"],
                             [0.0, 1.0])
            self.assertIsNone(analysis["three_way_bad_work_wrong_payment_interaction"])
            self.assertFalse(analysis["causal_claim_ready"])
            self.assertEqual(analysis["records_sha256"],
                             sha256(records_path.read_bytes()).hexdigest())

    def test_forged_complete_is_failed_and_partial_trial_is_retained(self):
        with tempfile.TemporaryDirectory(prefix="w10-collect-", dir="/workspace") as tmp:
            root = Path(tmp)
            assignment, runs, trials = self._workspace(root)
            assignment_sha = sha256((assignment / "assignment_manifest.json").read_bytes()).hexdigest()
            bad = trials[0]
            bad_dir = runs / bad.trial_id
            bad_dir.mkdir()
            (bad_dir / "trial_record.json").write_text(json.dumps({
                "trial_id": bad.trial_id, "pair_id": bad.pair_id,
                "assignment_manifest_sha256": assignment_sha,
                "status": "COMPLETE", "model_tier": "REAL_LLM",
                "payment_tier": "NATIVE_LOCAL", "verdict": "ACCEPT",
                "checked": False, "payment_status": "PAID",
                "native_inspect_sha256": "a" * 64,
                "native_payment_sha256": "b" * 64,
                "ledger_run_id": f"w10-factorial-{assignment_sha[:12]}-{bad.trial_id}",
            }) + "\n")
            partial = trials[1]
            partial_dir = runs / partial.trial_id
            partial_dir.mkdir()
            (partial_dir / "trial_record.json").write_text(json.dumps({
                "trial_id": partial.trial_id, "pair_id": partial.pair_id,
                "assignment_manifest_sha256": assignment_sha,
                "status": "PAYMENT_FAILED", "payment_status": "UNKNOWN",
                "stage": "erc8183_task_settlement",
            }) + "\n")
            result = collect(assignment, runs, root / "collection")
            rows = {row["trial_id"]: row for row in (
                json.loads(line) for line in
                (root / "collection" / "records.jsonl").read_text().splitlines())}
            analysis = json.loads((root / "collection" / "analysis.json").read_text())
            self.assertEqual(len(rows), 32)
            self.assertEqual(rows[bad.trial_id]["status"], "MODEL_FAILED")
            self.assertEqual(rows[bad.trial_id]["payment_status"], "UNKNOWN")
            self.assertEqual(rows[bad.trial_id]["evidence_validation"], "FAIL")
            self.assertEqual(rows[partial.trial_id]["status"], "PAYMENT_FAILED")
            self.assertEqual(rows[partial.trial_id]["evidence_validation"], "INCOMPLETE")
            self.assertEqual(result["failed_evidence_count"], 1)
            self.assertEqual(analysis["missing_output_count"], 30)
            self.assertEqual(analysis["valid_complete_count"], 0)
            self.assertEqual(analysis["assignment_count"], 32)
            self.assertIsNone(analysis["three_way_bad_work_wrong_payment_interaction"])


if __name__ == "__main__":
    unittest.main()
