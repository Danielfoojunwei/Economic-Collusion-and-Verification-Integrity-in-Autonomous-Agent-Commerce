"""Validate prospective record shape where the pinned ORBIT venv supplies jsonschema."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

try:
    import jsonschema
except ImportError:
    jsonschema = None


@unittest.skipUnless(jsonschema is not None, "jsonschema needed for full schema validation")
class JournalSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "journal_A_v1/episode_record.schema.json"
        cls.schema = json.loads(path.read_text())
        jsonschema.validators.validator_for(cls.schema).check_schema(cls.schema)
        cls.validator = jsonschema.validators.validator_for(cls.schema)(cls.schema)

    def valid_record(self):
        return {
            "schema_version": "journal-A-draft-v1", "study_id": "A1", "episode_id": "e1",
            "assignment_id": "a1", "obligation_id": "booking1",
            "execution_tier": "REAL_LLM_REMOTE", "model_tier": "REAL_LLM_REMOTE",
            "transaction_tier": "NOT_EXECUTED", "truth": "BAD",
            "arms": {"compensation": "FLAT", "contact": "WITHHELD",
                     "verification_price": "LOW", "proof_guard": False},
            "observation": {"behavior_endpoint_observed": False,
                            "native_endpoint_observed": False,
                            "collection_complete": False, "billing_reconciled": False},
            "semantics": {"solicitation": "UNKNOWN", "exposure": "UNKNOWN",
                          "assent": "UNKNOWN", "authoritative_evidence": "UNKNOWN",
                          "check_completed": "UNKNOWN", "verdict": "UNKNOWN"},
            "money": {"asset": "local-test-token", "unit_scale": 1,
                      "buyer_release_minor": None, "buyer_refund_minor": None,
                      "auditor_transfer_minor": None, "check_debit_minor": None,
                      "execution_fee_minor": None},
            "status": "NOT_STARTED"
        }

    def test_unknown_is_distinct_from_zero_and_record_is_valid(self):
        self.validator.validate(self.valid_record())

    def test_rejects_false_precision_and_missing_truth(self):
        for path, value in ((('money', 'buyer_release_minor'), 0.5),
                            (('semantics', 'assent'), True),
                            (('status',), 'REJECT'),
                            (('arms', 'verification_price'), 'FREE')):
            row = deepcopy(self.valid_record())
            cursor = row
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(jsonschema.ValidationError):
                self.validator.validate(row)
        row = self.valid_record()
        del row['truth']
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(row)

    def test_rejects_impossible_observation_state(self):
        row = self.valid_record()
        row['observation']['native_endpoint_observed'] = True
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(row)
        row['status'] = 'PARTIAL'
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(row)


if __name__ == '__main__':
    unittest.main()
