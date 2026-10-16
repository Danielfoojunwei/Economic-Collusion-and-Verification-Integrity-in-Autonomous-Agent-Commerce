"""Negative controls for the source-only BILATERAL030 paid-run contract."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import unittest
from unittest.mock import patch

from agent_economic_trust.bilateral030_hosted_contract import (
    HostedContractError, exact_private_assignment, preview_block_reserve,
    structural_block_reservation, structural_row_progress,
)
from agent_economic_trust.bilateral030_orchestration import preflight_proposal
from agent_economic_trust.bilateral030_plan import (
    CANONICAL_LEDGER, ROWS, STUDY, make_schedule, required_headroom,
)
from agent_economic_trust.bilateral030_remote import historical_catalog
from agent_economic_trust.remote_budget import BudgetLedger


IDENTITY = "4a" * 32
ASSIGNMENT = "b7" * 32
HASH = "a" * 64


def _journal(ids: list[str]) -> list[dict]:
    return [{"episode_id": episode, "status": "PENDING", "attempts": 0,
             "outcome": None, "trace_review_sha256": None,
             "native_review_sha256": None, "billing_review_sha256": None,
             "billing_state": None, "stop_scope": None,
             "stop_review_sha256": None, "fresh_context_sha256": None}
            for episode in ids]


class HostedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = preflight_proposal(IDENTITY, ASSIGNMENT)
        cls.rows = make_schedule(IDENTITY, ASSIGNMENT)
        cls.catalog = historical_catalog()

    def test_exact_assignment_binds_private_rows_and_public_proposal(self):
        self.assertEqual(
            exact_private_assignment(self.proposal, IDENTITY, ASSIGNMENT),
            self.rows)
        with self.assertRaises(HostedContractError):
            exact_private_assignment(self.proposal, IDENTITY, "c8" * 32)
        with self.assertRaises(HostedContractError):
            exact_private_assignment(self.proposal, IDENTITY, IDENTITY)
        changed = deepcopy(self.proposal)
        changed["public_assignment_preview"]["public_rows"][0]["provider_id"] = "provider-fake"
        with self.assertRaises(HostedContractError):
            exact_private_assignment(changed, IDENTITY, ASSIGNMENT)
        forged = deepcopy(self.proposal)
        forged["proposal_seal"]["private_rows_sha256"] = "0" * 64
        with self.assertRaises(HostedContractError):
            exact_private_assignment(forged, IDENTITY, ASSIGNMENT)

    def test_unfunded_preview_is_read_only_and_never_authorizes(self):
        before = CANONICAL_LEDGER.read_bytes()
        anchor = CANONICAL_LEDGER.with_name(CANONICAL_LEDGER.name + ".anchor")
        before_anchor = anchor.read_bytes()
        snapshot = BudgetLedger(CANONICAL_LEDGER).snapshot()
        with patch.object(BudgetLedger, "reserve",
                          side_effect=AssertionError("source preview mutated ledger")):
            result = preview_block_reserve(self.rows, self.catalog, snapshot)
        self.assertEqual(result["required_full_block_usd"], "36.0208342")
        self.assertEqual(result["status"], "HOLD_SOURCE_ONLY")
        self.assertFalse(result["permission_to_reserve_or_call"])
        self.assertIn("FULL_BLOCK_HEADROOM_INSUFFICIENT", result["hold_reasons"])
        self.assertEqual(CANONICAL_LEDGER.read_bytes(), before)
        self.assertEqual(anchor.read_bytes(), before_anchor)
        altered = dict(snapshot, unknown_run_ids=["unreconciled"],
                       available_usd="49", blocked=False)
        result = preview_block_reserve(self.rows, self.catalog, altered)
        self.assertIn("PRIOR_BILLING_OR_SHARED_LEDGER_BLOCKED", result["hold_reasons"])
        broken = deepcopy(self.catalog)
        broken.pop(next(iter(broken)))
        with self.assertRaises(HostedContractError):
            preview_block_reserve(self.rows, broken, snapshot)

    def test_even_matching_reservation_claim_is_not_execution_proof(self):
        # A synthetic snapshot can match the shape; it does not authenticate
        # a current ledger head or permit a paid model request.
        with patch("agent_economic_trust.bilateral030_orchestration.source_inventory",
                   return_value={"source_snapshot_sha256": HASH,
                                 "local_source_inventory_clean": True}):
            proposal = preflight_proposal(IDENTITY, ASSIGNMENT)
        quote = required_headroom(self.catalog, self.rows)
        run_id = "bilateral030-block-" + proposal["proposal_sha256"][:12]
        seal = proposal["proposal_seal"]
        metadata = {"study": STUDY, "planned_rows": ROWS,
                    "proposal_sha256": proposal["proposal_sha256"],
                    "private_rows_sha256": seal["private_rows_sha256"],
                    "source_snapshot_sha256": seal["source_snapshot_sha256"]}
        snapshot = {"cap_usd": "50", "blocked": False,
                    "unknown_run_ids": [], "contingent_run_ids": [],
                    "runs": {run_id: {"status": "RESERVED",
                                      "reserved_usd": str(quote),
                                      "metadata": metadata}}}
        review = structural_block_reservation(
            proposal, self.rows, self.catalog, snapshot)
        self.assertFalse(review["permission_to_call_model"])
        self.assertEqual(review["status"], "HOLD_SOURCE_ONLY_UNAUTHENTICATED_SNAPSHOT")
        self.assertFalse(structural_block_reservation(
            proposal, self.rows, self.catalog,
            {**snapshot, "blocked": True})["permission_to_call_model"])
        with self.assertRaises(HostedContractError):
            structural_block_reservation(
                proposal, make_schedule(IDENTITY, "c8" * 32),
                self.catalog, snapshot)
        for changed in (
            {**snapshot, "runs": {}},
            {**snapshot, "contingent_run_ids": ["prior-hold"]},
            {**snapshot, "runs": {run_id: {"status": "RESERVED",
                                          "reserved_usd": str(quote - Decimal("0.000001")),
                                          "metadata": metadata}}},
            {**snapshot, "runs": {run_id: {"status": "RESERVED",
                                          "reserved_usd": "Infinity",
                                          "metadata": metadata}}},
            {**snapshot, "runs": {run_id: {"status": "RESERVED",
                                          "reserved_usd": str(quote),
                                          "metadata": {**metadata,
                                                       "proposal_sha256": "0" * 64}}}},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(HostedContractError):
                    structural_block_reservation(
                        proposal, self.rows, self.catalog, changed)

    def test_row_local_stop_can_be_structurally_retained_as_missing(self):
        ids = [row.episode_id for row in self.rows]
        journal = _journal(ids)
        journal[0].update(status="STOPPED", attempts=1, stop_scope="ROW_LOCAL",
                          billing_state="BOUNDED_WORST_CASE_HELD",
                          stop_review_sha256=HASH,
                          fresh_context_sha256=sha256(b"fresh").hexdigest())
        journal[1].update(status="COMPLETE_CLAIM", attempts=1, outcome=False,
                          trace_review_sha256=sha256(b"trace").hexdigest(),
                          native_review_sha256=sha256(b"native").hexdigest(),
                          billing_review_sha256=sha256(b"bill").hexdigest(),
                          billing_state="ATTRIBUTABLE")
        result = structural_row_progress(ids, journal)
        self.assertEqual(result["stopped_missing_outcome"], 1)
        self.assertEqual(result["complete_claims_unverified"], 1)
        self.assertEqual(result["next_unattempted_index"], 2)
        self.assertFalse(result["permission_to_advance_or_call"])
        for field, value in (("billing_state", "UNKNOWN"),
                             ("stop_scope", "GLOBAL_HOLD"),
                             ("stop_review_sha256", None),
                             ("fresh_context_sha256", None),
                             ("outcome", False)):
            changed = deepcopy(journal)
            changed[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(HostedContractError):
                    structural_row_progress(ids, changed)

    def test_journal_rejects_retry_replacement_gap_and_unreviewed_complete(self):
        ids = [row.episode_id for row in self.rows]
        journal = _journal(ids)
        cases = []
        changed = deepcopy(journal)
        changed[0]["attempts"] = 2
        cases.append(changed)
        changed = deepcopy(journal)
        changed[0]["episode_id"] = "replacement"
        cases.append(changed)
        changed = deepcopy(journal)
        changed[1].update(status="COMPLETE_CLAIM", attempts=1, outcome=True,
                          trace_review_sha256=HASH,
                          native_review_sha256=HASH,
                          billing_review_sha256=HASH,
                          billing_state="ATTRIBUTABLE")
        cases.append(changed)
        changed = deepcopy(journal)
        changed[0].update(status="COMPLETE_CLAIM", attempts=1, outcome=True,
                          billing_state="ATTRIBUTABLE")
        cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed[:2]):
                with self.assertRaises(HostedContractError):
                    structural_row_progress(ids, changed)


if __name__ == "__main__":
    unittest.main()
