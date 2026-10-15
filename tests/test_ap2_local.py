"""Native AP2 SDK W15 integration tests; skipped in base environment."""

import importlib.util
import unittest


AP2_AVAILABLE = importlib.util.find_spec("ap2") is not None
if AP2_AVAILABLE:
    from jwcrypto.jwk import JWK
    from scripts.run_ap2_local import (
        BASE,
        PaymentAuthorization,
        create_presentation,
        new_test_key,
        run_cases,
    )


@unittest.skipUnless(AP2_AVAILABLE, "pinned AP2 SDK v0.2.0 is not installed")
class Ap2LocalIntegrationTests(unittest.TestCase):
    def test_official_sdk_conformance_cases(self):
        result = run_cases()
        self.assertEqual(result["upstream_tag"], "v0.2.0")
        self.assertEqual(result["execution_tier"], "NATIVE_LOCAL_PROTOCOL")
        self.assertEqual(result["payment_execution"], "NONE: signed authorization only; no PSP or funds")
        self.assertEqual(result["fail_count"], 0, result["cases"])
        self.assertEqual(result["pass_count"], 17)
        self.assertFalse(result["private_keys_written"])
        self.assertNotIn("~~", str(result["cases"]))

    def test_replay_is_caller_control_after_sdk_validation(self):
        issuer = new_test_key()
        agent = new_test_key()
        presentation = create_presentation(issuer, agent)
        verifier = PaymentAuthorization(JWK.from_json(issuer.export_public()))
        reference = verifier.authorize(presentation, BASE)
        self.assertEqual(len(reference), 43)
        with self.assertRaisesRegex(ValueError, "replay"):
            verifier.authorize(presentation, BASE)
        fresh_verifier = PaymentAuthorization(JWK.from_json(issuer.export_public()))
        self.assertEqual(fresh_verifier.authorize(presentation, BASE), reference)


if __name__ == "__main__":
    unittest.main()
