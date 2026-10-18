"""Read-only negative controls for the Paper A A0 local receipt reviewer."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'artifacts/exploratory/JOURNAL_A0_NATIVE_2026-10-18_002/evidence.json'
VERIFIER = ROOT / 'protocols/mpp/journal-a0-verify.mjs'


class NativeA0ReviewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EVIDENCE.is_file():
            raise unittest.SkipTest('Paper A local evidence not present')
        cls.saved = json.loads(EVIDENCE.read_text())
        url = urlsplit(cls.saved['rpc_url'])
        try:
            with socket.create_connection((url.hostname, url.port), timeout=1):
                pass
        except OSError:
            raise unittest.SkipTest('Paper A isolated historical local chain is unavailable')

    def verify(self, evidence):
        with tempfile.TemporaryDirectory(prefix='journal-a0-review-') as directory:
            source = Path(directory) / 'evidence.json'
            report = Path(directory) / 'review.json'
            source.write_text(json.dumps(evidence))
            result = subprocess.run(['node', str(VERIFIER), str(source), str(report)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=30)
            return result.returncode, report.exists()

    def test_original_native_receipts_pass(self):
        code, produced = self.verify(self.saved)
        self.assertEqual(code, 0)
        self.assertTrue(produced)

    def test_tampered_amount_payee_duplicate_and_case_fail(self):
        for label, mutation in (
            ('amount', lambda x: x['rows'][0]['transactions'][0].update(amount_minor='999')),
            ('payee', lambda x: x['rows'][0]['transactions'][0].update(to=x['rows'][0]['auditor'])),
            ('duplicate', lambda x: x['rows'][0]['transactions'][1].update(
                hash=x['rows'][0]['transactions'][0]['hash'])),
            ('case', lambda x: x['rows'][0].update(buyer_released=False)),
            ('mpp_amount', lambda x: x['rows'][0]['proof']['mpp_http']['challenge'].update(
                amount='6')),
            ('mpp_credential', lambda x: x['rows'][0]['proof']['mpp_http'].update(
                authorization='invalid')),
        ):
            bad = deepcopy(self.saved)
            mutation(bad)
            with self.subTest(label=label):
                code, produced = self.verify(bad)
                self.assertNotEqual(code, 0)
                self.assertFalse(produced)


if __name__ == '__main__':
    unittest.main()
