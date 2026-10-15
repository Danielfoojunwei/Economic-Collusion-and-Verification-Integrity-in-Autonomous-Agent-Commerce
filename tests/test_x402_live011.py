"""Prospective assignment, truth boundary, native receipt and budget controls."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_economic_trust.x402_audit_retainer import (
    AUDITOR_WALLET, FEE_MINOR, SERVICE_ID, RetainerAssignment, digest,
    intake_body)
from agent_economic_trust.x402_live011_plan import (
    SOL, SONNET, full_block_reserve, make_schedule, prospective_manifest,
    required_headroom, reserve_pair, validate_rows)
from agent_economic_trust.x402_live011_task import (
    _public_retainer, x402_live011_orbit)
from agent_economic_trust.x402_live011_boundary import (
    ROLE_TOOLS, TOOL_FIELDS, offline_real_tool_schema_control, strict_tools)
from agent_economic_trust.mpp005_boundary import RemoteBoundaryError


def receipt(row):
    assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                    row.truth, row.payer_role)
    return {"status": "AUDIT_INTAKE_PAID", "service_id": SERVICE_ID,
            "obligation_id": row.obligation_id, "payer_role": row.payer_role,
            "payee_role": "auditor", "payee": AUDITOR_WALLET,
            "amount_minor_units": FEE_MINOR,
            "transaction_hash": "0x" + "a" * 64,
            "body_sha256": digest(intake_body(assignment)),
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "proves_invoice_quality": False, "audit_verdict": None}


def catalog():
    return {model: {"model_id": model, "context_length": 200_000,
                    "max_completion_tokens": 8_192,
                    "input_usd_per_token": inp,
                    "output_usd_per_token": out,
                    "request_usd": "0", "catalog_model_sha256": "a" * 64}
            for model, inp, out in ((SOL, "0.00001", "0.00003"),
                                    (SONNET, "0.000004", "0.00001"))}


class X402Live011Tests(unittest.TestCase):
    def setUp(self):
        self.rows = make_schedule("00" * 32)

    def test_four_fresh_cells_keep_truth_blind_and_payer_matched(self):
        validate_rows(self.rows)
        manifest = prospective_manifest("00" * 32, self.rows)
        self.assertEqual(len(manifest["execution_order"]), 4)
        self.assertEqual(manifest["status"], "UNFROZEN_NO_PAID_EXECUTION")
        self.assertTrue(manifest["model_direction_replication_needed"])
        self.assertTrue(all(r.provider_model_id == SOL and
                            r.auditor_model_id == SONNET for r in self.rows))
        self.assertEqual({(r.truth, r.payer_role) for r in self.rows},
                         {(a, b) for a in ("good", "bad")
                          for b in ("provider", "buyer")})
        public = json.dumps(manifest["public_rows"])
        self.assertNotIn('"truth"', public)
        self.assertNotIn("-good-", public)
        self.assertNotIn("-bad-", public)
        with self.assertRaises(ValueError):
            make_schedule("00" * 31)
        with self.assertRaises(ValueError):
            validate_rows(tuple(replace(r, provider_model_id=SONNET)
                                for r in self.rows))

    def test_native_retainer_public_binding_rejects_wrong_role_or_body(self):
        row = self.rows[0]
        good = receipt(row)
        self.assertEqual(_public_retainer(row, good), good)
        for key, value in (("payer_role", "outsider"),
                           ("payee", "0x" + "0" * 40),
                           ("amount_minor_units", FEE_MINOR + 1),
                           ("body_sha256", "0" * 64),
                           ("audit_verdict", "ACCEPT"),
                           ("transaction_hash", "invalid")):
            bad = {**good, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                _public_retainer(row, bad)
        with self.assertRaises(ValueError):
            _public_retainer(row, {**good, "oracle_status": "PASS"})

    def test_orbit_roles_and_public_inputs_do_not_leak_bad_truth(self):
        row = next(r for r in self.rows if r.truth == "bad")
        task = x402_live011_orbit(
            row, retainer_receipt=receipt(row),
            native_check=lambda *_: {}, native_settle=lambda *_: {})
        sample = task.dataset[0]
        setup = sample.metadata["experiment"]["setup"]["agents"]
        provider, auditor = setup
        self.assertEqual(provider["model"], "openrouter/" + SOL)
        self.assertEqual(auditor["model"], "openrouter/" + SONNET)
        self.assertEqual(provider["tools"], ["submit_audit_request"])
        self.assertEqual(auditor["tools"], ["view_audit_intake",
                                            "pay_for_independent_check",
                                            "issue_invoice_verdict"])
        self.assertIn("BAD", provider["system_prompt"])
        self.assertNotIn("BAD", auditor["system_prompt"])
        self.assertNotIn("net_amount_cents", auditor["system_prompt"])
        self.assertNotIn("purchase_order_amount_cents", auditor["system_prompt"])
        self.assertNotIn("BAD", sample.input)
        self.assertNotIn("net_amount_cents", sample.input)
        self.assertEqual(sample.metadata["x402_live011"]["payer_role"], row.payer_role)
        self.assertEqual(sample.metadata["x402_live011"]["scheduled_activations"], 10)

    def test_full_block_budget_includes_contingency_and_unassigned_residual(self):
        prices = catalog()
        for row in self.rows:
            self.assertEqual(reserve_pair(prices, row), Decimal("4.407296"))
        self.assertEqual(full_block_reserve(prices, self.rows), Decimal("17.629184"))
        self.assertEqual(required_headroom(prices, self.rows),
                         Decimal("19.6292182"))
        bad = catalog()
        bad[SONNET]["context_length"] = 1_000
        with self.assertRaises(ValueError):
            required_headroom(bad, self.rows)

    def test_high_reasoning_boundary_rejects_role_and_non_strict_tools(self):
        def serialized(role):
            return [{"type": "function", "function": {
                "name": name, "strict": True,
                "parameters": {"type": "object", "additionalProperties": False,
                               "properties": {field: ({"anyOf": [
                                   {"type": part} for part in kind.split("|")]}
                                   if "|" in kind else {"type": kind})
                                   for field, kind in TOOL_FIELDS[name].items()},
                               "required": list(TOOL_FIELDS[name])}}}
                    for name in sorted(ROLE_TOOLS[role])]
        provider = serialized("provider")
        auditor = serialized("auditor")
        self.assertEqual(len(strict_tools(provider, "provider")), 64)
        self.assertEqual(len(strict_tools(auditor, "auditor")), 64)
        with self.assertRaises(RemoteBoundaryError):
            strict_tools(provider, "auditor")
        provider[0]["function"]["parameters"]["additionalProperties"] = True
        with self.assertRaises(RemoteBoundaryError):
            strict_tools(provider, "provider")

    def test_actual_orbit_tool_schemas_are_strict_without_model_calls(self):
        control = offline_real_tool_schema_control()
        self.assertEqual(control["status"], "PASS")
        self.assertEqual(control["paid_model_calls"], 0)
        self.assertEqual(set(control["roles"]["provider"]["tools"]),
                         ROLE_TOOLS["provider"])
        self.assertEqual(set(control["roles"]["auditor"]["tools"]),
                         ROLE_TOOLS["auditor"])

    def test_frozen_schema_status_override_keeps_every_preview_invariant(self):
        from scripts.freeze_x402_live011 import (
            freeze_payload, validate_frozen_manifest)
        prices = catalog()
        state = {"seq": 10, "last_hash": "a" * 64, "cap_usd": "50",
                 "available_usd": "50", "runs": {}}
        frozen = freeze_payload("00" * 32, self.rows,
            sources={"source.py": "b" * 64}, runtime={"pinned": True},
            offline={"status": "PASS"}, prices=prices, state=state,
            clearance={"status": "GO"})
        validate_frozen_manifest("00" * 32, frozen, self.rows)
        self.assertEqual(frozen["schema"], "x402-live011-first-assignment-v1")
        self.assertEqual(frozen["status"], "FROZEN_NOT_EXECUTED")
        self.assertEqual(frozen["budget_gate"]["full_block_plus_contingency_residual_usd"],
                         "19.6292182")
        for change in ({"schema": "preview"}, {"status": "UNFROZEN_NO_PAID_EXECUTION"},
                       {"execution_order": list(reversed(frozen["execution_order"]))}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_frozen_manifest("00" * 32, {**frozen, **change}, self.rows)

    def test_cross_study_clearance_binds_both_final_denominators(self):
        from scripts import freeze_x402_live011 as gate
        with TemporaryDirectory() as scratch:
            root = Path(scratch)

            def put(name, value):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, sort_keys=True) + "\n")
                return path

            ledger = put("artifacts/budget/openrouter-ledger.jsonl",
                         {"hash": "a" * 64})
            mpp_ids = [f"mpp-{i}" for i in range(10)]
            fee_ids = [f"fee-{i}" for i in range(8)]
            mpp_path = put("artifacts/gates/MPP010/assignment-001/assignment_manifest.json",
                           {"execution_order": mpp_ids})
            put("artifacts/gates/MPP010/first-freeze.lock.json",
                {"schema": "mpp010-one-time-freeze-v1",
                 "assignment_manifest_sha256": gate.sha(mpp_path)})
            mpp_report = put("artifacts/gates/MPP010/final-collection.json",
                {"schema": "mpp010-collection-v1",
                 "assignment_manifest_sha256": gate.sha(mpp_path),
                 "planned_episodes": 10,
                 "rows": [{"episode_id": item, "status": "COMPLETE"}
                          for item in mpp_ids]})
            fee_path = put("artifacts/gates/ERC8183_FEE011/assignment-001/assignment_manifest.json",
                           {"execution_order": fee_ids})
            put("artifacts/gates/ERC8183_FEE011/first-freeze.lock.json",
                {"schema": "fee011-first-freeze-lock-v1",
                 "assignment_manifest_sha256": gate.sha(fee_path)})
            fee_report = put("artifacts/gates/ERC8183_FEE011/final-collection.json",
                {"schema": "fee011-itt-collection-v1",
                 "assignment_manifest_sha256": gate.sha(fee_path),
                 "planned_episodes": 8,
                 "rows": [{"episode_id": item, "status": "COMPLETE"}
                          for item in fee_ids]})
            state = {"seq": 0, "last_hash": "a" * 64, "cap_usd": "50"}
            with (patch.object(gate, "ROOT", root),
                  patch.object(gate, "CANONICAL_LEDGER", ledger),
                  patch.object(gate, "CLEARANCE", root /
                      "artifacts/gates/X402_LIVE011/cross-study-clearance-001.json")):
                inventory = gate.competing_gate_inventory()
                saved = {"schema": "x402-live011-cross-study-clearance-v1",
                    "status": "GO_AFTER_MPP010_FINAL_DISPOSITION",
                    "mpp010_disposition": "CLOSED_AFTER_COMPLETE_COLLECTION",
                    "mpp010_final_collection_path": str(mpp_report.relative_to(root)),
                    "mpp010_final_collection_sha256": gate.sha(mpp_report),
                    "fee011_disposition": "CLOSED_AFTER_ALL_ROWS_COLLECTED",
                    "fee011_final_collection_path": str(fee_report.relative_to(root)),
                    "fee011_final_collection_sha256": gate.sha(fee_report),
                    "competing_gate_inventory_sha256": gate.digest(inventory),
                    "ledger_at_clearance": state}
                put("artifacts/gates/X402_LIVE011/cross-study-clearance-001.json", saved)
                self.assertEqual(gate.cross_study_clearance(state, current_head=True)
                                 ["fee011_final_collection_sha256"], gate.sha(fee_report))
                changed = {**saved, "fee011_disposition": "NOT_FROZEN"}
                put("artifacts/gates/X402_LIVE011/cross-study-clearance-001.json", changed)
                with self.assertRaises(ValueError):
                    gate.cross_study_clearance(state, current_head=True)
                changed = {**saved, "fee011_final_collection_sha256": "0" * 64}
                put("artifacts/gates/X402_LIVE011/cross-study-clearance-001.json", changed)
                with self.assertRaises(ValueError):
                    gate.cross_study_clearance(state, current_head=True)


if __name__ == "__main__":
    unittest.main()
