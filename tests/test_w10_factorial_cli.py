"""The W10 single-trial CLI never calls a provider in these tests."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import run_w10_factorial_live as cli


TRIAL_ID = "w10-test-one"


def _forecast(*, ready: bool = True) -> dict:
    return {
        "trial_id": TRIAL_ID, "pair_id": "test-pair",
        "assignment_manifest_sha256": "a" * 64,
        "R": 1, "S": 0, "P": 1,
        "model_id": "openai/gpt-5.6-sol", "reasoning_effort": "high",
        "project_cap_usd": "20", "max_provider_calls": 6,
        "worst_case_reservation_usd": "3.194880",
        "ledger": {"available_usd": "19.8", "blocked": False},
        "ready_to_execute": ready,
    }


class W10FactorialCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="w10-factorial-cli-", dir="/workspace")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def args(self, *extra: str) -> list[str]:
        return ["--model-id", "openai/gpt-5.6-sol",
                "--project-cap-usd", "20", "--trial-id", TRIAL_ID, *extra]

    def test_default_dry_run_never_invokes_paid_execute(self) -> None:
        output = StringIO()
        with patch.dict(os.environ, {"ALLOW_EXTERNAL_MODEL_CALLS": "true",
                                  "MAX_REAL_SPEND": "20"}):
            with patch.object(cli, "preflight", return_value=_forecast()) as checked:
                with patch.object(cli, "execute", side_effect=AssertionError("paid call")) as paid:
                    with redirect_stdout(output):
                        cli.main(self.args())
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["max_provider_calls"], 6)
        self.assertEqual(payload["ledger_available_usd"], "19.8")
        plan = checked.call_args.args[0]
        self.assertEqual(plan.model_id, "openai/gpt-5.6-sol")
        self.assertEqual(plan.cap_usd, Decimal("20"))
        self.assertEqual(plan.assignment_dir, cli.DEFAULT_ASSIGNMENT_DIR)
        paid.assert_not_called()

    def test_execute_requires_output_dir_before_preflight(self) -> None:
        stderr = StringIO()
        with patch.object(cli, "preflight") as checked, patch.object(cli, "execute") as paid:
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                cli.main(self.args("--execute"))
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(stderr.getvalue().strip(), "W10 factorial stopped: ValueError")
        checked.assert_not_called()
        paid.assert_not_called()

    def test_existing_output_blocks_execute_without_provider_call(self) -> None:
        existing = self.root / "existing"
        existing.mkdir()
        stderr = StringIO()
        with patch.object(cli, "preflight", side_effect=lambda plan: plan.validate()):
            with patch.object(cli, "execute") as paid:
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
                    cli.main(self.args("--output-dir", str(existing), "--execute"))
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(stderr.getvalue().strip(),
                         "W10 factorial stopped: RemoteBoundaryError")
        paid.assert_not_called()

    def test_execute_invokes_exactly_one_trial_after_ready_preflight(self) -> None:
        output_dir = self.root / "fresh"
        result = {"record": {
            "trial_id": TRIAL_ID, "status": "COMPLETE", "verdict": "REJECT",
            "checked": True, "payment_status": "NOT_PAID", "model_calls": 3,
            "model_cost_usd_estimate": "0.12",
        }, "manifest_sha256": "b" * 64}
        output = StringIO()
        with patch.object(cli, "preflight", return_value=_forecast()) as checked:
            with patch.object(cli, "execute", return_value=result) as paid:
                with redirect_stdout(output):
                    cli.main(self.args("--output-dir", str(output_dir), "--execute"))
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([line["mode"] for line in lines],
                         ["execute_preflight", "complete"])
        self.assertEqual(lines[1]["run_manifest_sha256"], "b" * 64)
        self.assertEqual(lines[1]["payment_status"], "NOT_PAID")
        plan = paid.call_args.args[0]
        self.assertIs(plan, checked.call_args.args[0])
        self.assertEqual(plan.output_dir, output_dir)
        paid.assert_called_once()

    def test_unready_preflight_never_invokes_paid_execute(self) -> None:
        stderr = StringIO()
        with patch.object(cli, "preflight", return_value=_forecast(ready=False)):
            with patch.object(cli, "execute") as paid:
                with redirect_stdout(StringIO()), redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as stopped:
                        cli.main(self.args("--output-dir", str(self.root / "fresh"),
                                           "--execute"))
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(stderr.getvalue().strip(),
                         "W10 factorial stopped: RuntimeError")
        paid.assert_not_called()


if __name__ == "__main__":
    unittest.main()
