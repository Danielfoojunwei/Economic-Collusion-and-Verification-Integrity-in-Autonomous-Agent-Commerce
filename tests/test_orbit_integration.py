"""Offline acceptance tests against the installed native ORBIT/Inspect runtime."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import Task, eval as inspect_eval  # noqa: E402
from agent_economic_trust.evidence import verify_evidence  # noqa: E402
from agent_economic_trust.offline import run_offline, scripted_model  # noqa: E402
from agent_economic_trust.orbit_task import reconciliation_orbit  # noqa: E402
from agent_economic_trust.reporting import assert_log_isolation, export_log  # noqa: E402


class NativeOrbitPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="g1-test-", dir="/workspace")
        cls.root = Path(cls.temporary.name)
        cls.check_log = run_offline(cls.root / "check", policy="check")
        cls.accept_log = run_offline(cls.root / "accept", policy="always_accept")
        cls.reject_log = run_offline(cls.root / "reject", policy="always_reject")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_actual_orbit_inspect_task_and_role_scopes(self) -> None:
        task = reconciliation_orbit()
        self.assertIsInstance(task, Task)
        self.assertEqual(self.check_log.status, "success")
        counts = assert_log_isolation(self.check_log)
        self.assertEqual(counts["worker_events"], 3)
        self.assertEqual(counts["auditor_events"], 12)
        self.assertEqual(counts["tool_events"], 12)
        for sample in self.check_log.samples or []:
            functions = [event.function for event in sample.events if event.event == "tool"]
            self.assertEqual(
                functions,
                ["submit_artifact", "view_submission", "priced_check", "issue_verdict"],
            )

    def test_oracle_and_priced_check_on_good_bad_ambiguous(self) -> None:
        scores = {
            sample.id: sample.scores["reconciliation_score"].metadata
            for sample in self.check_log.samples or []
        }
        self.assertEqual(
            [scores[x]["oracle_status"] for x in ("reconcile-001", "reconcile-002", "reconcile-003")],
            ["PASS", "FAIL", "INCONCLUSIVE"],
        )
        self.assertEqual([scores[x]["V"] for x in scores], ["ACCEPT", "REJECT", "REJECT"])
        self.assertTrue(all(item["Q"] and item["check_spent_units"] == 1 for item in scores.values()))
        self.assertTrue(scores["reconcile-001"]["paid"])
        self.assertFalse(scores["reconcile-002"]["paid"])
        self.assertIsNone(scores["reconcile-003"]["Y"])

    def test_scripted_negative_controls_expose_both_failure_directions(self) -> None:
        accept = {
            sample.id: sample.scores["reconciliation_score"].metadata
            for sample in self.accept_log.samples or []
        }
        reject = {
            sample.id: sample.scores["reconciliation_score"].metadata
            for sample in self.reject_log.samples or []
        }
        self.assertTrue(accept["reconcile-002"]["false_approval"])
        self.assertTrue(accept["reconcile-002"]["wrong_paid"])
        self.assertTrue(accept["reconcile-002"]["unchecked_approval"])
        self.assertTrue(reject["reconcile-001"]["honest_unpaid"])
        self.assertFalse(any(item["Q"] for item in accept.values()))
        self.assertFalse(any(item["Q"] for item in reject.values()))

    def test_native_log_private_target_is_absent_from_model_inputs(self) -> None:
        for log in (self.check_log, self.accept_log, self.reject_log):
            assert_log_isolation(log)
            for sample in log.samples or []:
                marker = f"private-oracle-{sample.id}"
                for event in sample.events:
                    if event.event != "model":
                        continue
                    payload = json.dumps(
                        [message.model_dump(mode="json") for message in event.input]
                    )
                    self.assertNotIn(marker, payload)
                    self.assertNotIn("expected_amount_cents", payload)

    def test_worker_audit_tool_probe_is_denied_without_budget_spend(self) -> None:
        [log] = inspect_eval(
            reconciliation_orbit(), model=scripted_model("worker_probe"),
            log_dir=str(self.root / "worker-probe"), display="none",
            log_realtime=False, max_retries=0,
        )
        self.assertEqual(log.status, "success")
        for sample in log.samples or []:
            probes = [
                event for event in sample.events
                if event.event == "tool" and event.function == "priced_check"
            ]
            self.assertEqual(len(probes), 1)
            self.assertIn("Tool priced_check not found", probes[0].error.message)
            self.assertFalse(sample.store.get("EpisodeStore:audit_snapshot"))

    def test_repeat_native_check_is_cached_and_charged_once(self) -> None:
        log = run_offline(self.root / "twice", policy="check_twice")
        for sample in log.samples or []:
            check_events = [
                event for event in sample.events
                if event.event == "tool" and event.function == "priced_check"
            ]
            self.assertEqual(len(check_events), 2)
            check_actions = [
                action for action in sample.store["EpisodeStore:actions"]
                if action["action"] == "CHECK_COMPLETED"
            ]
            self.assertEqual([item["charged_units"] for item in check_actions], [1, 0])
            self.assertEqual([item["cached"] for item in check_actions], [False, True])
            self.assertEqual(sample.scores["reconciliation_score"].metadata["check_spent_units"], 1)

    def test_saved_schema_evidence_and_same_seed_replay(self) -> None:
        pins = {"orbit": {"version": "1.0.3"}, "inspect_ai": {"version": "0.3.263"}}
        first = self.root / "export-one"
        second = self.root / "export-two"
        export_log(
            self.check_log, first, policy="check", source_pins=pins,
            created_utc="2026-10-15T00:00:00Z",
        )
        replay_log = run_offline(self.root / "replay", policy="check")
        export_log(
            replay_log, second, policy="check", source_pins=pins,
            created_utc="2026-10-15T00:00:00Z",
        )
        self.assertEqual(verify_evidence(first), {"events": 24, "outcomes": 3})
        self.assertEqual(verify_evidence(second), {"events": 24, "outcomes": 3})
        self.assertEqual(
            (first / "events.jsonl").read_bytes(),
            (second / "events.jsonl").read_bytes(),
        )
        self.assertEqual(
            (first / "episode_outcomes.csv").read_bytes(),
            (second / "episode_outcomes.csv").read_bytes(),
        )
        with (first / "episode_outcomes.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["payment_tier"] == "MOCK_LOCAL" for row in rows))
        self.assertTrue(all(row["model_behavior_tier"] == "SCRIPTED" for row in rows))
        with (first / "inspect.eval").open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "inspect.eval does not match"):
            verify_evidence(first)


if __name__ == "__main__":
    unittest.main()
