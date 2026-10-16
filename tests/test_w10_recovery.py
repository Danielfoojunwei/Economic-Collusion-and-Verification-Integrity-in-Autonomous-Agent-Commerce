"""Offline recovery checks for the settled, stopped W10 good pilot."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_economic_trust.w10_recovery import (
    SOURCE_DIR, RecoveryError, recover_good, verify_recovery,
)

W05_PIN = Path(__file__).resolve().parents[1] / (
    "artifacts/gates/W05/real-run-001/reconcile-002/usage_pricing_supplement.json"
)


class W10RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "original"
        self.source.mkdir()
        for name in ("inspect.eval", "STOPPED.json"):
            shutil.copyfile(SOURCE_DIR / name, self.source / name)
        self.destination = self.base / "derived"
        saved = json.loads(W05_PIN.read_text(encoding="utf-8"))
        self.catalog = {"data": [saved["catalog"]["model_record"]]}

    def test_derived_artifact_verifies_and_records_unknown_fields(self) -> None:
        result = recover_good(self.destination, source_dir=self.source, catalog=self.catalog)
        self.assertTrue(result["verified"])
        self.assertEqual(result["settled_estimate_usd"], "0.06689")
        manifest = json.loads((self.destination / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertIsNone(manifest["account_usage_delta_usd"])
        self.assertIsNone(manifest["max_input_bytes_seen"])
        with self.assertRaises(FileExistsError):
            recover_good(self.destination, source_dir=self.source, catalog=self.catalog)

    def test_changed_original_native_or_stopped_record_rejected(self) -> None:
        native = self.source / "inspect.eval"
        with native.open("ab") as file:
            file.write(b"tamper")
        with self.assertRaisesRegex(RecoveryError, "source.*hash|native log or STOPPED"):
            recover_good(self.destination, source_dir=self.source, catalog=self.catalog)
        self.assertFalse(self.destination.exists())

    def test_changed_stopped_record_rejected(self) -> None:
        stopped = self.source / "STOPPED.json"
        stopped.write_bytes(stopped.read_bytes() + b" ")
        with self.assertRaisesRegex(RecoveryError, "native log or STOPPED record hash"):
            recover_good(self.destination, source_dir=self.source, catalog=self.catalog)
        self.assertFalse(self.destination.exists())

    def test_changed_catalog_price_rejected(self) -> None:
        self.catalog["data"][0]["pricing"]["prompt"] = "0.123"
        with self.assertRaisesRegex(RecoveryError, "public model catalog differs"):
            recover_good(self.destination, source_dir=self.source, catalog=self.catalog)
        self.assertFalse(self.destination.exists())

    def test_saved_derived_artifact_verifies_offline(self) -> None:
        self.assertTrue(verify_recovery()["verified"])


if __name__ == "__main__":
    unittest.main()
