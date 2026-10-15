"""Tests for immutable W05 source linking and fail-closed catalog pinning."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_economic_trust.w05_supplement import (
    SUPPLEMENT_NAME, SupplementError, build_supplement, verify_supplement,
)


SOURCE = Path(__file__).resolve().parents[1] / "artifacts/gates/W05/real-run-001/reconcile-002"


class W05SupplementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for name in ("run_manifest.json", "inspect.eval"):
            shutil.copyfile(SOURCE / name, self.directory / name)
        saved = json.loads((SOURCE / SUPPLEMENT_NAME).read_text(encoding="utf-8"))
        self.catalog = {"data": [saved["catalog"]["model_record"]]}
        (self.directory / SUPPLEMENT_NAME).write_text(json.dumps(saved), encoding="utf-8")

    def test_saved_supplement_verifies_and_recovers_original_cost(self) -> None:
        result = verify_supplement(self.directory)
        self.assertTrue(result["verified"])
        self.assertEqual(result["estimated_usd"], "0.046460")
        record = json.loads((self.directory / SUPPLEMENT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(record["native_usage"]["provider_calls"], 5)
        self.assertEqual(record["native_usage"]["sample_usage"]["total_tokens"], 3904)

    def test_changed_catalog_price_rejected_by_original_model_digest(self) -> None:
        self.catalog["data"][0]["pricing"]["prompt"] = "0.123"
        with self.assertRaisesRegex(SupplementError, "differs from run-time pinned"):
            build_supplement(self.directory, catalog=self.catalog)

    def test_changed_source_or_supplement_rejected(self) -> None:
        manifest_path = self.directory / "run_manifest.json"
        manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        with self.assertRaisesRegex(SupplementError, "supplement differs"):
            verify_supplement(self.directory)
        shutil.copyfile(SOURCE / "run_manifest.json", manifest_path)
        record_path = self.directory / SUPPLEMENT_NAME
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["native_usage"]["sample_usage"]["output_tokens"] += 1
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(SupplementError, "record hash"):
            verify_supplement(self.directory)

    def test_changed_native_log_rejected(self) -> None:
        native_path = self.directory / "inspect.eval"
        with native_path.open("ab") as file:
            file.write(b"modified")
        with self.assertRaisesRegex(SupplementError, "native Inspect log differs"):
            verify_supplement(self.directory)


if __name__ == "__main__":
    unittest.main()
