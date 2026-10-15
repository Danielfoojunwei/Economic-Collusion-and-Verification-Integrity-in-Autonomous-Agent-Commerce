"""Prospective source closure and historical assignment-006 preimage checks."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from scripts.forensic_w11_stopped import (
    EXPECTED_FREEZER_SOURCE, EXPECTED_PRIOR_SOURCE,
    verify_historical_source_seal,
)
from scripts.freeze_w11_market import ROOT, SOURCE_FILES


class W11SourceSealTests(unittest.TestCase):
    def test_frozen_sources_cover_package_init_and_event_schemas(self):
        self.assertTrue({
            "src/agent_economic_trust/__init__.py",
            "schemas/event.schema.json",
            "schemas/run_manifest.schema.json",
        }.issubset(SOURCE_FILES))

    def test_frozen_sources_cover_local_import_closure(self):
        frozen = set(SOURCE_FILES)
        missing: set[str] = set()
        for name in frozen:
            if not name.endswith(".py"):
                continue
            path = ROOT / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level and name.startswith("src/agent_economic_trust/"):
                        candidate = f"src/agent_economic_trust/{module}.py"
                    elif module.startswith("agent_economic_trust."):
                        candidate = "src/agent_economic_trust/" + module.split(".")[1] + ".py"
                    elif module.startswith("tests."):
                        candidate = "tests/" + module.split(".")[1] + ".py"
                    else:
                        continue
                    if (ROOT / candidate).is_file() and candidate not in frozen:
                        missing.add(candidate)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("agent_economic_trust."):
                            candidate = ("src/agent_economic_trust/"
                                         + alias.name.split(".")[1] + ".py")
                            if (ROOT / candidate).is_file() and candidate not in frozen:
                                missing.add(candidate)
        self.assertEqual(missing, set())

    def test_assignment_006_requires_exact_archived_freezer_and_runner(self):
        frozen = json.loads((ROOT / "artifacts/gates/W11_DESIGN/assignment-006/"
                             "assignment_manifest.json").read_bytes())
        original = ROOT / "artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006"
        with tempfile.TemporaryDirectory(prefix="w11-source-test-", dir="/workspace") as dirname:
            copy_root = Path(dirname)
            for name in (EXPECTED_PRIOR_SOURCE, EXPECTED_FREEZER_SOURCE):
                target = copy_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((original / name).read_bytes())
            drift = verify_historical_source_seal(frozen["source_sha256"], copy_root)
            self.assertIn(EXPECTED_FREEZER_SOURCE, drift)
            self.assertIn(EXPECTED_PRIOR_SOURCE, drift)
            archived_freezer = copy_root / EXPECTED_FREEZER_SOURCE
            archived_freezer.write_bytes(archived_freezer.read_bytes() + b"\n# tampered\n")
            with self.assertRaisesRegex(ValueError, "historical source preimage"):
                verify_historical_source_seal(frozen["source_sha256"], copy_root)


if __name__ == "__main__":
    unittest.main()
