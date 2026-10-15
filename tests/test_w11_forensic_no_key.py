"""Credential-free W11 archive scan keeps candidate bytes out of errors."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.forensic_w11_stopped import _generic_credential_scan


class _EmptyResolvedLog:
    def model_dump_json(self) -> str:
        return "{}"


class NoKeyForensicScanTests(unittest.TestCase):
    def test_safe_archive_and_generic_key_candidate(self):
        with tempfile.TemporaryDirectory(prefix="w11-no-key-", dir="/workspace") as dirname:
            path = Path(dirname) / "archive.txt"
            path.write_bytes(b"ordinary saved model and tool evidence")
            self.assertEqual(_generic_credential_scan(path, _EmptyResolvedLog()),
                             "PASS_NO_CANDIDATE")
            candidate = b"sk-or-v1-" + b"a" * 64
            path.write_bytes(b"model output: " + candidate)
            with self.assertRaises(ValueError) as caught:
                _generic_credential_scan(path, _EmptyResolvedLog())
            self.assertNotIn(candidate.decode(), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
