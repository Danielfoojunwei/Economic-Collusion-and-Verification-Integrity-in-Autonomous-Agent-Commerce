"""Independent checks of saved ERC-8183 Anvil receipts and token transfers."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_erc8183_local.py"
CAST = ROOT.parent / ".tools" / "foundry" / "v1.8.5" / "cast"
ZERO = "0x" + "00" * 20


def _topic(signature: str) -> str:
    return subprocess.run([str(CAST), "keccak", signature], check=True, capture_output=True,
                          text=True).stdout.strip().lower()


class ERC8183NativeEvidenceTests(unittest.TestCase):
    def test_local_receipts_reconstruct_conserved_balances_and_native_outcomes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="erc8183-native-") as directory:
            output = Path(directory) / "run"
            subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                           cwd=ROOT, check=True, capture_output=True, text=True, timeout=45)
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["source"]["commit"],
                             "142e669c1fd318486a4628395b629f033654dd06")
            self.assertEqual(evidence["chain"]["rpc_host"], "127.0.0.1")
            self.assertEqual(evidence["model_behavior_tier"], "SCRIPTED")
            self.assertEqual(evidence["payment_tier"], "NATIVE_LOCAL_CHAIN")
            for contract in evidence["contracts"].values():
                artifact = json.loads(Path(contract["artifact_path"]).read_text(encoding="utf-8"))
                abi = json.dumps(artifact["abi"], sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.assertEqual(sha256(abi).hexdigest(), contract["abi_sha256"])

            transactions = evidence["transactions"]
            self.assertEqual(len(transactions), 49)
            self.assertEqual(sum(tx["status"] == 0 for tx in transactions), 8)
            self.assertEqual(sum(tx["status"] == 1 for tx in transactions), 41)
            by_step = {tx["step"]: tx for tx in transactions}
            self.assertEqual(len(by_step), len(transactions))
            token = evidence["contracts"]["MockUSDC"]["address"].lower()
            transfer_topic = _topic("Transfer(address,address,uint256)")
            ledger: defaultdict[str, int] = defaultdict(int)
            minted = 0
            for tx in transactions:
                raw = tx["raw_receipt"]
                self.assertRegex(tx["transaction_hash"], r"^0x[0-9a-fA-F]{64}$")
                self.assertEqual(raw["transactionHash"].lower(), tx["transaction_hash"].lower())
                self.assertEqual(int(raw["status"], 16), tx["status"])
                self.assertEqual(len(raw["logs"]), len(tx["logs"]))
                if tx["status"] == 0:
                    self.assertEqual(raw["logs"], [])
                for raw_log, log in zip(raw["logs"], tx["logs"]):
                    self.assertEqual(int(raw_log["logIndex"], 16), log["log_index"])
                    self.assertEqual(raw_log["topics"], log["topics"])
                    if raw_log["address"].lower() != token or raw_log["topics"][0].lower() != transfer_topic:
                        continue
                    sender = "0x" + raw_log["topics"][1][-40:].lower()
                    recipient = "0x" + raw_log["topics"][2][-40:].lower()
                    amount = int(raw_log["data"], 16)
                    if sender == ZERO:
                        minted += amount
                    else:
                        ledger[sender] -= amount
                    ledger[recipient] += amount

            self.assertEqual(minted, 120_000_000)
            self.assertEqual(minted, evidence["asset"]["supply_minor_units"])
            final = evidence["scenarios"]["partial_claim_after_expiry"]["after"]["balances_minor_units"]
            for role, address in evidence["actors"].items():
                self.assertEqual(ledger[address.lower()], final[role], role)
            escrow = evidence["contracts"]["ERC1967Proxy"]["address"].lower()
            self.assertEqual(ledger[escrow], final["escrow"])
            self.assertEqual(final["escrow"], 0)
            self.assertEqual(sum(final.values()), minted)

            bad = evidence["scenarios"]["bad_completed_without_app_guard"]
            self.assertEqual(bad["oracle_status"], "FAIL")
            self.assertEqual(bad["verdict_origin"], "fixed scripted evaluator decision")
            self.assertEqual(bad["job"]["status"], "Completed")
            self.assertEqual(bad["after"]["balances_minor_units"]["provider"] -
                             bad["before"]["balances_minor_units"]["provider"], 17_000_000)
            self.assertEqual(by_step["bad.complete_without_guard"]["status"], 1)
            self.assertIn("PaymentReleased", {log["name"] for log in by_step["bad.complete_without_guard"]["logs"]})

            for step in ("good.replay_complete", "reject.wrong_actor_complete", "reject.wrong_actor_reject",
                         "reject.replay_reject",
                         "submitted_expiry.early_refund", "claim.replay_rejected_8", "claim.wrong_binding",
                         "claim.pending_blocks_refund"):
                self.assertEqual(by_step[step]["status"], 0, step)
            self.assertIn("ClaimRejected", {log["name"] for log in by_step["claim.reject_8"]["logs"]})
            self.assertEqual(evidence["scenarios"]["wrong_roles_then_reject"]["job"]["status"], "Rejected")
            submitted = evidence["scenarios"]["submitted_grace_refund"]
            self.assertGreaterEqual(by_step["submitted_expiry.early_refund"]["block_timestamp"],
                                    submitted["expiry"])
            self.assertLess(by_step["submitted_expiry.early_refund"]["block_timestamp"],
                            submitted["expiry"] + 3600)
            self.assertGreaterEqual(by_step["submitted_expiry.refund_after_grace"]["block_timestamp"],
                                    submitted["expiry"] + 3600)
            claim = evidence["scenarios"]["partial_claim_after_expiry"]
            self.assertGreaterEqual(by_step["claim.approve_after_expiry"]["block_timestamp"], claim["expiry"])
            self.assertEqual(claim["job"]["settled_amount_minor_units"], 10_000_000)
            self.assertEqual(claim["job"]["status"], "Expired")

            saved = (output / "evidence.json").read_text(encoding="utf-8")
            self.assertNotRegex(saved, re.compile(r'"(?:private_key|mnemonic|secret)"\s*:', re.I))

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="erc8183-existing-") as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), "--output", directory],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite native receipts", result.stderr)


if __name__ == "__main__":
    unittest.main()
