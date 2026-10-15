"""Pure zero-model checks for the MPP009 scripted native-control runner."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from scripts.run_mpp009_offline_native import (
    controls, scripted_model, verify_offline_report,
)
from agent_economic_trust.mpp009_plan import MAX_INPUT_BYTES


class ScriptedNativeControlsTests(unittest.TestCase):
    def test_checked_matrix_and_extra_control_identity(self):
        cases = controls()
        self.assertEqual(len(cases), 9)
        self.assertEqual(len({case.row.episode_id for case in cases}), 9)
        self.assertEqual(len({case.label for case in cases}), 9)
        self.assertEqual({(case.row.truth, case.row.check_price_atomic,
                           case.row.provider_model_id, case.row.auditor_model_id)
                          for case in cases if case.checked},
            {(truth, price, provider, auditor)
             for truth in ("GOOD", "BAD") for price in (2000, 4000)
             for provider, auditor in {
                 (cases[0].row.provider_model_id, cases[0].row.auditor_model_id),
                 (cases[4].row.provider_model_id, cases[4].row.auditor_model_id)}})
        self.assertEqual([(case.row.truth, case.checked, case.authored_pressure)
                          for case in cases if case.authored_pressure],
                         [("BAD", False, True)])
        self.assertEqual({case.row.acceptance_bonus_atomic for case in cases
                          if case.row.truth == "GOOD"}, {0})

    def test_scripted_verdict_uses_paid_answer_and_stress_skips(self):
        bad = next(case for case in controls() if case.row.truth == "BAD" and case.checked)
        def message(function=None, result=None):
            return SimpleNamespace(
                tool_calls=[SimpleNamespace(function=function)] if function else [],
                function=function if result is not None else "",
                text=json.dumps(result) if result is not None else "")
        prior = [message(name) for name in
                 ("market_view", "market_accept", "market_view", "market_check")]
        tools = [SimpleNamespace(name="market_check")]
        failed = scripted_model(bad).api.outputs(
            prior + [message("market_check", {"status": "FAIL"})], tools, None, None)
        self.assertEqual(failed.choices[0].message.tool_calls[0].function, "market_decide")
        self.assertEqual(failed.choices[0].message.tool_calls[0].arguments["verdict"], "REJECT")
        self.assertIsNotNone(failed.usage)
        passed = scripted_model(bad).api.outputs(
            prior + [message("market_check", {"status": "PASS"})], tools, None, None)
        self.assertEqual(passed.choices[0].message.tool_calls[0].arguments["verdict"], "ACCEPT")
        stress = next(case for case in controls() if case.authored_pressure)
        skipped = scripted_model(stress).api.outputs(
            [message(name) for name in
             ("market_view", "market_accept", "market_view", "market_view")], tools, None, None)
        self.assertEqual(skipped.choices[0].message.tool_calls[0].arguments["verdict"], "ACCEPT")
        with self.assertRaisesRegex(ValueError, "paid check"):
            scripted_model(bad).api.outputs(prior, tools, None, None)

    def test_report_rejects_missing_rows_or_input_cap_violation(self):
        with tempfile.TemporaryDirectory(prefix="mpp009-scripted-report-") as temporary:
            report = Path(temporary) / "summary.json"
            report.write_text(json.dumps({"status": "PASS", "remote_model_calls": 0,
                "model_execution_tier": "SCRIPTED_SIMULATION",
                "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
                "max_serialized_input_bytes": MAX_INPUT_BYTES + 1,
                "rows": [{"label": case.label} for case in controls()]}))
            with self.assertRaisesRegex(ValueError, "incomplete or exceeds"):
                verify_offline_report(report)
            payload = json.loads(report.read_text())
            payload["max_serialized_input_bytes"] = 1
            payload["rows"].pop()
            report.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "incomplete or exceeds"):
                verify_offline_report(report)


if __name__ == "__main__":
    unittest.main()
