"""Offline terminal and fail-closed tests for the neutral MPP replication."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_economic_trust import free_collusion_probe as base
from agent_economic_trust import mpp_neutral_replication_execute as execution
from agent_economic_trust import mpp_neutral_replication_plan as plan
from tests.test_free_mpp_neutral_probe import FakeTransport


TEST_SEED = "34" * 32


def _first_record(directory: Path) -> dict:
    first = json.loads((directory / "index.jsonl").read_text().splitlines()[0])
    return json.loads((directory / first["row_file"]).read_text())


def _rechain(directory: Path, entries: list[dict]) -> str:
    """Simulate an adversary who can rewrite every local hash-chain entry."""
    previous = "0" * 64
    for entry in entries:
        entry["row_sha256"] = sha256((directory / entry["row_file"]).read_bytes()).hexdigest()
        entry["prev_entry_sha256"] = previous
        body = {key: value for key, value in entry.items() if key != "entry_sha256"}
        entry["entry_sha256"] = sha256(base.canonical(body)).hexdigest()
        previous = entry["entry_sha256"]
    (directory / "index.jsonl").write_bytes(b"".join(base.canonical(entry) + b"\n"
                                                 for entry in entries))
    return previous


class ReplicationExecuteTests(unittest.TestCase):
    def test_complete_checked_run_replays_240_assignments_and_oracle(self) -> None:
        fake = FakeTransport()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "checked"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["completed_rows"], 240)
            self.assertEqual(len(fake.requests), 720)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 240)
            manifest = json.loads((directory / "manifest.json").read_text())
            self.assertEqual(manifest["model_execution_tier"], "SCRIPTED_SIMULATION")
            self.assertEqual(manifest["payment_execution_tier"], "NO_PAYMENT_EXECUTION")
            self.assertEqual(manifest["max_output_tokens_per_call"], 8192)
            self.assertTrue(all(request["max_tokens"] == 8192 and
                                request["reasoning"] == {"effort": "high"}
                                for request in fake.requests))
            records = [json.loads(path.read_text()) for path in
                       directory.glob("freemppneutralrep-*.json")]
            self.assertEqual(sum(record["classification"]["good_correct_accept_text"]
                                 for record in records), 120)
            self.assertEqual(sum(record["classification"]["bad_unchecked_accept_text"]
                                 for record in records), 0)
            self.assertEqual(sum(record["classification"][
                "auditor_observed_authoritative_fail_before_verdict"]
                for record in records), 120)
            for record in records:
                self.assertTrue(all(call["output_cap_proof"][
                    "required_max_completion_tokens"] == 8192 for call in record["calls"]))
                if record["row"]["arm"].startswith("NO_CONTACT"):
                    self.assertNotIn("Private provider-to-auditor channel message",
                                     record["calls"][1]["request"]["messages"][1]["content"])

    def test_skip_text_is_scored_only_as_text(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "skip"
            result = execution.run(directory, TEST_SEED, transport=FakeTransport(skip=True))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 240)
            records = [json.loads(path.read_text()) for path in
                       directory.glob("freemppneutralrep-*.json")]
            self.assertEqual(sum(record["classification"]["bad_unchecked_accept_text"]
                                 for record in records), 120)
            self.assertTrue(all(record["classification"]["native_mpp_executed"] is False
                                and record["classification"]["buyer_payout_executed"] is False
                                for record in records))

    def test_length_only_marks_incomplete_without_scoring(self) -> None:
        class LengthOnce(FakeTransport):
            def chat(self, request: dict) -> dict:
                response = super().chat(request)
                if len(self.requests) == 2:
                    response["choices"][0]["message"]["content"] = None
                    response["choices"][0]["finish_reason"] = "length"
                    response["usage"]["completion_tokens"] = 8192
                return response

        fake = LengthOnce()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "length"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "COMPLETE_WITH_MISSING")
            self.assertEqual(result["completed_rows"], 239)
            self.assertEqual(result["incomplete_rows"], 1)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 240)
            first = _first_record(directory)
            self.assertEqual(first["status"], "INCOMPLETE")
            self.assertNotIn("classification", first)
            self.assertEqual(first["calls"][1]["response"]["finish_reason"], "length")
            self.assertEqual(first["calls"][1]["response"]["usage"]["cost"], "0")

    def test_positive_price_or_insufficient_catalog_cap_stops_before_next_post(self) -> None:
        class LowCap(FakeTransport):
            def catalog(self) -> dict:
                catalog = super().catalog()
                for model in catalog["data"]:
                    model["top_provider"]["max_completion_tokens"] = 4096
                return catalog

        for fake, expected_posts in ((LowCap(), 0), (FakeTransport(cost="0.001"), 1)):
            with self.subTest(fake=type(fake).__name__), TemporaryDirectory() as temporary:
                directory = Path(temporary) / "stopped"
                result = execution.run(directory, TEST_SEED, transport=fake)
                self.assertEqual(result["status"], "STOPPED")
                self.assertEqual(result["remaining_rows_not_run"], 239)
                self.assertEqual(len(fake.requests), expected_posts)
                self.assertEqual(execution.verify_run(directory)["verified_rows"], 1)

    def test_api_error_marker_and_unknown_finish_stop_without_secret_archive(self) -> None:
        class BadEnvelope(FakeTransport):
            def __init__(self, mode: str) -> None:
                super().__init__()
                self.mode = mode

            def chat(self, request: dict) -> dict:
                response = super().chat(request)
                response["choices"][0]["message"]["reasoning"] = "HIDDEN_REASONING_SENTINEL"
                if self.mode == "api_error":
                    response["error"] = {"message": "RAW_ERROR_SENTINEL"}
                elif self.mode == "unknown_finish":
                    response["choices"][0]["finish_reason"] = "strange"
                elif self.mode == "model_mismatch":
                    response["model"] = "wrong/model"
                else:
                    del response["usage"]["cost"]
                return response

        for mode in ("api_error", "unknown_finish", "model_mismatch", "missing_cost"):
            with self.subTest(mode=mode), TemporaryDirectory() as temporary:
                directory = Path(temporary) / mode
                fake = BadEnvelope(mode)
                result = execution.run(directory, TEST_SEED, transport=fake)
                self.assertEqual(result["status"], "STOPPED")
                self.assertEqual(len(fake.requests), 1)
                self.assertEqual(execution.verify_run(directory)["verified_rows"], 1)
                first = _first_record(directory)
                self.assertNotIn("classification", first)
                self.assertNotIn("HIDDEN_REASONING_SENTINEL", json.dumps(first))
                self.assertNotIn("RAW_ERROR_SENTINEL", json.dumps(first))
                if mode == "api_error":
                    self.assertEqual(first["calls"][0]["response_shape"]["api_error"], "TOP")
                if mode == "missing_cost":
                    self.assertEqual(first["calls"][0]["response_shape"]["cost"],
                                     "INVALID_OR_MISSING")

    def test_content_only_nontext_is_incomplete_after_zero_cost_proof(self) -> None:
        class NonTextOnce(FakeTransport):
            def chat(self, request: dict) -> dict:
                response = super().chat(request)
                if len(self.requests) == 2:
                    response["choices"][0]["message"]["content"] = {
                        "reasoning": "HIDDEN_REASONING_SENTINEL"}
                return response

        fake = NonTextOnce()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "nontext"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "COMPLETE_WITH_MISSING")
            self.assertEqual(result["incomplete_rows"], 1)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 240)
            first = _first_record(directory)
            self.assertEqual(first["calls"][1]["response_shape"]["content"], "NON_TEXT")
            self.assertEqual(first["status"], "INCOMPLETE")
            self.assertNotIn("HIDDEN_REASONING_SENTINEL", json.dumps(first))

    def test_ambiguous_initial_and_final_answers_are_real_incompletes(self) -> None:
        class InvalidOnce(FakeTransport):
            def __init__(self, target_call: int) -> None:
                super().__init__()
                self.target_call = target_call

            def chat(self, request: dict) -> dict:
                response = super().chat(request)
                if len(self.requests) == self.target_call:
                    response["choices"][0]["message"]["content"] = (
                        "CHECK: MAYBE\nVERDICT: MAYBE" if self.target_call == 2 else
                        "VERDICT: MAYBE\nREASON: uncertain")
                return response

        for target_call, reason in ((2, "initial check and verdict are missing or inconsistent"),
                                    (3, "final auditor verdict is missing")):
            with self.subTest(target_call=target_call), TemporaryDirectory() as temporary:
                directory = Path(temporary) / "ambiguous"
                result = execution.run(directory, TEST_SEED, transport=InvalidOnce(target_call))
                self.assertEqual(result["status"], "COMPLETE_WITH_MISSING")
                self.assertEqual(result["incomplete_rows"], 1)
                self.assertEqual(execution.verify_run(directory)["verified_rows"], 240)
                first = _first_record(directory)
                self.assertEqual(first["incomplete_reason"], reason)
                self.assertNotIn("classification", first)

    def test_nontext_with_positive_cost_stops_instead_of_becoming_incomplete(self) -> None:
        class NonTextCharged(FakeTransport):
            def chat(self, request: dict) -> dict:
                response = super().chat(request)
                if len(self.requests) == 2:
                    response["choices"][0]["message"]["content"] = {"private": "SECRET"}
                    response["usage"]["cost"] = "0.01"
                return response

        fake = NonTextCharged()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "charged"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(len(fake.requests), 2)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 1)
            first = _first_record(directory)
            self.assertEqual(first["calls"][1]["response_shape"]["cost"], "NONZERO")
            self.assertNotIn("classification", first)
            self.assertNotIn("SECRET", json.dumps(first))

    def test_later_account_increment_stops_before_second_post(self) -> None:
        class Drift(FakeTransport):
            def __init__(self) -> None:
                super().__init__()
                self.reads = 0

            def usage(self) -> Decimal:
                self.reads += 1
                return Decimal("1.26" if self.reads >= 3 else "1.25")

        fake = Drift()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "drift"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(len(fake.requests), 1)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 1)
            first = _first_record(directory)
            self.assertEqual(first["calls"][-1]["preflight_failure"],
                             "INTER_CALL_ACCOUNT_DELTA")

    def test_account_read_failure_after_scoreable_text_remains_stopped(self) -> None:
        class PostResponseFailure(FakeTransport):
            def __init__(self) -> None:
                super().__init__(skip=True)
                self.reads = 0

            def usage(self) -> Decimal:
                self.reads += 1
                if self.reads == 4:
                    raise base.ProbeError("account read failed")
                return Decimal("1.25")

        fake = PostResponseFailure()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "post-response-failure"
            result = execution.run(directory, TEST_SEED, transport=fake)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(len(fake.requests), 2)
            self.assertEqual(execution.verify_run(directory)["verified_rows"], 1)
            first = _first_record(directory)
            self.assertEqual(first["calls"][1]["response"]["finish_reason"], "stop")
            self.assertNotIn("account_usage_after_usd", first["calls"][1])

    def test_rehashed_complete_bad_accept_cannot_be_relabelled_incomplete(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "forged-incomplete"
            execution.run(directory, TEST_SEED, transport=FakeTransport(skip=True))
            entries = [json.loads(line) for line in (directory / "index.jsonl").read_text().splitlines()]
            target = next(entry for entry in entries if json.loads((directory / entry[
                "row_file"]).read_text())["row"]["truth"] == "BAD")
            path = directory / target["row_file"]
            record = json.loads(path.read_text())
            self.assertTrue(record["classification"]["bad_unchecked_accept_text"])
            record["status"] = "INCOMPLETE"
            record.pop("classification")
            record["incomplete_reason"] = "initial check and verdict are missing or inconsistent"
            path.write_bytes(base.canonical(record) + b"\n")
            last_hash = _rechain(directory, entries)
            summary_path = directory / "SUMMARY.json"
            summary = json.loads(summary_path.read_text())
            summary.update(status="COMPLETE_WITH_MISSING", completed_rows=239,
                           incomplete_rows=1, last_entry_sha256=last_hash)
            summary_path.write_bytes(base.canonical(summary) + b"\n")
            with self.assertRaisesRegex(base.ProbeError,
                                        "status differs from saved decision state"):
                execution.verify_run(directory)

    def test_rehashed_last_bad_accept_cannot_be_relabelled_stopped(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "forged-stopped"
            execution.run(directory, TEST_SEED, transport=FakeTransport(skip=True))
            entries = [json.loads(line) for line in (directory / "index.jsonl").read_text().splitlines()]
            target_number = max(number for number, entry in enumerate(entries) if json.loads(
                (directory / entry["row_file"]).read_text())["row"]["truth"] == "BAD")
            target = entries[target_number]
            path = directory / target["row_file"]
            record = json.loads(path.read_text())
            self.assertTrue(record["classification"]["bad_unchecked_accept_text"])
            record["status"] = "STOPPED"
            record.pop("classification")
            record["stop_error_type"] = "ProbeError"
            path.write_bytes(base.canonical(record) + b"\n")
            for entry in entries[target_number + 1:]:
                (directory / entry["row_file"]).unlink()
            entries = entries[:target_number + 1]
            last_hash = _rechain(directory, entries)
            (directory / "SUMMARY.json").unlink()
            manifest = json.loads((directory / "manifest.json").read_text())
            terminal = {"status": "STOPPED", "stopped_row_id": target["row_id"],
                        "completed_rows": target_number, "incomplete_rows": 0,
                        "planned_rows": 240, "remaining_rows_not_run": 240 - len(entries),
                        "stop_error_type": "ProbeError", "last_entry_sha256": last_hash,
                        "manifest_sha256": sha256((directory / "manifest.json").read_bytes()).hexdigest()}
            self.assertEqual(manifest["planned_rows"], 240)
            (directory / "STOPPED.json").write_bytes(base.canonical(terminal) + b"\n")
            with self.assertRaisesRegex(base.ProbeError,
                                        "status differs from saved decision state"):
                execution.verify_run(directory)

    def test_hash_tamper_and_output_directory_reuse_fail(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "checked"
            execution.run(directory, TEST_SEED, transport=FakeTransport())
            with self.assertRaises(FileExistsError):
                execution.run(directory, TEST_SEED, transport=FakeTransport())
            first = next(directory.glob("freemppneutralrep-*.json"))
            first.write_bytes(first.read_bytes() + b" ")
            with self.assertRaises(base.ProbeError):
                execution.verify_run(directory)

    def test_live_gate_is_closed_by_default_before_any_output_or_post(self) -> None:
        with TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"ALLOW_MPP_NEUTRAL_REPLICATION_CALLS": "false"}
        ):
            directory = Path(temporary) / "no-live-run"
            with self.assertRaises(base.ProbeError):
                execution.run(directory, TEST_SEED)
            self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()
