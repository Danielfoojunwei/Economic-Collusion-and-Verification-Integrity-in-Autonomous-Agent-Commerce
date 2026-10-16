"""Adversarial checks for the stopped W11 provider-session attribution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from inspect_ai.log import read_eval_log

from scripts.verify_w11_provider_reconciliation import (
    CSV_HASHES, EVIDENCE_DIR, FROZEN_LEDGER, INSPECT_MODEL, INSPECT_SHA, LEDGER,
    SESSION_USAGE, BudgetLedger, validate_csv_tables,
    validate_inspect_session, validate_ledger_prestate, verify,
)


class ProviderReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.csvs = {name: (EVIDENCE_DIR / name).read_bytes() for name in CSV_HASHES}
        cls.log = read_eval_log(str(Path(__file__).resolve().parents[1] /
                                    "artifacts/gates/W11_LIVE/market-runs-001/"
                                    "market-acb40c26ae8838c87fd3/episodes/"
                                    "episode-de0a57bf5b8ca2bbe753/inspect.eval"),
                                resolve_attachments=False)

    def check_tables(self, *, count: bytes | None = None, hourly: bytes | None = None,
                     session: bytes | None = None):
        return validate_csv_tables(count or self.csvs["request_count_hourly.csv"],
                                   hourly or self.csvs["usage_count_hourly.csv"],
                                   session or self.csvs["usage_by_session.csv"])

    def test_real_exports_and_ledger_are_read_only(self):
        before = LEDGER.read_bytes()
        tables = self.check_tables()
        self.assertEqual(tables["target_total_usage_usd"], format(SESSION_USAGE, "f"))
        self.assertEqual(sum(tables["hourly_request_counts"].values()), 264)
        evidence = verify()
        self.assertEqual(evidence["settlement_candidate_usd"], "0.037002")
        self.assertEqual(evidence["ledger_prestate"]["run_status"], "UNKNOWN")
        self.assertEqual(evidence["paid_model_calls"], 0)
        self.assertEqual(LEDGER.read_bytes(), before)

    def test_hourly_request_count_mismatch_rejected(self):
        altered = self.csvs["request_count_hourly.csv"].replace(b"Sol,44", b"Sol,45")
        with self.assertRaisesRegex(ValueError, "counts disagree"):
            self.check_tables(count=altered)

    def test_hourly_usage_mismatch_rejected(self):
        altered = self.csvs["usage_by_session.csv"].replace(b"0.03295,6", b"0.03296,6")
        with self.assertRaisesRegex(ValueError, "does not sum"):
            self.check_tables(session=altered)

    def test_target_uuid_count_and_model_mismatch_rejected(self):
        session = self.csvs["usage_by_session.csv"]
        for altered in (
            session.replace(b"X3NZV22BrmsPPw3eFEjYkb", b"unmatched-session-id"),
            session.replace(b"X3NZV22BrmsPPw3eFEjYkb,0.037002,8",
                            b"X3NZV22BrmsPPw3eFEjYkb,0.037002,7"),
        ):
            with self.subTest(altered=altered[-40:]), self.assertRaises(ValueError):
                self.check_tables(session=altered)
        model = self.csvs["usage_count_hourly.csv"].replace(b"GPT-5.6 Sol", b"Other Model")
        with self.assertRaisesRegex(ValueError, "unexpected model"):
            self.check_tables(hourly=model)

    def test_provider_session_wrong_hour_rejected(self):
        altered = self.csvs["usage_by_session.csv"].replace(
            b"2026-10-15 07:00:00,X3NZV22BrmsPPw3eFEjYkb",
            b"2026-10-15 08:00:00,X3NZV22BrmsPPw3eFEjYkb")
        with self.assertRaises(ValueError):
            self.check_tables(session=altered)

    def test_saved_sample_uuid_model_count_and_time_rejected(self):
        sample = self.log.samples[0]
        self.assertEqual(validate_inspect_session(sample, INSPECT_MODEL)["model_events"], 8)
        first_model = next(index for index, event in enumerate(sample.events)
                           if event.event == "model")
        missing_model_event = sample.events[:first_model] + sample.events[first_model + 1:]
        variants = (
            (sample.model_copy(update={"uuid": "different-session"}), INSPECT_MODEL),
            (sample, "openrouter/openai/other-model"),
            (sample.model_copy(update={"events": missing_model_event}), INSPECT_MODEL),
            (sample.model_copy(update={"started_at": "2026-10-15T06:25:09+00:00"}), INSPECT_MODEL),
        )
        for altered, model in variants:
            with self.subTest(model=model, uuid=altered.uuid,
                              started_at=altered.started_at,
                              event_count=len(altered.events)), self.assertRaises(ValueError):
                validate_inspect_session(altered, model)

    def test_inspect_archive_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(prefix="w11-provider-test-", dir="/workspace") as dirname:
            altered = Path(dirname) / "inspect.eval"
            altered.write_bytes(b"not the pinned Inspect archive")
            with self.assertRaisesRegex(ValueError, "pinned input changed"):
                verify(log_path=altered)
        self.assertEqual(INSPECT_SHA, verify()["saved_run"]["inspect_sha256"])

    def test_unknown_reservation_required(self):
        snapshot = BudgetLedger(FROZEN_LEDGER).snapshot()
        self.assertEqual(validate_ledger_prestate(snapshot)["run_status"], "UNKNOWN")
        altered = deepcopy(snapshot)
        altered["runs"][altered["unknown_run_ids"][0]]["status"] = "SETTLED"
        with self.assertRaisesRegex(ValueError, "UNKNOWN reservation"):
            validate_ledger_prestate(altered)
        altered = deepcopy(snapshot)
        altered["reserved_usd"] = "0"
        with self.assertRaisesRegex(ValueError, "UNKNOWN reservation"):
            validate_ledger_prestate(altered)


if __name__ == "__main__":
    unittest.main()
