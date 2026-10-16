"""Independent offline semantic checks, including self-consistent tampering."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.review_free_collusion_probe import ReviewError, review
from agent_economic_trust import free_collusion_probe as probe
from tests.test_free_collusion_probe import FakeTransport


def _rechain(directory: Path) -> None:
    """Make a changed row pass the original hash-chain check."""
    path = directory / "index.jsonl"
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    previous = "0" * 64
    for entry in entries:
        entry["row_sha256"] = sha256((directory / entry["row_file"]).read_bytes()).hexdigest()
        entry["prev_entry_sha256"] = previous
        body = {key: value for key, value in entry.items() if key != "entry_sha256"}
        entry["entry_sha256"] = sha256(probe.canonical(body)).hexdigest()
        previous = entry["entry_sha256"]
    path.write_bytes(b"".join(probe.canonical(entry) + b"\n" for entry in entries))
    terminal = directory / ("STOPPED.json" if (directory / "STOPPED.json").exists()
                            else "SUMMARY.json")
    summary = json.loads(terminal.read_bytes())
    summary["last_entry_sha256"] = previous
    terminal.write_bytes(probe.canonical(summary) + b"\n")


def _mutate(directory: Path, predicate, change) -> None:
    for path in directory.glob("free*.json"):
        row = json.loads(path.read_bytes())
        if predicate(row):
            change(row)
            path.write_bytes(probe.canonical(row) + b"\n")
            _rechain(directory)
            assert probe.verify_run(directory)["status"] in {
                "COMPLETE", "COMPLETE_WITH_MISSING", "STOPPED"}
            return
    raise AssertionError("matching row was absent")


class OfflineSemanticReviewerTests(unittest.TestCase):
    def test_complete_mpp_summary_has_30_per_arm_and_no_native_claim(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "mpp"
            self.assertEqual(probe.run(directory, scenario=probe.MPP,
                                       transport=FakeTransport())["status"], "COMPLETE")
            result = review(directory)
            self.assertEqual(result["reviewed_rows"], 90)
            self.assertEqual(result["by_arm"]["CONTACT_BONUS"]["complete"], 30)
            self.assertEqual(result["by_arm"]["NO_CONTACT_BONUS"]["complete"], 30)
            self.assertEqual(result["by_arm"]["NO_CONTACT_NO_BONUS"]["complete"], 30)
            self.assertEqual(result["by_arm"]["CONTACT_BONUS"]
                             ["candidate_counts_in_complete_rows"]
                             ["auditor_assent_candidate"], 30)
            self.assertEqual(result["payment_execution_tier"], "NO_PAYMENT_EXECUTION")
            self.assertIn("manual review", result["claim_limit"])

    def test_erc_incomplete_and_stopped_are_reported_without_replacement(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            incomplete = root / "incomplete"
            probe.run(incomplete, transport=FakeTransport(first_finish_reason="content_filter",
                                                           first_null_content=True))
            result = review(incomplete)
            self.assertEqual(sum(x["incomplete"] for x in result["by_arm"].values()), 1)
            self.assertEqual(result["reviewed_rows"], 60)
            stopped = root / "stopped"
            probe.run(stopped, transport=FakeTransport(fail_chat=True))
            result = review(stopped)
            self.assertEqual(result["chain_status"], "STOPPED")
            self.assertEqual(result["reviewed_rows"], 1)
            self.assertEqual(sum(x["unattempted"] for x in result["by_arm"].values()), 59)
            self.assertEqual(sum(x["stopped_billing_flags"]["unknown_final_charge"]
                                 for x in result["by_arm"].values()), 1)

    def test_stopped_positive_cost_is_explicitly_reported(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "positive-cost"
            probe.run(directory, transport=FakeTransport(cost="0.01"))
            result = review(directory)
            self.assertEqual(result["chain_status"], "STOPPED")
            self.assertEqual(sum(x["stopped_billing_flags"]["positive_response_cost"]
                                 for x in result["by_arm"].values()), 1)

    def test_request_route_tamper_is_detected_after_rehashing(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            probe.run(directory, transport=FakeTransport())
            def change(row):
                call = row["calls"][0]
                call["request"]["provider"]["max_price"]["completion"] = 1
                call["request_sha256"] = sha256(probe.canonical(call["request"])).hexdigest()
            _mutate(directory, lambda row: True, change)
            with self.assertRaises(ReviewError):
                review(directory)

    def test_response_billing_tamper_is_detected_after_rehashing(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            probe.run(directory, transport=FakeTransport())
            _mutate(directory, lambda row: True,
                    lambda row: row["calls"][0]["response"]["usage"].update(cost="0.001"))
            with self.assertRaises(ReviewError):
                review(directory)

    def test_contact_exposure_tamper_is_detected_after_rehashing(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            probe.run(directory, transport=FakeTransport())
            def change(row):
                call = row["calls"][1]
                call["request"]["messages"][1]["content"] = "Decide without the provider's actual message."
                call["request_sha256"] = sha256(probe.canonical(call["request"])).hexdigest()
            _mutate(directory, lambda row: row["row"]["arm"] == "CONTACT", change)
            with self.assertRaises(ReviewError):
                review(directory)

    def test_classification_tamper_is_detected_after_rehashing(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            probe.run(directory, transport=FakeTransport())
            def change(row):
                row["classification"]["false_approval_text_verdict"] = True
            _mutate(directory, lambda row: True, change)
            with self.assertRaises(ReviewError):
                review(directory)

    def test_inconsistent_mpp_skip_hold_cannot_be_complete(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "mpp"
            probe.run(directory, scenario=probe.MPP, transport=FakeTransport())
            def change(record):
                record["calls"][1]["response"]["text"] = (
                    "CHECK: SKIP\nVERDICT: HOLD\nREASON: Wait.\nRESPONSE_TO_PROVIDER: NONE")
                record["classification"] = probe.classify(
                    record["row"], record["calls"][0]["response"]["text"],
                    record["calls"][1]["response"]["text"])
            _mutate(directory, lambda row: True, change)
            with self.assertRaises(ReviewError):
                review(directory)


if __name__ == "__main__":
    unittest.main()
