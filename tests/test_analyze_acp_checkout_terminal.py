"""Offline evidence and denominator checks for terminal retail ACP analysis."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust import acp_free_checkout_execute as runner
from scripts.analyze_acp_checkout_terminal import (
    TerminalReviewError, analyze, missing_bounds, terminal_marker,
)
from tests.test_acp_free_checkout_execute import FakeTransport


class AcpCheckoutTerminalAnalysisTests(unittest.TestCase):
    def test_active_archive_refused_before_runner_verification(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TerminalReviewError, "terminal marker"):
                analyze(Path(directory))
            run_dir = Path(directory)
            (run_dir / "SUMMARY.json").write_text("{}")
            (run_dir / "STOPPED.json").write_text("{}")
            with self.assertRaisesRegex(TerminalReviewError, "exactly one"):
                terminal_marker(run_dir)

    def test_missing_bounds_include_incomplete_stopped_and_unattempted(self) -> None:
        self.assertEqual(missing_bounds(2, 7, 30), {
            "positive_complete": 2, "complete": 7, "planned": 30,
            "missing_or_unattempted": 23,
            "lower_all_assigned": 2 / 30,
            "upper_all_assigned": 25 / 30,
        })
        with self.assertRaises(TerminalReviewError):
            missing_bounds(8, 7, 30)

    def test_offline_test_double_complete_packet_and_contact_contrast(self) -> None:
        with TemporaryDirectory() as directory:
            run_dir = Path(directory) / "synthetic-test-double"
            self.assertEqual(runner.execute(run_dir, transport=FakeTransport())["status"],
                             "COMPLETE")
            report, packet, reconciliation = analyze(run_dir)
            self.assertEqual(report["model_execution_tier"], "SCRIPTED_TEST_DOUBLE")
            self.assertEqual(report["verified_indexed_rows"], 130)
            self.assertEqual(len(packet), len(reconciliation))
            self.assertEqual(len({item["packet_id"] for item in packet}), 130)
            self.assertEqual(sum(cell["complete"] for cell in report["by_cell"].values()),
                             130)
            for case in ("CROSS_BAD", "BOUND_BAD"):
                contact = report["by_cell"][case + "_CONTACT"]
                control = report["by_cell"][case + "_NO_CONTACT"]
                self.assertEqual(contact["planned"], 30)
                self.assertEqual(contact["verdicts_in_complete_rows"]["ACCEPT"], 30)
                self.assertEqual(contact["machine_candidates_in_complete_rows"][
                    "false_accept_against_independent_oracle"], 30)
                self.assertEqual(contact["observations_in_indexed_rows"][
                    "exact_provider_text_exposed_to_auditor"], 30)
                self.assertEqual(control["verdicts_in_complete_rows"]["ACCEPT"], 0)
                self.assertEqual(control["observations_in_indexed_rows"][
                    "exact_provider_text_exposed_to_auditor"], 0)
                self.assertEqual(control["bilateral_text_candidate_missing_bounds"][
                    "upper_all_assigned"], 0.0)
                self.assertEqual(report["contact_contrasts"][case][
                    "risk_difference_contact_minus_no_contact_bounds"], [1.0, 1.0])
            for item in packet:
                self.assertNotIn("case", item)
                self.assertNotIn("truth", item)
                self.assertNotIn("arm", item)
                self.assertIn("auditor_initial_request_messages", item)
            self.assertEqual(report["downstream_payment_execution_tier"],
                             "NO_NEW_NATIVE_TRANSACTION")

    def test_offline_stopped_run_retains_unattempted_rows(self) -> None:
        with TemporaryDirectory() as directory:
            run_dir = Path(directory) / "synthetic-pricing-stop"
            self.assertEqual(runner.execute(
                run_dir, transport=FakeTransport(paid_catalog=True))["status"], "STOPPED")
            report, packet, _ = analyze(run_dir)
            self.assertEqual(report["terminal_status"], "STOPPED")
            self.assertEqual(report["verified_indexed_rows"], 1)
            self.assertEqual(len(packet), 1)
            self.assertEqual(sum(cell["unattempted"] for cell in report["by_cell"].values()),
                             129)
            self.assertEqual(sum(cell["stopped"] for cell in report["by_cell"].values()),
                             1)


if __name__ == "__main__":
    unittest.main()
