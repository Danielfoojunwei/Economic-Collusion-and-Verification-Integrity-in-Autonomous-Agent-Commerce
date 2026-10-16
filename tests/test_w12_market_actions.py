"""W12 read-only attribution against archived scripted W11 native smoke evidence."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from inspect_ai.log import read_eval_log

from agent_economic_trust.coordination_metrics import actions_from_events
from agent_economic_trust.w12_market_actions import (
    MarketActionError, _assigned_round, _saved_tool_links, _sha, _transform,
    derive_market_actions, export_market_actions,
)


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/gates/W11_SCRIPTED/market-smoke-003"
PLAN = ROOT / "artifacts/gates/W11_DESIGN/assignment-006"


def episode(episode_id: str) -> Path:
    matches = list(RUN.glob(f"*/episodes/{episode_id}"))
    if len(matches) != 1:
        raise AssertionError(f"missing scripted W11 smoke episode {episode_id}")
    return matches[0]


class W12MarketActionsTests(unittest.TestCase):
    def test_client_and_provider_fee_payers_have_distinct_verified_nets(self):
        # These are scripted behavior plus native local payments, never LLM outcomes.
        cases = (
            ("episode-1dc552a5a2c76ed008a9", 0, "FAIL", 0, 0, 2_000_000),
            ("episode-3fe26e4342b1eb9878f0", 0, "PASS", 20_000_000,
             20_000_000, 2_000_000),
            ("episode-1e71fe47154315db66c8", 1, "FAIL", 0, -2_000_000, 2_000_000),
            ("episode-e4ec91e1f70524236b39", 1, "PASS", 20_000_000,
             18_000_000, 2_000_000),
        )
        for episode_id, r, oracle, payout, provider_net, auditor_net in cases:
            with self.subTest(episode_id=episode_id):
                result = derive_market_actions(episode(episode_id), PLAN)
                actions = result.actions
                self.assertEqual(result.provenance["R"], r)
                self.assertEqual(actions.oracle_status, oracle)
                self.assertEqual(actions.principal_to_provider_minor, payout)
                self.assertEqual(actions.provider_net_minor, provider_net)
                self.assertEqual(actions.verifier_net_minor, auditor_net)
                self.assertEqual(actions.coalition_net_minor, payout + (2_000_000 if r == 0 else 0))
                self.assertFalse(actions.false_approval)
                self.assertFalse(actions.wrongful_payment)
                self.assertEqual(actions.explicit_signal_event_ids, ())
                self.assertEqual(actions_from_events(result.canonical_events), actions)

    def test_offer_assignment_is_not_observed_delivery_or_agreement(self):
        unread = derive_market_actions(episode("episode-675e3412e1cf31a6e841"), PLAN)
        delivered = derive_market_actions(episode("episode-cf1b36e79b7846108617"), PLAN)
        for result in (unread, delivered):
            self.assertEqual(result.communication["assigned_offer_variant"],
                             "AUTHORED_UNTRUSTED_PROMISE")
            self.assertTrue(result.communication["researcher_authored_message"])
            self.assertEqual(result.communication["independent_explicit_agreement_annotation"],
                             "NOT_PERFORMED")
            self.assertEqual(result.actions.explicit_signal_event_ids, ())
        self.assertFalse(unread.communication["assigned_message_read"])
        self.assertTrue(delivered.communication["assigned_message_read"])

    def test_source_to_derived_links_and_escrow_route_are_explicit(self):
        source = episode("episode-e4ec91e1f70524236b39")
        result = derive_market_actions(source, PLAN)
        original = [json.loads(line) for line in (source / "events.jsonl").read_text().splitlines()]
        previous = None
        for derived, old in zip(result.canonical_events, original, strict=True):
            self.assertEqual(derived["parent_event_id"], previous)
            self.assertEqual(derived["payload"]["w12_derivation"]["source_event_id"], old["event_id"])
            previous = derived["event_id"]
        release = [event for event in result.canonical_events
                   if event["event_type"] == "PAYMENT_SETTLED"
                   and event["payload"].get("payment_kind") == "erc8183_job_release_via_escrow"]
        self.assertEqual(len(release), 1)
        self.assertEqual(release[0]["payload"]["payer_id"], "client")
        self.assertEqual(release[0]["payload"]["raw_transfer_from"].lower(),
                         result.provenance["native_erc8183_escrow_address"].lower())
        self.assertEqual(release[0]["payload"]["raw_transfer_to"].lower(),
                         result.provenance["native_party_addresses"][result.actions.provider_id].lower())

    def test_wrong_assignment_and_forged_fee_payee_fail_closed(self):
        path = episode("episode-1e71fe47154315db66c8")
        with self.assertRaises(MarketActionError):
            derive_market_actions(path, ROOT / "artifacts/gates/W11_DESIGN/assignment-005")
        result = derive_market_actions(path, PLAN)
        rows = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        fee = next(item for item in rows if item["event_type"] == "AUDITOR_FEE_PAID")
        fee["payload"]["payee_id"] = "other-auditor"
        row, _, _ = _assigned_round(PLAN, result.actions.episode_id)
        native_data = json.loads((path / "native_evidence.json").read_bytes())
        native = next(item for item in native_data["rounds"]
                      if item["episode_id"] == result.actions.episode_id)
        with self.assertRaises(MarketActionError):
            _transform(rows, source_hash="0" * 64, row=row, native=native,
                       evidence=native_data,
                       score={"Q": True, "V": "REJECT", "oracle_status": "FAIL"})

    def test_tampered_saved_events_and_in_place_output_fail_closed(self):
        path = episode("episode-1e71fe47154315db66c8")
        with self.assertRaises(MarketActionError):
            export_market_actions(path, PLAN, path / "w12")
        with self.assertRaises(MarketActionError):
            export_market_actions(path, PLAN, PLAN / "w12")
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "episode"
            copy.mkdir()
            for name in ("events.jsonl", "episode_outcomes.csv", "run_manifest.json",
                         "episode_record.json", "native_evidence.json", "inspect.eval"):
                shutil.copy2(path / name, copy / name)
            events = copy / "events.jsonl"
            events.write_text(events.read_text().replace("valueless MockUSDC", "real USD", 1))
            with self.assertRaises(ValueError):
                derive_market_actions(copy, PLAN)

    def test_native_tool_link_cannot_be_omitted(self):
        path = episode("episode-1e71fe47154315db66c8")
        row, _, _ = _assigned_round(PLAN, path.name)
        saved = read_eval_log(str(path / "inspect.eval"), resolve_attachments=True)
        rows = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        check = next(item for item in rows if item["event_type"] == "CHECK_COMPLETED")
        del check["payload"]["native_event_id"]
        with self.assertRaises(MarketActionError):
            _saved_tool_links(rows, saved, row)

    def test_export_is_separate_and_keeps_source_hashes(self):
        path = episode("episode-3fe26e4342b1eb9878f0")
        before = {name: _sha(path / name) for name in ("events.jsonl", "inspect.eval",
                                                    "native_evidence.json", "episode_record.json")}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "w12"
            summary = export_market_actions(path, PLAN, out)
            self.assertEqual(summary["provenance"]["inference_tier"], "ACTION_ATTRIBUTION_ONLY")
            self.assertEqual(summary["canonical_events_sha256"], _sha(out / "canonical_events.jsonl"))
            self.assertEqual(len((out / "canonical_events.jsonl").read_text().splitlines()), 19)
            with self.assertRaises(FileExistsError):
                export_market_actions(path, PLAN, out)
        self.assertEqual(before, {name: _sha(path / name) for name in before})


if __name__ == "__main__":
    unittest.main()
