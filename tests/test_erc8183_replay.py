"""Independent checks of W07 snapshot replay and branch-local native receipts."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_erc8183_replay.py"
CAST = ROOT.parent / ".tools" / "foundry" / "v1.8.5" / "cast"


def _cast(*args: str) -> str:
    return subprocess.run([str(CAST), *args], check=True, capture_output=True, text=True).stdout.strip()


class ERC8183ReplayTests(unittest.TestCase):
    def test_frozen_decision_snapshot_replay_and_receipt_balances(self) -> None:
        with tempfile.TemporaryDirectory(prefix="erc8183-replay-") as directory:
            output = Path(directory) / "native"
            subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                           cwd=ROOT, check=True, capture_output=True, text=True, timeout=45)
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["work_order"], "W07")
            self.assertEqual(evidence["source"]["commit"], "142e669c1fd318486a4628395b629f033654dd06")
            self.assertEqual(evidence["chain"]["rpc_host"], "127.0.0.1")
            self.assertEqual(evidence["model_behavior_tier"], "SCRIPTED_SIMULATION")
            self.assertEqual(evidence["payment_tier"], "NATIVE_LOCAL_PROTOCOL")
            self.assertEqual(evidence["asset"]["real_value"], 0)
            self.assertEqual(set(evidence["pairs"]), {"good", "bad"})
            self.assertEqual(len(evidence["setup_transactions"]), 8)

            token = evidence["contracts"]["MockUSDC"]["address"].lower()
            escrow = evidence["contracts"]["ERC1967Proxy"]["address"].lower()
            transfer_topic = _cast("keccak", "Transfer(address,address,uint256)").lower()
            known = {address.lower(): role for role, address in evidence["actors"].items()}
            known[escrow] = "escrow"
            complete_selector = _cast("sig", "complete(uint256,bytes32,bytes)")
            reject_selector = _cast("sig", "reject(uint256,bytes32,bytes)")

            for case, pair in evidence["pairs"].items():
                self.assertEqual(pair["oracle_status"], "PASS" if case == "good" else "FAIL")
                self.assertEqual(pair["prestate"], pair["restored_prestate"])
                self.assertTrue(pair["identical_prestate"])
                self.assertEqual(pair["prestate"]["job"]["status"], "Submitted")
                self.assertEqual(pair["prestate"]["token_state"]["balances_minor_units"]["escrow"], 20_000_000)
                self.assertEqual(pair["frozen_auditor_decision"]["verdict"], "ACCEPT")
                self.assertFalse(pair["frozen_auditor_decision"]["check_completed"])
                self.assertEqual(pair["frozen_auditor_decision"]["artifact_digest"], pair["artifact_digest"])
                self.assertEqual(pair["submitted_event"]["data"].lower(), "0x" + pair["artifact_digest"])
                self.assertEqual(len(pair["preparation_transactions"]), 4)

                for arm_name, arm in pair["arms"].items():
                    transactions = arm["transactions"]
                    self.assertEqual(len(transactions), 2)
                    first, duplicate = transactions
                    self.assertEqual(first["status"], 1)
                    self.assertEqual(duplicate["status"], 0)
                    self.assertEqual(duplicate["raw_receipt"]["logs"], [])
                    self.assertEqual(first["raw_transaction"]["from"].lower(), evidence["actors"]["evaluator"].lower())
                    self.assertEqual(first["raw_transaction"]["to"].lower(), escrow)
                    self.assertEqual(first["raw_transaction"]["hash"].lower(), first["transaction_hash"].lower())
                    self.assertEqual(first["raw_transaction"]["blockHash"], first["raw_receipt"]["blockHash"])
                    self.assertEqual(first["raw_receipt"]["status"], "0x1")
                    self.assertEqual(duplicate["raw_receipt"]["status"], "0x0")
                    self.assertEqual(first["block_number"], pair["prestate"]["block_number"] + 1)
                    self.assertEqual(first["raw_transaction"]["nonce"],
                                     pair["prestate"]["actor_nonces"]["evaluator"].__format__("#x"))

                    deltas: defaultdict[str, int] = defaultdict(int)
                    for tx in transactions:
                        self.assertEqual(tx["raw_receipt"]["transactionHash"].lower(), tx["transaction_hash"].lower())
                        self.assertEqual(len(tx["logs"]), len(tx["raw_receipt"]["logs"]))
                        for saved_log, raw_log in zip(tx["logs"], tx["raw_receipt"]["logs"]):
                            self.assertEqual(saved_log["log_index"], int(raw_log["logIndex"], 16))
                            self.assertEqual(saved_log["topics"], raw_log["topics"])
                            if raw_log["address"].lower() != token or raw_log["topics"][0].lower() != transfer_topic:
                                continue
                            sender = "0x" + raw_log["topics"][1][-40:].lower()
                            recipient = "0x" + raw_log["topics"][2][-40:].lower()
                            amount = int(raw_log["data"], 16)
                            deltas[known[sender]] -= amount
                            deltas[known[recipient]] += amount
                    before = pair["prestate"]["token_state"]["balances_minor_units"]
                    after = arm["final_state"]["token_state"]["balances_minor_units"]
                    self.assertEqual({role: after[role] - before[role] for role in before},
                                     {role: deltas[role] for role in before})
                    replay_state = arm.get("post_replay_state", arm.get("pre_replay_state"))
                    self.assertEqual(replay_state["token_state"], arm["final_state"]["token_state"])
                    self.assertEqual(replay_state["job"], arm["final_state"]["job"])

                unguarded = pair["arms"]["unguarded"]
                guarded = pair["arms"]["guarded"]
                unguarded_first = unguarded["transactions"][0]
                guarded_first = guarded["transactions"][0]
                self.assertEqual(unguarded_first["raw_transaction"]["nonce"],
                                 guarded_first["raw_transaction"]["nonce"])
                expected_complete = _cast("calldata", "complete(uint256,bytes32,bytes)",
                                          str(pair["job_id"]), "0x" + pair["frozen_decision_sha256"], "0x")
                self.assertEqual(unguarded_first["raw_transaction"]["input"], expected_complete)
                self.assertEqual(unguarded_first["raw_transaction"]["input"][:10], complete_selector)
                self.assertEqual(unguarded["final_state"]["job"]["status"], "Completed")
                self.assertEqual(unguarded["final_state"]["token_state"]["balances_minor_units"]["provider"] -
                                 pair["prestate"]["token_state"]["balances_minor_units"]["provider"], 17_000_000)
                self.assertEqual(unguarded["wrongful_payment"], case == "bad")
                self.assertEqual(guarded["application_guard"]["origin"], "APPLICATION_IDEAL_ORACLE_UPPER_BOUND")
                self.assertEqual(guarded["application_guard"]["oracle_status"], pair["oracle_status"])
                self.assertEqual(guarded["application_guard"]["verification_calls"], 1)
                self.assertTrue(guarded["application_guard"]["digest_bound"])
                self.assertTrue(guarded["application_guard"]["task_bound"])
                self.assertFalse(guarded["wrongful_payment"])
                if case == "good":
                    self.assertTrue(guarded["application_guard"]["allow_complete"])
                    self.assertEqual(guarded_first["raw_transaction"]["input"], expected_complete)
                    self.assertEqual(guarded["final_state"]["job"]["status"], "Completed")
                    self.assertEqual(guarded["final_state"]["token_state"], unguarded["final_state"]["token_state"])
                else:
                    self.assertFalse(guarded["application_guard"]["allow_complete"])
                    self.assertEqual(guarded_first["raw_transaction"]["input"][:10], reject_selector)
                    self.assertEqual(guarded["final_state"]["job"]["status"], "Rejected")
                    self.assertIn("Refunded", {log["name"] for log in guarded_first["logs"]})
                    self.assertEqual(guarded["final_state"]["token_state"]["balances_minor_units"]["provider"],
                                     pair["prestate"]["token_state"]["balances_minor_units"]["provider"])
                    self.assertEqual(guarded["final_state"]["token_state"]["balances_minor_units"]["client"] -
                                     pair["prestate"]["token_state"]["balances_minor_units"]["client"], 20_000_000)

    def test_application_guard_rejects_wrong_digest_and_wrong_task(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "src"))
        from agent_economic_trust.core import Artifact, FIXTURES
        from run_erc8183_replay import application_evidence_guard

        fixture, artifact = FIXTURES["good"]
        decision = {"verdict": "ACCEPT", "artifact_digest": artifact.digest()}
        self.assertTrue(application_evidence_guard(decision=decision, submitted_digest=artifact.digest(),
                                                   fixture=fixture, artifact=artifact)["allow_complete"])
        self.assertFalse(application_evidence_guard(decision=decision, submitted_digest="0" * 64,
                                                    fixture=fixture, artifact=artifact)["allow_complete"])
        foreign = Artifact(task_id="other-task", submitted_amount_cents=artifact.submitted_amount_cents)
        self.assertFalse(application_evidence_guard(decision=decision, submitted_digest=artifact.digest(),
                                                    fixture=fixture, artifact=foreign)["allow_complete"])

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="erc8183-replay-existing-") as directory:
            result = subprocess.run([sys.executable, str(SCRIPT), "--output", directory],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite replay receipts", result.stderr)


if __name__ == "__main__":
    unittest.main()
