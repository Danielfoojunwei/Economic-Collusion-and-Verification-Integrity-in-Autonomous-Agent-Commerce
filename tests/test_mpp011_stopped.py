"""Read-only stopped-row request and contingent billing reconciliation."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_economic_trust.mpp011_plan import digest, make_schedule
from agent_economic_trust.mpp011_remote import run_id
from agent_economic_trust.mpp011_reporting import (
    verify_stopped_billing, verify_stopped_request_boundary)
from agent_economic_trust.remote_budget import create_ledger


ROW = make_schedule("cd" * 32)[0]
ASSIGNMENT_SHA = "a" * 64


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


class StoppedRequestTests(unittest.TestCase):
    def test_saved_inspect_events_replay_guarded_attempts_without_billing_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "inspect.eval").write_bytes(b"synthetic inspect archive")
            attempts = [{"call_index": index, "role": "provider",
                         "model": "openrouter/" + ROW.provider_model_id,
                         "serialized_input_bytes": 100 + index,
                         "tool_schemas_sha256": "b" * 64,
                         "provider_api_invoked": True,
                         "network_forwarding": "UNOBSERVED",
                         "http_client_max_retries": 0,
                         "completed": True} for index in (1, 2)]
            events = [SimpleNamespace(event="model", actor="provider",
                model="openrouter/" + ROW.provider_model_id,
                input=[], tools=[], error=None, raw_size=100 + index)
                for index in (1, 2)]
            log = SimpleNamespace(samples=[SimpleNamespace(events=events)])
            stopped = {"model_request_boundary": attempts,
                       "model_calls_attempted": 2}
            with (patch("agent_economic_trust.mpp011_reporting.read_eval_log",
                        return_value=log),
                  patch("agent_economic_trust.mpp011_reporting._agent_for_event",
                        side_effect=lambda event, sample: event.actor),
                  patch("agent_economic_trust.mpp011_reporting._safe_model_input_size",
                        side_effect=lambda inputs, tools: next(
                            event.raw_size for event in events if event.input is inputs)),
                  patch("agent_economic_trust.mpp011_reporting.verify_strict_tool_schemas",
                        return_value="b" * 64)):
                replay = verify_stopped_request_boundary(ROW, directory, stopped)
                self.assertEqual(replay["status"], "ALL_ATTEMPTS_REPLAYED")
                self.assertEqual(replay["inspect_model_events"], 2)
                self.assertEqual(replay["final_provider_billing"], "UNVERIFIED")
                changed = {**stopped, "model_request_boundary": [
                    {**attempts[0], "serialized_input_bytes": 99}, attempts[1]]}
                with self.assertRaisesRegex(ValueError, "Inspect event differs"):
                    verify_stopped_request_boundary(ROW, directory, changed)
                (directory / "other.eval").write_bytes(b"different Inspect archive")
                with self.assertRaisesRegex(ValueError, "archives conflict"):
                    verify_stopped_request_boundary(ROW, directory, stopped)

    def test_no_archive_preserves_attempts_as_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            replay = verify_stopped_request_boundary(ROW, directory, {
                "model_request_boundary": [], "model_calls_attempted": 0})
            self.assertEqual(replay["status"], "NO_SAVED_INSPECT_ARCHIVE")
            self.assertIsNone(replay["inspect_model_events"])
            self.assertEqual(replay["final_provider_billing"], "UNVERIFIED")


class StoppedContingentTests(unittest.TestCase):
    def test_committed_clearance_retains_exact_unknown_full_reserve(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"],
                           cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Stopped Collector Test"],
                           cwd=root, check=True)
            ledger_path = root / "artifacts/budget/openrouter-ledger.jsonl"
            ledger = create_ledger(ledger_path, "20")
            ident = run_id(ASSIGNMENT_SHA, ROW.episode_id)
            ledger.reserve(ident, "3", "20", metadata={
                "provider_model_id": ROW.provider_model_id,
                "auditor_model_id": ROW.auditor_model_id,
                "episode_id": ROW.episode_id,
                "assignment_sha": ASSIGNMENT_SHA})
            prior = ledger.mark_unknown(ident, "RemoteBoundaryError")
            directory = root / "artifacts/gates/MPP011/runs-001/episodes" / ROW.episode_id
            stopped = {"schema": "mpp011-stopped-episode-v1",
                "episode_id": ROW.episode_id,
                "assignment_manifest_sha256": ASSIGNMENT_SHA,
                "ledger_run_id": ident, "error_type": "RemoteBoundaryError",
                "budget_state": "UNKNOWN", "model_request_boundary": [],
                "model_calls_attempted": 0}
            stop_path = directory / "STOPPED.json"
            _write(stop_path, stopped)
            stop_sha = sha256(stop_path.read_bytes()).hexdigest()
            head = {"seq": prior["seq"], "last_hash": prior["last_hash"]}
            sidecar_path = root / "artifacts/budget/mpp011-contingent" / f"{ROW.episode_id}.json"
            sidecar = {"schema": "mpp011-contingent-billing-sidecar-v1",
                "run_id": ident, "episode_id": ROW.episode_id,
                "assignment_manifest_sha256": ASSIGNMENT_SHA,
                "stop_sha256": stop_sha,
                "stopped_model_request_sha256": digest([]),
                "inspect_sha256": None,
                "full_reserved_usd": "3", "final_provider_charge_usd": None,
                "settlement_requires_independent_review": True,
                "ledger_prestate": head}
            _write(sidecar_path, sidecar)
            sidecar_sha = sha256(sidecar_path.read_bytes()).hexdigest()
            clearance_path = root / "artifacts/gates/MPP011/contingent-clearance" / f"{ROW.episode_id}.json"
            clearance = {"schema": "mpp011-contingent-billing-clearance-v1",
                "decision": "RETAIN_FULL_RESERVATION_AFTER_INDEPENDENT_REVIEW",
                "run_id": ident, "episode_id": ROW.episode_id,
                "sidecar_path": str(sidecar_path.relative_to(root)),
                "sidecar_sha256": sidecar_sha, "stop_sha256": stop_sha,
                "ledger_prestate": head}
            _write(clearance_path, clearance)
            subprocess.run(["git", "add", str(sidecar_path.relative_to(root)),
                            str(clearance_path.relative_to(root))], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "Reviewed contingent hold"],
                           cwd=root, check=True)
            ledger.mark_contingent(ident, "sha256:" + sidecar_sha,
                expected_seq=prior["seq"], expected_last_hash=prior["last_hash"])
            from agent_economic_trust import mpp011_reporting as reporting
            replay = {"inspect_sha256": None}
            with (patch.object(reporting, "ROOT", root),
                  patch.object(reporting, "CONTINGENT_SIDECARS", sidecar_path.parent),
                  patch.object(reporting, "CONTINGENT_CLEARANCE", clearance_path.parent)):
                result = verify_stopped_billing(ROW, directory, stopped,
                    assignment_sha=ASSIGNMENT_SHA, ledger=ledger.snapshot(),
                    ledger_path=ledger_path, replay=replay,
                    expected_reserve_usd="3")
                self.assertEqual(result["saved_state"], "UNKNOWN")
                self.assertEqual(result["current_state"], "CONTINGENT")
                self.assertEqual(result["full_reserved_usd"], "3")
                self.assertEqual(result["final_provider_billing"], "UNVERIFIED")
                altered = ledger.snapshot()
                altered["runs"][ident]["reserved_usd"] = "2"
                with self.assertRaisesRegex(ValueError, "full assigned reservation"):
                    verify_stopped_billing(ROW, directory, stopped,
                        assignment_sha=ASSIGNMENT_SHA, ledger=altered,
                        ledger_path=ledger_path, replay=replay,
                        expected_reserve_usd="3")
                clearance_path.unlink()
                with self.assertRaises(ValueError):
                    verify_stopped_billing(ROW, directory, stopped,
                        assignment_sha=ASSIGNMENT_SHA, ledger=ledger.snapshot(),
                        ledger_path=ledger_path, replay=replay,
                        expected_reserve_usd="3")


if __name__ == "__main__":
    unittest.main()
