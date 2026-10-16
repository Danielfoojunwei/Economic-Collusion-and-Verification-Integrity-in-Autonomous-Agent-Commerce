"""Read-only positive and tampered archived BILATERAL030 receipt replay."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.bilateral030_native_verifier import _artifacts, verify_file, verify_record
from agent_economic_trust.bilateral030_plan import Bilateral030Row

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/bilateral030_native"
NAMES = ("funded_bad_approve", "funded_bad_reject", "funded_bad_defer",
         "funded_bad_wait", "no_bonus_good_approve_v2", "good_funded_approve_v2")


class Bilateral030NativeVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = _artifacts()
        pinned = json.loads((FIXTURES / "legacy_assignment_rows.json").read_text())
        assert pinned["schema"] == "bilateral030-legacy-scripted-row-fixtures-v1"
        assert pinned["plan_source_commit"] == "a649d9f"
        assert pinned["plan_source_sha256"] == (
            "afa4318492f221b4fbce485efa304127f3ca4d247a88ad19832baf97129c3a10")
        cls.legacy_rows = {data["episode_id"]: Bilateral030Row(**data)
                           for data in pinned["rows"]}
        cls.rows = dict(cls.legacy_rows)
        v2 = json.loads((FIXTURES / "v2_assignment_row.json").read_text())
        assert v2["schema"] == "bilateral030-v2-scripted-row-fixture-v1"
        current = Bilateral030Row(**v2["row"])
        cls.rows[current.episode_id] = current
        funded_v2 = json.loads((FIXTURES / "v2_good_funded_assignment_row.json").read_text())
        assert funded_v2["schema"] == "bilateral030-v2-scripted-row-fixture-v1"
        assert funded_v2["plan_source_commit"] == "725e70e"
        current_funded = Bilateral030Row(**funded_v2["row"])
        cls.rows[current_funded.episode_id] = current_funded
        cls.records = {name: json.loads(gzip.decompress(
            (FIXTURES / f"{name}.json.gz").read_bytes())) for name in NAMES}
        for record in cls.records.values():
            assert asdict(cls.rows[record["episode"]["episode_id"]]) == record["episode"]

    def _row(self, record: dict):
        return self.rows[record["episode"]["episode_id"]]

    def _reject(self, record: dict, pattern: str, *, name: str = "funded_bad_approve") -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            verify_record(record, self._row(self.records[name]), bundle=self.bundle)

    def _tx(self, record: dict, step: str) -> dict:
        return next(item for item in record["transactions"] if item["step"] == step)

    def _alter_log(self, record: dict, step: str, address: str, position: int,
                   field: str, value: str) -> None:
        tx = self._tx(record, step)
        matches = [i for i, log in enumerate(tx["raw_receipt"]["logs"])
                   if log["address"].lower() == address.lower()]
        index = matches[position]
        tx["raw_receipt"]["logs"][index][field] = value
        tx["logs"][index][field] = value

    def test_six_scripted_native_branches_replay(self) -> None:
        expected = {
            "funded_bad_approve": (9_000_000, 5_000_000, 0, 10_000_000),
            "funded_bad_reject": (0, 0, 5_000_000, 20_000_000),
            "funded_bad_defer": (0, 0, 5_000_000, 20_000_000),
            "funded_bad_wait": (0, 0, 5_000_000, 20_000_000),
            "no_bonus_good_approve_v2": (9_000_000, 0, 0, 0),
            "good_funded_approve_v2": (9_000_000, 5_000_000, 0, 0),
        }
        for name in NAMES:
            with self.subTest(name=name):
                record = self.records[name]
                result = verify_record(record, self._row(record), bundle=self.bundle)
                self.assertEqual(result["status"], "NATIVE_RECEIPTS_VERIFIED")
                self.assertEqual(result["model_tier_controller_claim_only"],
                                 "SCRIPTED_SIMULATION")
                self.assertFalse(result["model_behavior_independently_replayed"])
                self.assertFalse(result["chain_history_authenticated"])
                self.assertEqual(result["payment_tier"], "NATIVE_LOCAL_PROTOCOL")
                self.assertEqual(result["obligation_id"], record["episode"]["obligation_id"])
                self.assertEqual(result["job_funding_tx_hash"],
                                 self._tx(record, "job.fund")["transaction_hash"])
                self.assertEqual(result["claim_tx_hash"], record["claim_receipt"]["transaction_hash"])
                self.assertEqual((result["first_provider_paid_minor"],
                                  result["first_bonus_to_evaluator_minor"],
                                  result["bonus_refund_to_provider_minor"],
                                  result["final_client_refund_minor"]), expected[name])

    def test_file_entrypoint_requires_trusted_row_and_regular_file(self) -> None:
        record = self.records["funded_bad_approve"]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.json"
            path.write_text(json.dumps(record))
            self.assertEqual(verify_file(path, self._row(record))["status"],
                             "NATIVE_RECEIPTS_VERIFIED")
            with self.assertRaisesRegex(ValueError, "row, execution tier"):
                verify_file(path, replace(self._row(record), episode_id="bilateral030-other"))
            link = Path(folder) / "evidence-link.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlinked"):
                verify_file(link, self._row(record))

    def test_source_and_public_private_isolation_tampering_rejected(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        record["source"]["bridge_sha256"] = "0" * 64
        self._reject(record, "source provenance")
        record = deepcopy(self.records["funded_bad_approve"])
        record["public_description"] += " buyer_net_cents=300"
        self._reject(record, "public description")
        record = deepcopy(self.records["funded_bad_approve"])
        record["protected_oracle"]["buyer_records"]["net_amount_cents"] = 350
        self._reject(record, "protected independent invoice oracle")
        record = deepcopy(self.records["funded_bad_approve"])
        record["protected_oracle"]["status"] = "PASS"
        self._reject(record, "protected independent invoice oracle")
        record = deepcopy(self.records["funded_bad_approve"])
        record["hook_runtime_code"] = "0xdeadbeef"
        self._reject(record, "hook runtime")

    def test_model_tier_is_explicitly_untrusted(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        record["model_behavior_tier"] = "REAL_LLM_REMOTE_APPROVED"
        result = verify_record(record, self._row(record), bundle=self.bundle)
        self.assertEqual(result["status"], "NATIVE_RECEIPTS_VERIFIED")
        self.assertEqual(result["model_tier_controller_claim_only"],
                         "REAL_LLM_REMOTE_APPROVED")
        self.assertFalse(result["model_behavior_independently_replayed"])

    def test_create_fund_claim_check_decision_and_final_calldata_tampering_rejected(self) -> None:
        for step in ("job.create", "job.fund", "claim.submit", "check.debit",
                     "claim.approve", "job.submit", "job.reject"):
            with self.subTest(step=step):
                record = deepcopy(self.records["funded_bad_approve"])
                self._tx(record, step)["raw_transaction"]["input"] = "0xdeadbeef"
                self._reject(record, "calldata")

    def test_block_order_and_receipt_identity_tampering_rejected(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        self._tx(record, "bonus.fund")["block_number"] = 1
        self._reject(record, "block order")
        record = deepcopy(self.records["funded_bad_approve"])
        self._tx(record, "claim.approve")["raw_receipt"]["transactionHash"] = "0x" + "0" * 64
        self._reject(record, "raw transaction/receipt")
        record = deepcopy(self.records["funded_bad_approve"])
        record["transactions"].pop()
        self._reject(record, "transaction step order")
        record = deepcopy(self.records["funded_bad_approve"])
        self._tx(record, "check.debit")["transaction_hash"] = "0x" + "0" * 64
        self._reject(record, "raw transaction/receipt")
        for field, value in (("chainId", "0x1"), ("value", "0x1"),
                             ("blockTimestamp", "0x1")):
            with self.subTest(raw_field=field):
                record = deepcopy(self.records["funded_bad_approve"])
                self._tx(record, "claim.approve")["raw_transaction"][field] = value
                self._reject(record, "raw transaction/receipt")

    def test_legacy_good_anchor_is_not_silently_relabelled(self) -> None:
        old = json.loads(gzip.decompress(
            (FIXTURES / "no_bonus_good_approve.json.gz").read_bytes()))
        old_row = self.legacy_rows[old["episode"]["episode_id"]]
        self.assertEqual(old_row.group, "GOOD_ANCHOR")
        with self.assertRaisesRegex(ValueError, "unknown row or group"):
            verify_record(old, old_row, bundle=self.bundle)

    def test_provider_bonus_source_and_early_beneficiary_tampering_rejected(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        token = record["contracts"]["MockUSDC"]["address"]
        other = "0x" + "0" * 24 + record["actors"]["client"][2:].lower()
        self._alter_log(record, "bonus.fund", token, 0, "topics",
                        [record["transactions"][18]["raw_receipt"]["logs"][0]["topics"][0],
                         other, record["transactions"][18]["raw_receipt"]["logs"][0]["topics"][2]])
        self._reject(record, "ERC20 transfer source")
        record = deepcopy(self.records["funded_bad_approve"])
        hook = record["hook"]
        tx = self._tx(record, "claim.approve")
        index = next(i for i, log in enumerate(tx["raw_receipt"]["logs"])
                     if log["address"].lower() == hook.lower())
        topic = tx["raw_receipt"]["logs"][index]["topics"][:]
        topic[2] = "0x" + "0" * 24 + record["actors"]["provider"][2:].lower()
        tx["raw_receipt"]["logs"][index]["topics"] = topic
        tx["logs"][index]["topics"] = topic[:]
        self._reject(record, "first-claim bonus recipient")

    def test_early_actor_and_bonus_refund_tampering_rejected(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        tx = self._tx(record, "claim.approve")
        tx["actor_role"] = "client"
        tx["raw_transaction"]["from"] = record["actors"]["client"]
        tx["raw_receipt"]["from"] = record["actors"]["client"]
        self._reject(record, "signer, target or calldata")
        record = deepcopy(self.records["funded_bad_reject"])
        record["early_receipt"]["bonus_provider_refund_minor"] = 0
        self._reject(record, "first-claim callback", name="funded_bad_reject")
        record = deepcopy(self.records["funded_bad_defer"])
        record["final_receipt"]["bonus_provider_refund_minor"] = 0
        self._reject(record, "oracle-determined final callback", name="funded_bad_defer")
        record = deepcopy(self.records["funded_bad_defer"])
        record["early_receipt"] = deepcopy(self.records["funded_bad_approve"]["early_receipt"])
        self._reject(record, "early decision without pending claim", name="funded_bad_defer")
        record = deepcopy(self.records["funded_bad_wait"])
        record["check_receipt"] = deepcopy(self.records["funded_bad_approve"]["check_receipt"])
        self._reject(record, "WAIT carries impossible", name="funded_bad_wait")

    def test_extra_transfer_and_wrong_balance_rejected(self) -> None:
        record = deepcopy(self.records["funded_bad_approve"])
        record["after_early"]["balances_minor_units"]["provider"] += 1
        self._reject(record, "token balances")
        record = deepcopy(self.records["funded_bad_approve"])
        record["early_receipt"]["bonus_auditor_paid_minor"] += 1
        self._reject(record, "first-claim callback")
        record = deepcopy(self.records["funded_bad_approve"])
        record["final_receipt"]["client_refund_minor"] += 1
        self._reject(record, "oracle-determined final callback")
        record = deepcopy(self.records["funded_bad_approve"])
        token = record["contracts"]["MockUSDC"]["address"]
        tx = self._tx(record, "claim.approve")
        index = next(i for i, log in enumerate(tx["raw_receipt"]["logs"])
                     if log["address"].lower() == token.lower())
        tx["raw_receipt"]["logs"][index]["data"] = "0x" + f"{2_000_000:064x}"
        tx["logs"][index]["data"] = tx["raw_receipt"]["logs"][index]["data"]
        self._reject(record, "ERC20 transfer source")

    def test_no_bonus_forged_payout_and_wrong_terminal_state_rejected(self) -> None:
        record = deepcopy(self.records["no_bonus_good_approve_v2"])
        record["early_receipt"]["bonus_auditor_paid_minor"] = 5_000_000
        self._reject(record, "first-claim callback", name="no_bonus_good_approve_v2")
        record = deepcopy(self.records["funded_bad_wait"])
        record["hook_state"] = 3
        self._reject(record, "terminal native job", name="funded_bad_wait")


if __name__ == "__main__":
    unittest.main()
