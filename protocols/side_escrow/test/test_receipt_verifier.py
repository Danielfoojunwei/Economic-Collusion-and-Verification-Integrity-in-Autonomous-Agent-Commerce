"""Independent negative checks for the saved local side escrow receipts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from protocols.side_escrow.verify_native_receipts import verify


EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "local-native-001" / "evidence.json"


class ReceiptVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def _check(self, data: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return verify(path)

    def test_saved_receipts_pass(self) -> None:
        self.assertEqual(self._check(self.original)["native_transactions"], 31)

    def test_wrong_bonus_recipient_rejected(self) -> None:
        data = copy.deepcopy(self.original)
        data["scenarios"]["completed"]["bonus_recipient"] = "provider"
        with self.assertRaisesRegex(ValueError, "scenario amount, outcome, or recipient"):
            self._check(data)

    def test_forged_successful_replay_rejected(self) -> None:
        data = copy.deepcopy(self.original)
        replay = next(tx for tx in data["transactions"] if tx["step"] == "good.replay_settle")
        replay["status"] = 1
        replay["raw_receipt"]["status"] = "0x1"
        with self.assertRaisesRegex(ValueError, "premature or replay settlement succeeded"):
            self._check(data)

    def test_other_job_terminal_event_rejected(self) -> None:
        data = copy.deepcopy(self.original)
        terminal = next(tx for tx in data["transactions"] if tx["step"] == "good.complete")
        event = next(log for log in terminal["raw_receipt"]["logs"]
                     if log["address"].lower() == data["contracts"]["ERC1967Proxy"]["address"].lower()
                     and log["topics"] and log["topics"][0].lower()
                     == "0x0fd54bd364fa9e67f17b091aefe930932c09fe7651cf5ad02c71a418f3341444")
        event["topics"][1] = "0x" + "00" * 31 + "ff"
        # Keep summary synchronized to test the actual job linkage, not summary drift.
        summary = next(log for log in terminal["logs"] if log["log_index"] == int(event["logIndex"], 16))
        summary["topics"][1] = event["topics"][1]
        with self.assertRaisesRegex(ValueError, "official terminal event belongs to wrong job"):
            self._check(data)


if __name__ == "__main__":
    unittest.main()
