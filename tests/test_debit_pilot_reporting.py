"""Negative and denominator checks for saved-evidence pilot 003 collection."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_economic_trust.debit_pilot_plan import make_schedule, manifest
from agent_economic_trust.debit_pilot_reporting import (
    DebitPilotEvidenceError, _bounds, _serialized_model_input_bytes, _stopped_row,
    _verify_model_boundary, _verify_ledger, _row_stub, _summarize,
    collect_debit_pilot, load_assignment,
)


SEED = "d3" * 32


def _assignment(root: Path) -> tuple[Path, tuple]:
    directory = root / "assignment"
    directory.mkdir()
    rows = make_schedule(SEED)
    (directory / "seed.hex").write_text(SEED + "\n", encoding="ascii")
    (directory / "private_episodes.json").write_text(
        json.dumps([asdict(row) for row in rows], sort_keys=True))
    (directory / "assignment_manifest.json").write_text(
        json.dumps(manifest(SEED, rows), sort_keys=True))
    return directory, rows


class DebitPilotReportingTests(unittest.TestCase):
    def test_saved_model_usage_must_settle_to_exact_inspect_hash(self):
        row = make_schedule(SEED)[0]
        assignment_sha = "b" * 64
        inspect_sha = "c" * 64
        run_id = f"debit-{assignment_sha[:12]}-{row.episode_id}"
        record = {"ledger_run_id": run_id,
                  "model_cost_usd_provisional_estimate": "0.02"}
        run = {"status": "SETTLED", "evidence_ref": "sha256:" + inspect_sha,
               "actual_usd": "0.02",
               "metadata": {"assignment_sha": assignment_sha,
                            "episode_id": row.episode_id,
                            "model_id": "openai/gpt-5.6-sol"}}
        ledger = {"runs": {run_id: run}}
        self.assertEqual(_verify_ledger(ledger, record, row, assignment_sha,
                                        inspect_sha)["settled_usd"], "0.02")
        run["evidence_ref"] = "sha256:" + "d" * 64
        with self.assertRaisesRegex(DebitPilotEvidenceError, "shared ledger"):
            _verify_ledger(ledger, record, row, assignment_sha, inspect_sha)

    def test_completed_nonadherent_direct_row_remains_in_assigned_cell(self):
        rows = [_row_stub(row, "PENDING") for row in make_schedule(SEED)]
        target = next(row for row in rows if row["cell"] == "BAD-DIRECT-B1-D1")
        target["status"] = "COMPLETE"
        target["direct_read_exact"] = False
        target["independent_check_completed_before_verdict"] = False
        target["bad_false_approval"] = True
        target["bad_unchecked_approval"] = True
        target["bad_wrongful_provider_payout"] = True
        target["good_work_nonpayment"] = False
        target["wrong_amount_or_payee"] = False
        target["coalition_external_net_minor_units"] = 19_000_000
        analysis = _summarize(rows)
        cell = analysis["cells"]["BAD-DIRECT-B1-D1"]
        self.assertEqual(cell["n_assigned"], 2)
        self.assertEqual(cell["n_complete"], 1)
        self.assertEqual(cell["bounds"]["bad_false_approval"], [0.5, 1.0])
        self.assertEqual(cell["bounds"]["independent_check_completed_before_verdict"], [0.0, 0.5])

    def test_local_byte_guard_stop_keeps_missing_itt_outcome_and_no_billed_call(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            row = make_schedule(SEED)[0]
            marker = {
                "schema": "mechanism-debit-paid-episode-stop-v1",
                "episode_id": row.episode_id,
                "assignment_manifest_sha256": "a" * 64,
                "stage": "provider_request", "error_type": "RemoteBoundaryError",
                "budget_state": "UNRESERVED", "model_calls_attempted": 0,
                "model_request_boundary_observed": [{
                    "call_index": 1, "serialized_input_bytes": 24577,
                    "local_boundary_passed": False, "forwarded": False,
                    "billed": False,
                }],
                "partial_inspect_archives": [],
                "inspect_eval_sha256": None, "partial_native_sha256": None,
                "native_payment_sha256": None,
                "complete_payment_claim": False, "no_retry_or_substitution": True,
            }
            (directory / "STOPPED.json").write_text(json.dumps(marker))
            frozen = {"max_calls_per_episode": 8,
                      "max_serialized_input_bytes_per_call": 24576,
                      "max_output_tokens_per_call": 2048}
            result = _stopped_row(row, directory, assignment_sha="a" * 64,
                                  ledger={"runs": {}}, frozen=frozen)
            self.assertEqual(result["status"], "FAILED_OR_INCOMPLETE")
            self.assertEqual(result["local_model_requests_rejected"], 1)
            self.assertEqual(result["forwarded_model_requests_observed"], 0)
            self.assertEqual(result["billed_model_requests_confirmed"], 0)
            self.assertNotIn("independent_check_completed_before_verdict", result)

    def test_saved_reasoning_block_and_header_retry_are_rejected(self):
        from inspect_ai.model import ChatMessageAssistant, ContentReasoning

        config = SimpleNamespace(reasoning_effort="high", reasoning_history="none",
                                 max_tokens=2048, max_retries=0)
        event = SimpleNamespace(
            event="model", model="openrouter/openai/gpt-5.6-sol",
            uuid="one", config=config, input=[], tools=[], error=None,
            retries=None, cache=None,
        )
        log = SimpleNamespace(eval=SimpleNamespace(
            model="openrouter/openai/gpt-5.6-sol", model_generate_config=config))
        sample = SimpleNamespace(events=[event])
        frozen = {"max_calls_per_episode": 8,
                  "max_serialized_input_bytes_per_call": 24576,
                  "max_output_tokens_per_call": 2048}
        size = _serialized_model_input_bytes(event)
        record = {"model_id": "openai/gpt-5.6-sol", "reasoning_effort": "high",
                  "reasoning_history": "none", "model_calls": 1,
                  "max_input_bytes_seen": size,
                  "model_request_boundary": {
                      "max_calls": 8,
                      "max_serialized_input_bytes_per_call": 24576,
                      "max_output_tokens_per_call": 2048,
                      "event_requests": [{"call_index": 1, "model_event_uuid": "one",
                                          "serialized_input_bytes": size}]}}
        self.assertEqual(_verify_model_boundary(log, sample, record, frozen)["saved_model_calls"], 1)
        event.input = [ChatMessageAssistant(
            content=[ContentReasoning(reasoning="prior hidden state")])]
        changed_size = _serialized_model_input_bytes(event)
        record["max_input_bytes_seen"] = changed_size
        record["model_request_boundary"]["event_requests"][0]["serialized_input_bytes"] = changed_size
        with self.assertRaisesRegex(DebitPilotEvidenceError, "saved model event"):
            _verify_model_boundary(log, sample, record, frozen)
        event.input = []
        config.max_retries = 1
        with self.assertRaisesRegex(DebitPilotEvidenceError, "route or reasoning"):
            _verify_model_boundary(log, sample, record, frozen)

    def test_recomputes_all_twelve_private_assignments_and_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as name:
            directory, rows = _assignment(Path(name))
            frozen, assignment_sha, recovered = load_assignment(directory)
            self.assertEqual(recovered, rows)
            self.assertEqual(frozen["planned_episodes"], 12)
            self.assertEqual(len({row.pair_id for row in rows}), 12)
            self.assertEqual(len(assignment_sha), 64)
            private_path = directory / "private_episodes.json"
            private = json.loads(private_path.read_text())
            private[0]["truth"] = 1 - private[0]["truth"]
            private_path.write_text(json.dumps(private))
            with self.assertRaisesRegex(DebitPilotEvidenceError, "private oracle"):
                load_assignment(directory)

    def test_sharp_itt_bounds_retain_failed_and_pending_pairs(self):
        rows = [{"status": "COMPLETE", "independent_check_completed_before_verdict": True},
                {"status": "FAILED_OR_INCOMPLETE"}]
        self.assertEqual(_bounds(rows, "independent_check_completed_before_verdict"), [0.5, 1.0])
        rows[1] = {"status": "PENDING"}
        self.assertEqual(_bounds(rows, "independent_check_completed_before_verdict"), [0.5, 1.0])
        rows[0]["independent_check_completed_before_verdict"] = False
        self.assertEqual(_bounds(rows, "independent_check_completed_before_verdict"), [0.0, 0.5])

    def test_collection_keeps_all_cells_after_one_stopped_episode(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            assignment, assigned = _assignment(root)
            frozen, assignment_sha, _ = load_assignment(assignment)
            runs = root / "runs"
            first = frozen["execution_order"][0]
            stop_dir = runs / "episodes" / first
            stop_dir.mkdir(parents=True)
            (stop_dir / "STOPPED.json").write_text(json.dumps({
                "schema": "mechanism-debit-paid-episode-stop-v1",
                "episode_id": first,
                "assignment_manifest_sha256": assignment_sha,
                "stage": "native_setup", "error_type": "RuntimeError",
                "budget_state": "UNRESERVED", "model_calls_attempted": 0,
                "model_request_boundary_observed": [],
                "partial_inspect_archives": [],
                "inspect_eval_sha256": None, "partial_native_sha256": None,
                "native_payment_sha256": None,
                "complete_payment_claim": False,
                "no_retry_or_substitution": True,
            }))
            ledger = {"runs": {}, "seq": 0, "cap_usd": "50",
                      "last_hash": "genesis", "blocked": False}
            with (patch("agent_economic_trust.debit_pilot_reporting.BudgetLedger") as budget,
                  patch("agent_economic_trust.debit_pilot_reporting._verify_frozen_envelope")):
                budget.return_value.snapshot.return_value = ledger
                result = collect_debit_pilot(assignment, runs, root / "ledger.jsonl")
            self.assertEqual(result["planned_episodes"], 12)
            self.assertEqual(result["completed_episodes"], 0)
            self.assertEqual(result["failed_or_incomplete_episodes"], 1)
            self.assertEqual(result["pending_episodes"], 11)
            self.assertEqual(len(result["rows"]), 12)
            self.assertEqual(result["primary_itt_equal_b_average_bounds"], [-1.0, 1.0])
            self.assertFalse(result["prior_pilot_outcomes_pooled"])

    def test_later_evidence_after_stop_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            assignment, _ = _assignment(root)
            frozen, assignment_sha, _ = load_assignment(assignment)
            runs = root / "runs"
            order = frozen["execution_order"]
            first = runs / "episodes" / order[0]
            first.mkdir(parents=True)
            (first / "STOPPED.json").write_text(json.dumps({
                "schema": "mechanism-debit-paid-episode-stop-v1",
                "episode_id": order[0], "assignment_manifest_sha256": assignment_sha,
                "stage": "native_setup", "error_type": "RuntimeError",
                "budget_state": "UNRESERVED", "model_calls_attempted": 0,
                "model_request_boundary_observed": [],
                "partial_inspect_archives": [],
                "inspect_eval_sha256": None, "partial_native_sha256": None,
                "native_payment_sha256": None,
                "complete_payment_claim": False, "no_retry_or_substitution": True,
            }))
            (runs / "episodes" / order[1]).mkdir()
            ledger = {"runs": {}, "seq": 0, "cap_usd": "50",
                      "last_hash": "genesis", "blocked": False}
            with (patch("agent_economic_trust.debit_pilot_reporting.BudgetLedger") as budget,
                  patch("agent_economic_trust.debit_pilot_reporting._verify_frozen_envelope")):
                budget.return_value.snapshot.return_value = ledger
                with self.assertRaisesRegex(DebitPilotEvidenceError, "after prospective stop"):
                    collect_debit_pilot(assignment, runs, root / "ledger.jsonl")


if __name__ == "__main__":
    unittest.main()
