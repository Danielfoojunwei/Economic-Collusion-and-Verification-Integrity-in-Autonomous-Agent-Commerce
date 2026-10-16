"""Local-only BILATERAL030 bridge controls; these are not model results."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.bilateral030_native import (
    Bilateral030NativeBridge, Bilateral030NativeError,
)
from agent_economic_trust.bilateral030_plan import (
    FUNDED, GOOD_ANCHOR, HIGH_RISK, NO_ACCEPT_BONUS, SOL, SONNET,
    make_schedule,
)
from agent_economic_trust.bilateral030_task import funded_prefix
from scripts.run_erc8183_local import CAST, _command


ROWS = make_schedule("b3" * 32)


def _row(group: str, provider_model: str):
    return next(row for row in ROWS if row.group == group
                and row.provider_model_id == provider_model)


class Bilateral030NativeBridgeTest(unittest.TestCase):
    def _run(self, row, *, decision: str | None, check: bool,
             claim: str = "CLAIM") -> dict:
        with TemporaryDirectory(prefix="bilateral030-native-test-", dir="/tmp") as temp:
            path = Path(temp) / "native"
            with Bilateral030NativeBridge(row, path) as bridge:
                prefix = bridge.public_prefix()
                self.assertEqual(funded_prefix(row, prefix), prefix)
                self.assertEqual(bridge.public_report["submitted_cents"], 350)
                public_bytes = bridge.description + json.dumps(prefix)
                for forbidden in ("purchase_order_amount_cents", "credit_note_amount_cents",
                                  "net_amount_cents", '"truth"', '"bad"', '"good"'):
                    self.assertNotIn(forbidden, public_bytes)
                chosen = bridge.choose_claim(row, claim)
                if claim == "CLAIM":
                    self.assertEqual(chosen["status"], "CLAIM_PENDING")
                    if check:
                        checked = bridge.buy_check(row, "native-check")
                        self.assertEqual(checked["oracle_status"],
                                         "PASS" if row.truth == "good" else "FAIL")
                        with self.assertRaises(Bilateral030NativeError):
                            bridge.buy_check(row, "repeat")
                    with self.assertRaises(Bilateral030NativeError):
                        bridge.reveal_final(row)
                    if decision is None:
                        bridge.mark_deferred(row)
                        with self.assertRaises(Bilateral030NativeError):
                            bridge.buy_check(row, "late-check")
                        with self.assertRaises(Bilateral030NativeError):
                            bridge.early_decide(row, "APPROVE")
                    else:
                        early = bridge.early_decide(row, decision)
                        self.assertEqual(early["decision"], decision)
                        if row.accept_bonus == FUNDED:
                            self.assertEqual(early["bonus_transaction_hash"],
                                             early["transaction_hash"])
                            self.assertEqual(early["bonus_auditor_paid_minor"] +
                                             early["bonus_provider_refund_minor"], 5_000_000)
                        else:
                            self.assertEqual(early["bonus_status"], "ABSENT")
                else:
                    self.assertEqual(chosen["status"], "WAIT_NO_CLAIM")
                    with self.assertRaises(Bilateral030NativeError):
                        bridge.buy_check(row, "not-pending")
                bridge.reveal_final(row)
                verdict = "ACCEPT" if row.truth == "good" else "REJECT"
                with self.assertRaises(Bilateral030NativeError):
                    bridge.finalize(row, "REJECT" if verdict == "ACCEPT" else "ACCEPT")
                final = bridge.finalize(row, verdict)
                self.assertEqual(final["status"],
                                 "COMPLETED" if verdict == "ACCEPT" else "REJECTED")
            saved = json.loads((path / "native-evidence.json").read_text())
            self.assertEqual(saved["source"]["official_commit"],
                             "142e669c1fd318486a4628395b629f033654dd06")
            self.assertEqual(saved["payment_tier"], "NATIVE_LOCAL_PROTOCOL")
            self.assertEqual(saved["model_behavior_tier"], "SCRIPTED_SIMULATION")
            self.assertFalse(saved["independent_native_receipt_replay"])
            self.assertEqual(saved["protected_oracle"]["status"],
                             "PASS" if row.truth == "good" else "FAIL")
            self.assertEqual(saved["report_digest"], prefix["report_digest"])
            create = next(tx for tx in saved["transactions"] if tx["step"] == "job.create")
            expected_input = _command(
                str(CAST), "calldata", "createJob(address,address,uint48,string,address,uint256)",
                saved["actors"]["provider"], saved["actors"]["evaluator"],
                str(saved["expiry"]), saved["public_description"], saved["hook"], "0")
            self.assertEqual(create["raw_transaction"]["input"].lower(),
                             expected_input.lower())
            self.assertEqual(create["raw_transaction"]["from"].lower(),
                             saved["actors"]["client"].lower())
            return saved

    def test_funded_false_approval_sol_provider_sonnet_auditor(self):
        saved = self._run(_row(HIGH_RISK, SOL), decision="APPROVE", check=True)
        self.assertEqual(saved["early_receipt"]["provider_paid_minor"], 9_000_000)
        self.assertEqual(saved["early_receipt"]["evaluator_native_fee_minor"], 1_000_000)
        self.assertEqual(saved["early_receipt"]["bonus_auditor_paid_minor"], 5_000_000)
        self.assertEqual(saved["final_receipt"]["client_refund_minor"], 10_000_000)

    def test_funded_reject_sonnet_provider_sol_auditor(self):
        saved = self._run(_row(HIGH_RISK, SONNET), decision="REJECT", check=False)
        self.assertEqual(saved["early_receipt"]["bonus_provider_refund_minor"], 5_000_000)
        self.assertEqual(saved["early_receipt"]["provider_paid_minor"], 0)
        self.assertEqual(saved["final_receipt"]["client_refund_minor"], 20_000_000)

    def test_no_bonus_good_anchor_and_oracle_acceptance(self):
        saved = self._run(_row(GOOD_ANCHOR, SOL), decision="APPROVE", check=True)
        self.assertIsNone(saved["early_receipt"]["bonus_transaction_hash"])
        self.assertEqual(saved["final_receipt"]["provider_paid_minor"], 9_000_000)

    def test_no_bonus_bad_defer_preserves_full_refund(self):
        saved = self._run(_row(NO_ACCEPT_BONUS, SONNET), decision=None, check=False)
        self.assertTrue(saved["deferred"])
        self.assertEqual(saved["final_receipt"]["client_refund_minor"], 20_000_000)

    def test_funded_wait_refunds_provider_bonus_on_final_submit(self):
        saved = self._run(_row(HIGH_RISK, SOL), decision=None, check=False, claim="WAIT")
        self.assertEqual(saved["final_receipt"]["bonus_provider_refund_minor"], 5_000_000)
        self.assertEqual(saved["final_receipt"]["client_refund_minor"], 20_000_000)

    def test_funded_bad_defer_supersedes_claim_and_refunds_both_escrows(self):
        saved = self._run(_row(HIGH_RISK, SONNET), decision=None, check=False)
        self.assertTrue(saved["deferred"])
        self.assertEqual(saved["final_receipt"]["bonus_provider_refund_minor"], 5_000_000)
        self.assertEqual(saved["final_receipt"]["client_refund_minor"], 20_000_000)
        self.assertEqual(saved["final_job"]["settled_amount_minor_units"], 0)

    def test_pre_view_bonus_proof_rejects_tampered_raw_transfer(self):
        row = _row(HIGH_RISK, SONNET)
        with TemporaryDirectory(prefix="bilateral030-proof-test-", dir="/tmp") as temp:
            with Bilateral030NativeBridge(row, Path(temp) / "native") as bridge:
                funded = bridge.public_prefix()
                self.assertTrue(funded["bonus_funded"])
                bonus = next(tx for tx in bridge.helper.transactions
                             if tx["step"] == "bonus.fund")
                saved = deepcopy(bonus["raw_receipt"])
                try:
                    token_log = next(log for log in bonus["raw_receipt"]["logs"]
                                     if log["address"].lower() == bridge.helper.token.lower())
                    token_log["data"] = "0x" + "00" * 32
                    with self.assertRaises(Bilateral030NativeError):
                        bridge.public_prefix()
                finally:
                    bonus["raw_receipt"] = saved


if __name__ == "__main__":
    unittest.main()
