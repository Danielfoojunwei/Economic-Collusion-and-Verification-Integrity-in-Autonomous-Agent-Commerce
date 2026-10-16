"""Scripted local W11 market payment controls; no model or public assets."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from agent_economic_trust.w11_market_native import (
    LiveNativeMarket, MarketNativeError, verify_fee_receipt, verify_market_evidence,
)


class LiveNativeMarketTests(unittest.TestCase):
    def _open(self, market: LiveNativeMarket, index: int, provider: str, auditor: str):
        return market.open_round(
            episode_id=f"{market.market_id}-episode-{index}",
            obligation_id=f"{market.market_id}-obligation-{index}",
            artifact_digest=f"{index + 1:064x}",
            public_task_digest=f"{index + 101:064x}",
            provider_id=provider, auditor_id=auditor,
        )

    def test_persistent_market_wallets_fees_payout_refund_expiry_and_replay(self):
        with tempfile.TemporaryDirectory(prefix="w11-market-", dir="/workspace") as root:
            path = Path(root) / "market"
            with LiveNativeMarket("market-alpha", path, r=1,
                                  assignment_manifest_sha256="a" * 64) as market:
                one = self._open(market, 0, "provider-A", "auditor-A")
                self.assertEqual(one["job_id"], 1)
                self.assertEqual(one["fee_payer_role"], "provider")
                self.assertIsNotNone(one["provider_initial_endowment"])
                self.assertEqual(
                    one["fee_balances_after"]["balances_minor_units"][one["addresses"]["provider"].lower()],
                    one["fee_balances_before"]["balances_minor_units"][one["addresses"]["provider"].lower()]
                    - 2_000_000,
                )
                self.assertEqual(market.verify_open_round(one["obligation_id"])["job_id"], 1)
                tx_count = len(market.helper.transactions)
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    self._open(market, 0, "provider-A", "auditor-A")
                self.assertEqual(len(market.helper.transactions), tx_count)
                with self.assertRaisesRegex(ValueError, "frozen"):
                    market.settle_round(one["obligation_id"], "ACCEPT", "f" * 64)
                self.assertEqual(len(market.helper.transactions), tx_count)
                settled = market.settle_round(one["obligation_id"], "ACCEPT",
                                              one["artifact_digest"])
                self.assertTrue(settled["provider_paid"])
                self.assertEqual(settled["job_status"], "Completed")
                self.assertEqual(settled["provider_payout_minor_units"], 20_000_000)
                with self.assertRaisesRegex(ValueError, "not the live open"):
                    market.verify_open_round(one["obligation_id"])

                two = self._open(market, 1, "provider-A", "auditor-B")
                self.assertEqual(two["job_id"], 2)
                self.assertIsNone(two["provider_initial_endowment"])
                self.assertEqual(
                    two["fee_balances_before"]["balances_minor_units"][two["addresses"]["provider"].lower()],
                    settled["balances_after"]["balances_minor_units"][two["addresses"]["provider"].lower()],
                )
                self.assertEqual(two["addresses"]["provider"], one["addresses"]["provider"])
                self.assertNotEqual(two["addresses"]["auditor"], one["addresses"]["auditor"])
                rejected = market.settle_round(two["obligation_id"], "REJECT",
                                               two["artifact_digest"])
                self.assertFalse(rejected["provider_paid"])
                self.assertEqual(rejected["job_status"], "Rejected")
                self.assertEqual(rejected["provider_payout_minor_units"], 0)

                three = self._open(market, 2, "auditor-A", "provider-A")
                self.assertEqual(three["job_id"], 3)
                self.assertEqual(three["addresses"]["provider"], one["addresses"]["auditor"])
                self.assertEqual(three["addresses"]["auditor"], one["addresses"]["provider"])
                expired = market.expire_round(three["obligation_id"])
                self.assertEqual(expired["job_status"], "Expired")
                self.assertFalse(expired["provider_paid"])
                self.assertEqual({r["job_id"] for r in market.rounds.values()}, {1, 2, 3})
                self.assertEqual(len({r["fee_receipt"]["transactionHash"]
                                      for r in market.rounds.values()}), 3)
                self.assertEqual(market.helper.uint(market.helper.core, "jobCounter()"), 3)
                self.assertIsNone(market.active_obligation)
            evidence = json.loads((path / "evidence.json").read_text())
            verified = verify_market_evidence(path / "evidence.json")
            self.assertEqual(verified["statuses"],
                             {"COMPLETED": 1, "REJECTED": 1, "EXPIRED": 1})
            self.assertEqual(verified["payment_transactions"], 6)
            self.assertEqual(evidence["schema"], "w11-native-local-market-v1")
            self.assertEqual(evidence["asset_real_value"], 0)
            self.assertEqual([r["status"] for r in evidence["rounds"]],
                             ["COMPLETED", "REJECTED", "EXPIRED"])
            self.assertEqual(evidence["fee_terms"]["conditional_evaluator_fee_bps"], 0)
            self.assertEqual(evidence["fee_terms"]["platform_fee_bps"], 0)
            tampered = deepcopy(evidence)
            tampered["rounds"][1]["obligation_id"] = tampered["rounds"][0]["obligation_id"]
            forged = Path(root) / "duplicate-obligation.json"
            forged.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "duplicated"):
                verify_market_evidence(forged)
            tampered = deepcopy(evidence)
            tampered["rounds"][0]["settlement"]["provider_payout_minor_units"] = 0
            forged.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "payout"):
                verify_market_evidence(forged)
            for action in ("fund", "submit"):
                tampered = deepcopy(evidence)
                item = next(tx for tx in tampered["transactions"]
                            if tx["step"] == f"market-alpha-obligation-0.{action}")
                tampered["raw_transactions"][item["transaction_hash"].lower()]["input"] = "0x"
                forged.write_text(json.dumps(tampered))
                with self.subTest(action=action), self.assertRaisesRegex(ValueError, action):
                    verify_market_evidence(forged)

    def test_client_fee_and_wrong_payer_payee_amount_detection(self):
        with tempfile.TemporaryDirectory(prefix="w11-market-", dir="/workspace") as root:
            first_path, second_path = Path(root) / "first", Path(root) / "second"
            with LiveNativeMarket("market-beta", first_path, r=0) as market:
                record = self._open(market, 0, "provider-A", "auditor-A")
                self.assertEqual(record["fee_payer_role"], "client")
                fields = {
                    "transaction": record["fee_transaction"],
                    "receipt": record["fee_receipt"],
                    "token": market.helper.token, "chain_id": 31337,
                    "payer": record["addresses"]["client"],
                    "payee": record["addresses"]["auditor"],
                    "amount_minor": 2_000_000,
                    "balances_before": record["fee_balances_before"],
                    "balances_after": record["fee_balances_after"],
                }
                self.assertEqual(verify_fee_receipt(**fields), record["fee_receipt_sha256"])
                for key, wrong in (
                    ("payer", record["addresses"]["provider"]),
                    ("payee", record["addresses"]["provider"]),
                    ("amount_minor", 1_000_000),
                ):
                    bad = fields | {key: wrong}
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        verify_fee_receipt(**bad)
                tampered = deepcopy(fields)
                tampered["receipt"]["logs"][0]["data"] = "0x1"
                with self.assertRaises(ValueError):
                    verify_fee_receipt(**tampered)
                with self.assertRaisesRegex(ValueError, "overlapping"):
                    self._open(market, 1, "provider-A", "auditor-A")
                market.settle_round(record["obligation_id"], "ACCEPT",
                                    record["artifact_digest"])
                first_addresses = set(market.identity_addresses.values())
                client_address = market.helper.roles["client"]
            with LiveNativeMarket("market-gamma", second_path, r=0) as other:
                second = self._open(other, 0, "provider-A", "auditor-A")
                self.assertTrue(first_addresses.isdisjoint(other.identity_addresses.values()))
                self.assertNotEqual(client_address, other.helper.roles["client"])
                other.settle_round(second["obligation_id"], "REJECT",
                                   second["artifact_digest"])
            self.assertEqual(verify_market_evidence(first_path / "evidence.json")["rounds"], 1)
            self.assertEqual(verify_market_evidence(second_path / "evidence.json")["rounds"], 1)

    def test_pause_resume_preserves_chain_history_and_rejects_tampered_state(self):
        with tempfile.TemporaryDirectory(prefix="w11-resume-", dir="/workspace") as root:
            path = Path(root) / "market"
            config = {"r": 1, "assignment_manifest_sha256": "b" * 64}
            with LiveNativeMarket("market-resume", path, **config) as first:
                one = self._open(first, 0, "provider-A", "auditor-A")
                first_tip = first.helper.rpc.call("eth_getBlockByNumber", ["latest", False])["hash"]
                fee_hash = one["fee_receipt"]["transactionHash"]
            self.assertTrue((path / "anvil-state.hex").is_file())
            with LiveNativeMarket("market-resume", path, resume=True, **config) as resumed:
                self.assertEqual(resumed.helper.rpc.call("eth_getBlockByNumber", ["latest", False])["hash"],
                                 first_tip)
                self.assertEqual(resumed.verify_open_round(one["obligation_id"])["job_id"], 1)
                self.assertEqual(resumed.helper.rpc.call("eth_getTransactionReceipt", [fee_hash]),
                                 one["fee_receipt"])
                resumed.settle_round(one["obligation_id"], "ACCEPT", one["artifact_digest"])
                two = self._open(resumed, 1, "provider-A", "auditor-B")
                self.assertEqual(two["job_id"], 2)
                resumed.settle_round(two["obligation_id"], "REJECT", two["artifact_digest"])
            verified = verify_market_evidence(path / "evidence.json")
            self.assertEqual(verified["statuses"], {"COMPLETED": 1, "REJECTED": 1})
            self.assertEqual(verified["payment_transactions"], 4)
            evidence_before = sha256((path / "evidence.json").read_bytes()).hexdigest()
            original_evidence = (path / "evidence.json").read_bytes()
            altered = json.loads(original_evidence)
            altered["chain_checkpoint"]["account_nonces"][0] += 1
            (path / "evidence.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(MarketNativeError, "nonces"):
                with LiveNativeMarket("market-resume", path, resume=True, **config):
                    self.fail("tampered account nonce was accepted")
            (path / "evidence.json").write_bytes(original_evidence)
            state = path / "anvil-state.hex"
            payload = bytearray(state.read_bytes())
            payload[-3] = ord("0") if payload[-3] != ord("0") else ord("1")
            state.write_bytes(payload)
            with self.assertRaisesRegex(MarketNativeError, "state digest"):
                with LiveNativeMarket("market-resume", path, resume=True, **config):
                    self.fail("tampered chain state was accepted")
            self.assertEqual(sha256((path / "evidence.json").read_bytes()).hexdigest(),
                             evidence_before)


if __name__ == "__main__":
    unittest.main()
