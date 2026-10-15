"""MPP010 budget, checkout and native-chain guards without paid execution."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_economic_trust.mpp010_plan import digest
from agent_economic_trust.mpp010_remote import (
    RemoteBoundaryError, dedicated_chain_preflight, remaining_headroom,
)
from agent_economic_trust.remote_budget import BudgetIntegrityError, create_ledger
from scripts import freeze_mpp010 as gate


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


class RunnerTests(unittest.TestCase):
    def test_full_remaining_block_keeps_contingency_and_residual(self):
        self.assertEqual(remaining_headroom([Decimal("2.621440"), Decimal("3.276800")]),
                         Decimal("7.8982742"))
        self.assertEqual(remaining_headroom([]), Decimal("2.0000342"))
        with self.assertRaises(RemoteBoundaryError):
            remaining_headroom([Decimal("-1")])

    def test_chain_marker_is_required_beyond_shared_genesis(self):
        with patch("agent_economic_trust.mpp010_remote._rpc") as rpc:
            rpc.side_effect = ["0x539", {"hash": "0x" + "f" * 64}, "0x6001"]
            with self.assertRaisesRegex(RemoteBoundaryError, "genesis differs"):
                dedicated_chain_preflight()
        from agent_economic_trust import mpp010_remote as remote
        with patch.object(remote, "_rpc", side_effect=[
            "0x539", {"hash": remote.MPP010_GENESIS_HASH}, "0x6001", None, {}]):
            with self.assertRaises(RemoteBoundaryError):
                dedicated_chain_preflight()

    def test_noncanonical_worktree_rejected_before_git(self):
        with TemporaryDirectory() as temporary, \
             patch.object(gate, "ROOT", Path(temporary) / "other"), \
             patch.object(gate, "PROJECT_ROOT", Path(temporary) / "main"), \
             patch.object(gate.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "not the canonical project checkout"):
                gate.canonical_checkout_preflight()
            run.assert_not_called()

    def test_mutable_ledger_still_requires_valid_chain_and_anchor(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifacts/budget/openrouter-ledger.jsonl"
            ledger = create_ledger(path, "20")
            ledger.reserve("mpp010-test", "1", "20")
            ledger.settle("mpp010-test", "0.2", "sha256:" + "c" * 64)
            self.assertEqual(ledger.snapshot()["runs"]["mpp010-test"]["status"],
                             "SETTLED")
            original = path.read_bytes()
            path.write_bytes(original.replace(b'"actual_usd":"0.2"',
                                              b'"actual_usd":"0.3"'))
            with self.assertRaises(BudgetIntegrityError):
                ledger.snapshot()

    def test_settled_ledger_and_assigned_artifact_are_allowed_after_freeze(self):
        """Real BudgetLedger writes may dirty two tracked files during verify_static."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _git(root, "init", "-q")
            _git(root, "config", "user.email", "mpp010@example.invalid")
            _git(root, "config", "user.name", "MPP010 Test")
            source = root / "frozen.py"
            source.write_text("SOURCE = 1\n")
            readme = root / "README.md"
            readme.write_text("clean\n")
            ledger_path = root / "artifacts/budget/openrouter-ledger.jsonl"
            ledger = create_ledger(ledger_path, "20")
            episode = "mpp010-" + "a" * 24
            assignment = root / "artifacts/gates/MPP010/assignment-001"
            assignment.mkdir(parents=True)
            (assignment / "assignment_manifest.json").write_text(json.dumps({
                "rows": [{"episode_id": episode}]}))
            artifact = root / "artifacts/gates/MPP010/runs-001/episodes" / episode / "trace.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n")
            _git(root, "add", "frozen.py", "README.md", "artifacts/budget",
                 "artifacts/gates/MPP010/runs-001")
            _git(root, "commit", "-qm", "test fixture")
            frozen_head = ledger.snapshot()
            assignment_sha = "b" * 64
            run_id = f"mpp010-{assignment_sha[:12]}-{episode}"
            ledger.reserve(run_id, Decimal("1"), Decimal("20"))
            ledger.settle(run_id, Decimal("0.2"), "sha256:" + "c" * 64)
            artifact.write_text('{"settled":true}\n')
            source_hash = sha256(source.read_bytes()).hexdigest()
            row = SimpleNamespace(episode_id=episode)
            clearance = {"status": "REVIEWED"}
            exposure = {"status": "CONTINGENT"}
            frozen = {"source_sha256": {"frozen.py": source_hash},
                      "runtime_pins": {},
                      "public_pricing_snapshots": {},
                      "worst_case_reserve_usd_by_episode": {episode: "1"},
                      "worst_case_reserve_usd_full_block": "1",
                      "required_headroom_usd": "3.0000342",
                      "budget_at_freeze": {key: frozen_head[key] for key in
                         ("seq", "last_hash", "cap_usd", "available_usd")},
                      "prior_ledger_run_ids": [],
                      "prior_ledger_runs_sha256": digest({}),
                      "cross_study_clearance": clearance,
                      "prior_mpp006_contingent_exposure": exposure}
            with patch.object(gate, "ROOT", root), \
                 patch.object(gate, "PROJECT_ROOT", root), \
                 patch.object(gate, "ASSIGNMENT", assignment), \
                 patch.object(gate, "source_inventory",
                              side_effect=lambda: {"frozen.py": sha256(source.read_bytes()).hexdigest()}), \
                 patch.object(gate, "load_assignment", return_value=(frozen, assignment_sha, (row,))), \
                 patch.object(gate, "runtime_pins", return_value={}), \
                 patch.object(gate, "_reserves", return_value={episode: Decimal("1")}), \
                 patch.object(gate, "required_headroom", return_value=Decimal("3.0000342")), \
                 patch.object(gate, "_ancestor", side_effect=lambda _: ledger.snapshot()), \
                 patch.object(gate, "cross_study_clearance", return_value=clearance), \
                 patch.object(gate, "mpp006_contingent_exposure", return_value=exposure):
                self.assertEqual(gate.verify_static()["status"], "PASS")
                readme.write_text("unrelated edit\n")
                with self.assertRaisesRegex(ValueError, "unrelated or frozen tracked"):
                    gate.verify_static()
                readme.write_text("clean\n")
                source.write_text("SOURCE = 2\n")
                with self.assertRaisesRegex(ValueError, "differs from committed HEAD"):
                    gate.verify_static()
                _git(root, "add", "frozen.py")
                source.write_text("SOURCE = 1\n")
                with self.assertRaisesRegex(ValueError, "unrelated or frozen tracked"):
                    gate.verify_static()


if __name__ == "__main__":
    unittest.main()
