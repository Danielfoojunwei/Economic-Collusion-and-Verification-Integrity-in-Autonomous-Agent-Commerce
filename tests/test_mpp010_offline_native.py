"""Pure zero-model checks for the MPP010 scripted native-control runner."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

from scripts.run_mpp010_offline_native import (
    ROOT, SOURCE_FILES, controls, scripted_model, verify_offline_report,
)
from agent_economic_trust.mpp010_plan import MAX_INPUT_BYTES


class ScriptedNativeControlsTests(unittest.TestCase):
    def test_marker_rejects_mpp009_chain_with_same_genesis(self):
        """A separate 1337 chain must lack MPP010's first transfer marker."""
        for port in (19767, 19667):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    pass
            except OSError:
                self.skipTest("both isolated historical Tempo chains are required")
        module_dir = ROOT / "protocols/mpp"
        code = ("import {createClient,http} from 'viem';"
                "import {verifyMpp010Chain,RPC_URL} from './mpp010-chain-identity.mjs';"
                "await verifyMpp010Chain(createClient({transport:http(process.argv[1],"
                "{retryCount:0})}),RPC_URL)")
        good = subprocess.run(["node", "--input-type=module", "-e", code,
                               "http://127.0.0.1:19767"], cwd=module_dir,
                              capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(good.returncode, 0, good.stderr)
        wrong = subprocess.run(["node", "--input-type=module", "-e", code,
                                "http://127.0.0.1:19667"], cwd=module_dir,
                               capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("AssertionError", wrong.stderr)

    def test_frozen_mpp009_receipt_rejected_by_mpp010_verifier(self):
        foreign = ROOT / ("artifacts/prospective/mpp009-scripted-native-001/"
                          "good-2000-bonus0-sol-sonnet-checked/check-evidence.json")
        if not foreign.is_file():
            self.skipTest("frozen MPP009 receipt is unavailable")
        verifier = ROOT / "protocols/mpp/mpp010-verify-meeting-service.mjs"
        result = subprocess.run(["node", str(verifier), str(foreign)], cwd=ROOT,
            capture_output=True, text=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AssertionError", result.stderr)

    def test_native_verifier_rejects_tampered_402_terms(self):
        """Saved 402 terms must match the independently verified native debit."""
        root = Path(__file__).resolve().parents[1]
        directory = root / ("artifacts/prospective/mpp010-scripted-native-001/"
                            "good-2000-bonus0-sol-sonnet-checked")
        check_path = directory / "check-evidence.json"
        release_path = directory / "release-evidence.json"
        if not check_path.is_file() or not release_path.is_file():
            self.skipTest("saved MPP010 native controls are unavailable")
        endpoint = urlsplit(json.loads(check_path.read_text())["rpc_url"])
        try:
            with socket.create_connection((endpoint.hostname, endpoint.port), timeout=1):
                pass
        except OSError:
            self.skipTest("isolated MPP010 historical local chain is unavailable")
        verifier = root / "protocols/mpp/mpp010-verify-meeting-service.mjs"

        def run(path):
            return subprocess.run(["node", str(verifier), str(path)], cwd=root,
                capture_output=True, text=True, timeout=30, check=False)

        for operation, original in (("check", check_path), ("release", release_path)):
            self.assertEqual(run(original).returncode, 0, operation)
            saved = json.loads(original.read_text())
            mutations = [(("intent",), "session"),
                         (("method",), "other"),
                         (("request", "amount"), str(int(saved["amount_atomic"]) + 1)),
                         (("request", "currency"), "0x" + "0" * 40),
                         (("request", "recipient"), saved["accounts"]["treasury"]),
                         (("request", "methodDetails", "chainId"), 1)]
            with tempfile.TemporaryDirectory(prefix="mpp010-challenge-tamper-") as temporary:
                for number, (keys, wrong) in enumerate(mutations):
                    with self.subTest(operation=operation, field=".".join(keys)):
                        corrupted = json.loads(original.read_text())
                        target = next(event["challenge"] for event in corrupted["events"]
                                      if event["status"] == 402)
                        for key in keys[:-1]:
                            target = target[key]
                        self.assertNotEqual(wrong, target[keys[-1]])
                        target[keys[-1]] = wrong
                        path = Path(temporary) / f"{operation}-{number}.json"
                        path.write_text(json.dumps(corrupted))
                        result = run(path)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("AssertionError", result.stderr)

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
        with tempfile.TemporaryDirectory(prefix="mpp010-scripted-report-") as temporary:
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

    def test_report_binds_portable_compensation_paths(self):
        """A moved archive may use relative row paths; absolute paths cannot pass."""
        with tempfile.TemporaryDirectory(prefix="mpp010-portable-report-") as temporary:
            report = Path(temporary) / "summary.json"
            rows = [{"label": case.label,
                     "compensation_evidence": f"{case.label}/compensation-evidence.json"}
                    for case in controls()]
            summary = {"status": "PASS", "remote_model_calls": 0,
                       "model_execution_tier": "SCRIPTED_SIMULATION",
                       "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
                       "max_serialized_input_bytes": 1, "rows": rows,
                       "source_sha256": {name: sha256((ROOT / name).read_bytes()).hexdigest()
                                         for name in SOURCE_FILES}}
            report.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "archive absent or changed"):
                verify_offline_report(report)
            for wrong in (str(report.parent / rows[0]["compensation_evidence"]),
                          "../other-control/compensation-evidence.json"):
                with self.subTest(path=wrong):
                    summary["rows"][0]["compensation_evidence"] = wrong
                    report.write_text(json.dumps(summary))
                    with self.assertRaisesRegex(ValueError, "incomplete or exceeds"):
                        verify_offline_report(report)


if __name__ == "__main__":
    unittest.main()
