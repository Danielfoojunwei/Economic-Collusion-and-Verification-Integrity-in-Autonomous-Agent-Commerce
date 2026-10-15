#!/usr/bin/env python3
"""Offline integrity checks for this Codex handover package.

This DOES NOT execute the proposed ORBIT/payment integrations or validate a
research hypothesis. It only checks files and original archives.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import sys

ROOT = Path(__file__).resolve().parent.parent

def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def main() -> None:
    manifest_path = ROOT / "MANIFEST.json"
    if not manifest_path.is_file():
        fail("MANIFEST.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("files", [])
    if not items:
        fail("Manifest contains no file records")
    checked = 0
    for item in items:
        rel = item["path"]
        if rel.startswith("/") or ".." in Path(rel).parts:
            fail("Invalid path in manifest: " + rel)
        path = ROOT / rel
        if not path.is_file():
            fail("Missing file: " + rel)
        if path.stat().st_size != item["size_bytes"]:
            fail("Incorrect byte length: " + rel)
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != item["sha256"]:
            fail("SHA256 mismatch: " + rel)
        checked += 1
    for rel in ["schemas/event.schema.json", "schemas/run_manifest.schema.json"]:
        json.loads((ROOT / rel).read_text(encoding="utf-8"))
    zipped = ROOT / "legacy/raw-results/PaidAuditBench_v0.2_results_full.zip"
    with ZipFile(zipped) as archive:
        bad = archive.testzip()
        if bad:
            fail("Legacy full-results ZIP corruption: " + bad)
        if not any(name.endswith("trials.jsonl") for name in archive.namelist()):
            fail("Legacy ZIP missing trial traces")
    pdf = ROOT / "inputs/From chat collusion to bribes.pdf"
    if not pdf.open("rb").read(5) == b"%PDF-":
        fail("Input reference is not PDF")
    required = [
        "README.md", "START_HERE.md", "CODEX_MASTER_PROMPT.md", "AGENTS.md",
        "planning/WORK_ORDERS.md", "planning/STAGE_GATES.md",
        "planning/ACCEPTANCE_TEST_MATRIX.md", "docs/08_PROTOCOL_COVERAGE.md",
        "docs/16_UPSTREAM_SOURCE_REGISTER.md",
        "legacy/paid-audit-bench-v0.2-source/paidaudit/study.py",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            fail("Required file missing: " + rel)
    print(f"PASS: verified SHA256/length of {checked} manifest files")
    print("PASS: both JSON schemas parse")
    print("PASS: previous full-results ZIP contains trial traces and passes CRC")
    print("PASS: original preliminary research PDF present")
    print("IMPORTANT: This check does not show any native payment integration or LLM study was run.")

if __name__ == "__main__":
    main()
