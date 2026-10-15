"""FEE014 source-level monetary, hold and offline control gates."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from inspect_ai.log import read_eval_log

from agent_economic_trust.fee014_budget import (EXACT_OPEN_IDS,
                                                exact_prior_holds,
                                                same_usd_amount)
from agent_economic_trust.fee014_offline import ARCHIVE, verify as verify_offline
from agent_economic_trust.fee014_plan import (CANONICAL_LEDGER, SONNET, SOL,
                                              per_row_reserve, required_headroom)
from agent_economic_trust.fee014_boundary import reported_reasoning
from agent_economic_trust.remote_budget import BudgetLedger
from agent_economic_trust import partial_claim_native_verifier
from scripts import fee014_freeze
from scripts import partial_claim_freeze


class Fee014RuntimeGates(unittest.TestCase):
    def test_settled_usd_uses_numeric_decimal_equality(self):
        self.assertTrue(same_usd_amount("0.05069", "0.050690"))
        self.assertTrue(same_usd_amount("0.050690", "0.05069"))
        self.assertTrue(same_usd_amount("0E-7", "0.000000"))
        for different in ("0.050691", "0.05068", "0.15069"):
            self.assertFalse(same_usd_amount("0.05069", different))
        for invalid in ("NaN", "Infinity", "-Infinity", "-0.01", "nonsense", None,
                        0.05069, True):
            self.assertFalse(same_usd_amount("0.05069", invalid))
            self.assertFalse(same_usd_amount(invalid, "0.05069"))

    def test_three_old_holds_and_frozen_fee012_settlement_retained(self):
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        projected = json.loads(json.dumps(state))
        projected["runs"] = {key: value for key, value in state["runs"].items()
                             if not key.startswith("fee013-")}
        projected["reserved_usd"] = "14.094300"
        result = exact_prior_holds(projected)
        self.assertEqual(set(result["exact_open_run_ids"]), EXACT_OPEN_IDS)
        self.assertEqual(Decimal(result["prior_reserved_usd"]), Decimal("14.094300"))
        fee012 = [item for name, item in state["runs"].items()
                  if name.startswith("fee012-")]
        self.assertEqual(len(fee012), 1)
        self.assertEqual(fee012[0]["status"], "SETTLED")
        self.assertTrue(same_usd_amount(fee012[0]["actual_usd"], "0.050690"))
        changed = json.loads(json.dumps(projected))
        changed["unknown_run_ids"] = ["unreconciled"]
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)
        changed = json.loads(json.dumps(projected))
        changed["reserved_usd"] = "14.094299"
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)
        changed = json.loads(json.dumps(projected))
        changed["runs"]["fee013-unfinished"] = {
            "status": "RESERVED", "reserved_usd": "1"}
        changed["reserved_usd"] = "15.094300"
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)

    def test_role_swapped_worst_case_catalog_reserve(self):
        manifest = Path(__file__).resolve().parents[1] / (
            "artifacts/gates/ERC8183_FEE013/assignment-001/assignment_manifest.json")
        prices = json.loads(manifest.read_bytes())["public_pricing_snapshot"]
        self.assertEqual(per_row_reserve(prices), Decimal("4.292608"))
        self.assertEqual(required_headroom(prices, 5), Decimal("23.4630742"))
        wrong = json.loads(json.dumps(prices))
        wrong.pop(SONNET)
        with self.assertRaises(ValueError):
            per_row_reserve(wrong)
        wrong = json.loads(json.dumps(prices))
        wrong[SOL]["model_id"] = SONNET
        with self.assertRaises(ValueError):
            per_row_reserve(wrong)

    def test_predecessor_selector_rejects_partial_or_duplicate_terminal_archives(self):
        def archive(path: Path, name: str, complete: int, stopped: int,
                    pending: int) -> None:
            path.joinpath(name).write_text(json.dumps({
                "schema": "fee013-itt-collection-v1", "planned_episodes": 6,
                "rows": [{}] * 6, "completed_episodes": complete,
                "stopped_episodes": stopped, "pending_episodes": pending,
                "observed_incomplete_episodes": 0}))
        with TemporaryDirectory(prefix="fee014-selector-", dir="/tmp") as raw:
            root = Path(raw)
            with patch.object(fee014_freeze, "FEE013_GATE", root):
                archive(root, "collection-001.json", 2, 0, 4)
                with self.assertRaises(ValueError):
                    fee014_freeze._fee013_terminal_collection()
                archive(root, "collection-002.json", 3, 1, 2)
                path, saved = fee014_freeze._fee013_terminal_collection()
                self.assertEqual(path.name, "collection-002.json")
                self.assertEqual(saved["stopped_episodes"], 1)
                archive(root, "collection-003.json", 6, 0, 0)
                with self.assertRaises(ValueError):
                    fee014_freeze._fee013_terminal_collection()

    def test_intervening_partial_stop_raw_native_refund_and_ledger_gate(self):
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        with (patch.object(partial_claim_freeze, "_canonical_root", lambda: None),
              patch.object(partial_claim_native_verifier, "UPSTREAM",
                           Path("/workspace/upstreams/erc8183"))):
            result = fee014_freeze._partial013_stopped_clearance(state)
            self.assertEqual(result["completed_episodes"], 0)
            self.assertEqual(result["stopped_episodes"], 1)
            self.assertEqual(result["pending_episodes"], 4)
            self.assertEqual(result["native_terminal_verdict"], "REJECT")
            self.assertEqual(result["native_client_refund_minor"], 20_000_000)
            self.assertEqual(result["native_provider_gain_minor"], 0)
            with patch.object(fee014_freeze, "PARTIAL013_FORENSICS_SHA", "0" * 64):
                with self.assertRaises(ValueError):
                    fee014_freeze._partial013_stopped_clearance(state)
            changed = json.loads(json.dumps(state))
            changed["runs"][result["ledger_run_id"]]["actual_usd"] = "0.123223"
            with self.assertRaises(ValueError):
                fee014_freeze._partial013_stopped_clearance(changed)

    def test_eight_predecessor_native_cases_and_seven_tamper_negatives(self):
        report = verify_offline(ARCHIVE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["model_behavior_tier"], "SCRIPTED_SIMULATION")
        self.assertEqual(report["paid_model_calls"], 0)
        self.assertEqual(report["replay"]["scripted_native_cases_reverified"], 8)
        self.assertEqual(report["replay"]["scripted_bad_accept_positive_controls"], 1)
        self.assertEqual(report["replay"]["tamper_negatives_reverified"], 7)

    def test_reported_reasoning_reads_raw_saved_model_usage(self):
        source = (Path(__file__).resolve().parents[1] /
                  "artifacts/gates/ERC8183_FEE012/runs-001/episodes/"
                  "fee012-9d83103c141f26e01bb20f64/inspect.eval")
        sample = read_eval_log(str(source), resolve_attachments=True).samples[0]
        measured = reported_reasoning(sample)
        self.assertEqual(measured["reported_reasoning_tokens_by_role"],
                         {"provider": 139, "auditor": 33})
        self.assertEqual(measured["reported_reasoning_tokens_missing_by_role"],
                         {"provider": 0, "auditor": 0})


if __name__ == "__main__":
    unittest.main()
