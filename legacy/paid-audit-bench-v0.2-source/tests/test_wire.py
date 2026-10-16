import unittest
from paidaudit.wiremock import SandboxHTTP,smoke_once

class TestLocalHttpWireShapes(unittest.TestCase):
    def test_x402_mpp_402_and_credentials_and_replay(self):
        with SandboxHTTP() as server:
            for proto in ("x402","mpp"):
                with self.subTest(proto=proto):
                    result=smoke_once(server,proto)
                    self.assertEqual(result["challenge_status"],402)
                    self.assertEqual(result["credential_status"],200)
                    self.assertEqual(result["replay_status"],409)
                    self.assertFalse(result["real_settlement"])

    def test_changed_economic_terms_rejected(self):
        with SandboxHTTP() as server:
            for proto in ("x402","mpp"):
                with self.subTest(proto=proto):
                    result=smoke_once(server,proto,attack="alter_amount")
                    self.assertEqual(result["credential_status"],403)

if __name__=="__main__":unittest.main()
