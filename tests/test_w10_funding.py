"""Native local fee receipts, application obligation mapping, and tamper checks."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.w10_factorial import make_assignments, task_for_trial  # noqa: E402
from agent_economic_trust.w10_funding import NativePairFundingVerifier  # noqa: E402


SEED = "03" * 32


class W10NativeFundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="w10-native-funding-", dir="/workspace")
        cls.root = Path(cls.temp.name)
        cls.plan = cls.root / "plan"
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "run_w10_factorial.py"),
            "freeze", "--output", str(cls.plan), "--seed", SEED,
        ], cwd=ROOT, check=True, capture_output=True, text=True, timeout=15)
        cls.output = cls.root / "native"
        cls.completed = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "run_w10_native_funding.py"),
            "--plan", str(cls.plan), "--output", str(cls.output),
        ], cwd=ROOT, check=True, capture_output=True, text=True, timeout=60)
        cls.evidence_path = cls.output / "evidence.json"
        cls.evidence = json.loads(cls.evidence_path.read_text())
        cls.plan_sha = sha256((cls.plan / "assignment_manifest.json").read_bytes()).hexdigest()
        cls.rows = make_assignments(SEED)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def _tamper(self, mutator):
        candidate = deepcopy(self.evidence)
        mutator(candidate)
        path = self.root / f"tampered-{len(list(self.root.glob('tampered-*')))}.json"
        path.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            NativePairFundingVerifier(path, self.rows, self.plan_sha)

    def test_native_funding_matches_all_frozen_pair_relationships(self):
        verifier = NativePairFundingVerifier(self.evidence_path, self.rows, self.plan_sha)
        self.assertEqual(len(verifier.by_trial), 32)
        self.assertEqual(self.evidence["native_transactions_count"], 65)
        self.assertEqual(self.evidence["chain"]["rpc_host"], "127.0.0.1")
        self.assertEqual(self.evidence["payment_tier"], "NATIVE_LOCAL_ERC20")
        self.assertEqual(self.evidence["model_behavior_tier"], "NOT_EXECUTED")
        self.assertEqual(self.evidence["obligation_binding"], "APPLICATION_UNIQUE_TX_MAP")
        all_addresses = set()
        for trial in self.rows:
            observed = verifier(trial)
            self.assertEqual(observed.payer_role, "worker" if trial.r else "client")
            self.assertEqual(observed.obligation_id, trial.obligation_id)
            self.assertEqual(observed.pair_id, trial.pair_id)
            self.assertEqual(observed.amount_minor, 2_000_000)
            self.assertEqual(observed.chain_id, 31337)
            pair = next(pair for pair in self.evidence["pairs"]
                        if pair["trial_id"] == trial.trial_id)
            all_addresses.update(pair["addresses"].values())
        self.assertEqual(len(all_addresses), 96)
        self.assertEqual(sum(pair["R"] == 0 for pair in self.evidence["pairs"]), 16)
        self.assertEqual(sum(pair["R"] == 1 for pair in self.evidence["pairs"]), 16)
        self.assertEqual(self.evidence["asset"]["real_value"], 0)
        # This makes the relationship eligible for a task; no model is called.
        task = task_for_trial(self.rows[0], verify_funding=verifier)
        self.assertEqual(task.name, "protected_receipt_orbit")
        evidence_text = self.evidence_path.read_text()
        self.assertNotIn("private_key", evidence_text)
        self.assertNotIn("mnemonic", evidence_text)

    def test_wrong_payer_amount_obligation_and_duplicate_transaction_rejected(self):
        self._tamper(lambda data: data["pairs"][0].update({"obligation_id": "wrong"}))
        self._tamper(lambda data: data["pairs"][0]["balances_after_minor"].update(
            {"auditor": 1_999_999}))
        self._tamper(lambda data: data["pairs"][0]["transfer_transaction"].update(
            {"hash": data["pairs"][1]["transfer_transaction"]["hash"]}))
        self._tamper(lambda data: data["pairs"][0]["transfer_transaction"]["raw_transaction"].update(
            {"from": data["pairs"][0]["addresses"]["auditor"]}))
        self._tamper(lambda data: data["pairs"][0]["transfer_transaction"]["raw_receipt"].update(
            {"status": "0x0"}))

    def test_refuses_overwrite_of_native_receipts(self):
        attempt = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "run_w10_native_funding.py"),
            "--plan", str(self.plan), "--output", str(self.output),
        ], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(attempt.returncode, 0)
        self.assertIn("FileExistsError", attempt.stderr)


if __name__ == "__main__":
    unittest.main()
