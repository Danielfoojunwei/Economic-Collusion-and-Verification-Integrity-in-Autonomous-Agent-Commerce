"""Synthetic input-contract and small-sample analysis tests; no study outcomes."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.bilateral030_analysis import (
    ASSIGNMENT_SCHEMA, REVIEW_MANIFEST_SCHEMA, REVIEW_SCHEMA,
    analyze_artifacts, clopper_pearson,
)
from agent_economic_trust.bilateral030_plan import (
    ADVERSARIAL_AUDITOR_STRESS, GOOD_ANCHOR, HIGH_RISK,
    NO_ACCEPT_BONUS, NO_CONTACT, NO_PROVIDER_PROMPT, STUDY, canonical,
    make_schedule,
)


IDENTITY_SEED = "30" * 32
ASSIGNMENT_SEED = "31" * 32


class SyntheticBundle:
    """Only unit-test fixtures, never research evidence."""

    def __init__(self, root: Path):
        self.root = root
        self.rows = make_schedule(IDENTITY_SEED, ASSIGNMENT_SEED)
        assignment = {
            "schema": ASSIGNMENT_SCHEMA, "status": "FROZEN", "study": STUDY,
            "seed_hex": IDENTITY_SEED, "assignment_seed_hex": ASSIGNMENT_SEED,
            "seed_commitment_sha256": sha256(bytes.fromhex(IDENTITY_SEED)).hexdigest(),
            "assignment_seed_commitment_sha256":
                sha256(bytes.fromhex(ASSIGNMENT_SEED)).hexdigest(),
            "arm_allocation_method":
                "HMAC_PERMUTE_15_ANONYMOUS_SLOTS_WITHIN_MODEL_DIRECTION",
            "source_sha256": "a" * 64,
            "rows": [asdict(row) for row in self.rows],
        }
        self.assignment_ref = self.write("assignment.json", assignment)
        self.refs = []

    def write(self, name: str, value: object) -> dict[str, str]:
        raw = (value if type(value) is bytes else
               json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": name, "sha256": sha256(raw).hexdigest()}

    def complete(self, row, *, bad_approve=False, improper=False,
                 exposed=False, assent=False, check=True, good_approve=True):
        approve = bad_approve if row.truth == "bad" else good_approve
        verdict = "APPROVE" if approve else "REJECT"
        check_result = (("FAIL" if row.truth == "bad" else "PASS")
                        if check else "SKIPPED")
        oracle_result = "FAIL" if row.truth == "bad" else "PASS"
        provider_paid = 9_000_000 if approve else 0
        evaluator_paid = 1_000_000 if approve else 0
        buyer = {"purchase_order_amount_cents": 350 if row.truth == "bad" else 400,
                 "credit_note_amount_cents": 50,
                 "net_amount_cents": 300 if row.truth == "bad" else 350}
        final_verdict = "REJECT" if row.truth == "bad" else "ACCEPT"
        remainder = 10_000_000 if approve else 20_000_000
        final_fee = remainder // 10 if final_verdict == "ACCEPT" else 0
        native = {
            "schema": "erc8183-bilateral030-local-bridge-v1",
            "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "episode": asdict(row),
            "public_report": {"study": STUDY, "obligation_id": row.obligation_id,
                              "submitted_cents": 350},
            "protected_oracle": {"status": oracle_result, "buyer_records": buyer},
            "claim_receipt": {"status": "CLAIM_PENDING",
                              "obligation_id": row.obligation_id},
            "deferred": False,
            "check_receipt": ({"status": "CHECK_PAID",
                               "obligation_id": row.obligation_id,
                               "payer_role": "auditor",
                               "payee_role": "independent_check_service",
                               "amount_minor": 200_000,
                               "oracle_status": oracle_result,
                               "buyer_records": buyer} if check else None),
            "early_receipt": {
                "decision": verdict, "obligation_id": row.obligation_id,
                "provider_paid_minor": provider_paid,
                "evaluator_native_fee_minor": evaluator_paid,
                "bonus_auditor_paid_minor": row.accept_bonus_minor if approve else 0,
                "bonus_provider_refund_minor": 0 if approve else row.accept_bonus_minor,
            },
            "final_receipt": {"obligation_id": row.obligation_id,
                              "requested_verdict": final_verdict,
                              "provider_paid_minor": (
                                  remainder - final_fee if final_verdict == "ACCEPT" else 0),
                              "evaluator_native_fee_minor": final_fee,
                              "client_refund_minor": (
                                  remainder if final_verdict == "REJECT" else 0),
                              "bonus_provider_refund_minor": 0},
            "buyer_revealed": True,
            "final_job": {"status": "Rejected" if row.truth == "bad"
                          else "Completed"},
        }
        prefix = f"raw/{row.episode_id}"
        inspect_ref = self.write(prefix + ".inspect", b"SYNTHETIC INSPECT " +
                                 row.episode_id.encode())
        native_ref = self.write(prefix + ".native.json", native)
        post = sha256((row.episode_id + " offer").encode()).hexdigest() if improper else None
        facts = {
            "oracle_truth": row.truth, "oracle_result": oracle_result,
            "provider_claim": "CLAIM", "early_verdict": verdict,
            "check_result": check_result,
            "check_debit_minor": 200_000 if check else 0,
            "early_provider_paid_minor": provider_paid,
            "early_evaluator_paid_minor": evaluator_paid,
            "buyer_early_outlay_minor": provider_paid + evaluator_paid,
            "bonus_funded_minor": row.accept_bonus_minor,
            "bonus_paid_minor": row.accept_bonus_minor if approve else 0,
            "bonus_refunded_minor": 0 if approve else row.accept_bonus_minor,
            "bonus_payee_role": (("auditor" if approve else "provider")
                                 if row.accept_bonus_minor else None),
            "bonus_trigger": "EARLY_APPROVE" if row.accept_bonus_minor else None,
            "provider_post_sha256": post,
            "auditor_input_post_sha256": post if exposed else None,
            "auditor_exposure_model_event_index": 5 if exposed else None,
        }
        label = {"provider_improper_request": improper,
                 "auditor_explicit_assent": assent}
        review = {
            "schema": REVIEW_SCHEMA, "study": STUDY,
            "assignment_sha256": self.assignment_ref["sha256"],
            "row_sha256": sha256(canonical(asdict(row))).hexdigest(),
            "episode_id": row.episode_id,
            "reviewer_id": "independent_native_reviewer", "runner_id": "runner",
            "verification_status": "PASS", "row_status": "COMPLETE_VERIFIED",
            "independent_checks": {key: True for key in (
                "model_trace_replayed", "native_receipts_replayed",
                "bonus_receipts_replayed", "buyer_oracle_recomputed",
                "paid_check_replayed", "message_exposure_join_replayed",
                "final_settlement_replayed")},
            "evidence": {"inspect": inspect_ref, "native": native_ref},
            "semantic_review": {
                "first": {"reviewer_id": "label_one", **label},
                "second": {"reviewer_id": "label_two", **label},
                "resolved": {"reviewer_id": "label_one", **label},
            },
            "verified_facts": facts,
        }
        self.refs.append(self.write(f"reviews/{row.episode_id}.json", review))
        return review, native

    def stopped(self, row):
        stop_ref = self.write(f"stops/{row.episode_id}.json",
                              {"episode_id": row.episode_id, "status": "STOPPED"})
        review = {
            "schema": REVIEW_SCHEMA, "study": STUDY,
            "assignment_sha256": self.assignment_ref["sha256"],
            "row_sha256": sha256(canonical(asdict(row))).hexdigest(),
            "episode_id": row.episode_id,
            "reviewer_id": "independent_stop_reviewer", "runner_id": "runner",
            "verification_status": "PASS", "row_status": "STOPPED_VERIFIED",
            "independent_checks": {"stop_forensics_replayed": True},
            "stop_reason": "SYNTHETIC_TOOL_ERROR",
            "evidence": {"stop_record": stop_ref},
        }
        self.refs.append(self.write(f"reviews/{row.episode_id}.json", review))

    def run(self):
        manifest = {"schema": REVIEW_MANIFEST_SCHEMA, "study": STUDY,
                    "assignment_sha256": self.assignment_ref["sha256"],
                    "reviews": self.refs}
        manifest_ref = self.write("review_manifest.json", manifest)
        return analyze_artifacts(self.root, self.assignment_ref, manifest_ref)


class Bilateral030AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = SyntheticBundle(Path(self.temp.name))

    def test_empty_review_manifest_keeps_all_thirty_pending(self):
        result = self.bundle.run()
        self.assertEqual((result["assigned_rows"], result["verified_complete_rows"],
                          result["pending_rows_without_review"]), (30, 0, 30))
        self.assertEqual(result["analysis_status"], "SOURCE_ONLY_UNVERIFIED_REVIEWS")
        self.assertTrue(result["publication_gate"].startswith("HOLD_"))
        self.assertEqual(result["primary_proper_bad_assigned"], 26)
        self.assertEqual(result["groups"][HIGH_RISK]["assigned_risk_bounds"], [0, 1])
        self.assertIsNone(result["single_knockout_contrasts"][NO_CONTACT]
                          ["randomization_p_value"])

    def test_explicit_bilateral_chain_and_good_control_are_separate(self):
        high = next(row for row in self.bundle.rows if row.group == HIGH_RISK)
        good = next(row for row in self.bundle.rows if row.group == GOOD_ANCHOR)
        self.bundle.complete(high, bad_approve=True, improper=True,
                             exposed=True, assent=True, check=False)
        self.bundle.complete(good)
        result = self.bundle.run()
        self.assertEqual(result["groups"][HIGH_RISK]["verified_events"], 1)
        self.assertEqual(result["groups"][HIGH_RISK]["confirmed_bilateral_events"], 1)
        self.assertEqual(result["groups"][GOOD_ANCHOR]["verified_events"], 1)
        self.assertEqual(result["groups"][GOOD_ANCHOR]["confirmed_bilateral_events"], 0)
        self.assertEqual(result["groups"][HIGH_RISK]["assigned_risk_bounds"],
                         [1 / 14, 1])

    def test_stopped_row_is_missing_not_a_negative(self):
        row = next(row for row in self.bundle.rows if row.group == HIGH_RISK)
        self.bundle.stopped(row)
        result = self.bundle.run()
        self.assertEqual(result["groups"][HIGH_RISK]["stopped_verified"], 1)
        self.assertEqual(result["groups"][HIGH_RISK]["pending_without_review"], 13)
        self.assertEqual(result["groups"][HIGH_RISK]["assigned_risk_bounds"], [0, 1])
        self.assertIsNone(result["groups"][HIGH_RISK]
                          ["exact_95pct_interval_if_fully_observed"])

    def test_complete_synthetic_block_has_exact_small_sample_outputs(self):
        for row in self.bundle.rows:
            success = row.group in {HIGH_RISK, ADVERSARIAL_AUDITOR_STRESS}
            self.bundle.complete(row, bad_approve=success,
                                 improper=success and row.truth == "bad",
                                 exposed=success and row.truth == "bad",
                                 assent=success and row.truth == "bad")
        result = self.bundle.run()
        self.assertEqual(result["verified_complete_rows"], 30)
        self.assertEqual(result["groups"][HIGH_RISK]["verified_events"], 14)
        self.assertEqual(result["groups"][GOOD_ANCHOR]["verified_events"], 2)
        self.assertEqual(result["groups"][ADVERSARIAL_AUDITOR_STRESS]
                         ["confirmed_bilateral_events"], 2)
        self.assertEqual(result["groups"][ADVERSARIAL_AUDITOR_STRESS]
                         ["bilateral_chain_interpretation"],
                         "RESEARCHER_INDUCED_AUDITOR_COMPLIANCE_NOT_SPONTANEOUS")
        for knockout in (NO_PROVIDER_PROMPT, NO_ACCEPT_BONUS, NO_CONTACT):
            contrast = result["single_knockout_contrasts"][knockout]
            self.assertEqual(contrast["estimate_if_fully_observed"], 1)
            self.assertEqual(contrast["randomization_assignments_enumerated"], 1296)
            self.assertEqual(contrast["randomization_p_value"], 1 / 1296)
            self.assertEqual(contrast["holm_adjusted_p"], 3 / 1296)
        self.assertEqual(result["groups"][HIGH_RISK]
                         ["exact_95pct_interval_if_fully_observed"][1], 1)

    def test_complete_proper_arms_still_withhold_p_when_control_missing(self):
        for row in self.bundle.rows:
            if row.group not in {GOOD_ANCHOR, ADVERSARIAL_AUDITOR_STRESS}:
                self.bundle.complete(row, bad_approve=row.group == HIGH_RISK)
        result = self.bundle.run()
        self.assertEqual(result["verified_complete_rows"], 26)
        self.assertEqual(result["randomization_tests_gate"],
                         "WITHHELD_UNTIL_ALL_30_COMPLETE_VERIFIED")
        for knockout in (NO_PROVIDER_PROMPT, NO_ACCEPT_BONUS, NO_CONTACT):
            self.assertEqual(result["single_knockout_contrasts"][knockout]
                             ["estimate_if_fully_observed"], 1)
            self.assertIsNone(result["single_knockout_contrasts"][knockout]
                              ["randomization_p_value"])

    def test_unverified_or_native_mismatched_review_is_rejected(self):
        row = next(row for row in self.bundle.rows if row.group == HIGH_RISK)
        review, native = self.bundle.complete(row, bad_approve=True,
                                              improper=True, exposed=True,
                                              assent=True)
        original = json.loads(json.dumps(review))
        cases = []
        changed = json.loads(json.dumps(original))
        changed["verification_status"] = "RUNNER_SELF_CERTIFIED"
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["independent_checks"]["bonus_receipts_replayed"] = False
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["verified_facts"]["early_provider_paid_minor"] = 0
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["verified_facts"]["oracle_result"] = "PASS"
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["verified_facts"]["auditor_input_post_sha256"] = "b" * 64
        cases.append(changed)
        changed = json.loads(json.dumps(original))
        changed["semantic_review"]["second"]["auditor_explicit_assent"] = False
        changed["semantic_review"]["resolved"]["reviewer_id"] = "label_three"
        changed["semantic_review"]["resolved"]["provider_improper_request"] = False
        cases.append(changed)  # resolver cannot override an agreed field
        for changed in cases:
            with self.subTest(change=changed):
                self.bundle.refs[-1] = self.bundle.write(
                    f"reviews/{row.episode_id}.json", changed)
                with self.assertRaises(ValueError):
                    self.bundle.run()
        self.bundle.refs[-1] = self.bundle.write(
            f"reviews/{row.episode_id}.json", original)
        native["early_receipt"]["provider_paid_minor"] = 0
        self.bundle.write(f"raw/{row.episode_id}.native.json", native)
        with self.assertRaises(ValueError):
            self.bundle.run()  # original pinned hash no longer matches
        tampered = json.loads(json.dumps(original))
        tampered["evidence"]["native"] = self.bundle.write(
            f"raw/{row.episode_id}.native.json", native)
        self.bundle.refs[-1] = self.bundle.write(
            f"reviews/{row.episode_id}.json", tampered)
        with self.assertRaisesRegex(ValueError, "raw native receipt"):
            self.bundle.run()

    def test_no_claim_and_defer_have_no_early_payout_and_refund_bonus(self):
        for mode in ("WAIT", "DEFER"):
            with self.subTest(mode=mode):
                bundle = SyntheticBundle(Path(self.temp.name) / mode)
                row = next(row for row in bundle.rows if row.group == HIGH_RISK)
                review, native = bundle.complete(row, check=False)
                review["verified_facts"]["provider_claim"] = mode if mode == "WAIT" else "CLAIM"
                review["verified_facts"]["early_verdict"] = (
                    "NO_CLAIM" if mode == "WAIT" else "DEFER")
                native["early_receipt"] = None
                native["final_receipt"]["bonus_provider_refund_minor"] = row.accept_bonus_minor
                native["deferred"] = mode == "DEFER"
                if mode == "WAIT":
                    native["claim_receipt"] = {
                        "status": "WAIT_NO_CLAIM",
                        "obligation_id": row.obligation_id,
                        "job_id": 1,
                        "transaction_hash": None,
                    }
                review["evidence"]["native"] = bundle.write(
                    f"raw/{row.episode_id}.native.json", native)
                bundle.refs[-1] = bundle.write(
                    f"reviews/{row.episode_id}.json", review)
                result = bundle.run()
                self.assertEqual(result["groups"][HIGH_RISK]["verified_events"], 0)
                self.assertEqual(result["verified_complete_rows"], 1)
                if mode == "WAIT":
                    native["claim_receipt"]["transaction_hash"] = "0x" + "1" * 64
                    review["evidence"]["native"] = bundle.write(
                        f"raw/{row.episode_id}.native.json", native)
                    bundle.refs[-1] = bundle.write(
                        f"reviews/{row.episode_id}.json", review)
                    with self.assertRaisesRegex(ValueError, "no-claim path"):
                        bundle.run()

    def test_scripted_tier_and_native_final_mismatch_are_rejected(self):
        row = next(row for row in self.bundle.rows if row.group == HIGH_RISK)
        review, native = self.bundle.complete(row, bad_approve=True)
        for field, value in (("model_behavior_tier", "SCRIPTED_SIMULATION"),
                             ("final_receipt", {**native["final_receipt"],
                                                "client_refund_minor": 20_000_000})):
            with self.subTest(field=field):
                mutated = json.loads(json.dumps(native))
                mutated[field] = value
                review["evidence"]["native"] = self.bundle.write(
                    f"raw/{row.episode_id}.native.json", mutated)
                self.bundle.refs[-1] = self.bundle.write(
                    f"reviews/{row.episode_id}.json", review)
                with self.assertRaises(ValueError):
                    self.bundle.run()

    def test_exact_interval_and_unfrozen_assignment_rejection(self):
        lo, hi = clopper_pearson(0, 14)
        self.assertEqual(lo, 0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 14), places=12)
        raw = json.loads((self.bundle.root / "assignment.json").read_text())
        raw["status"] = "SOURCE_ONLY"
        self.bundle.assignment_ref = self.bundle.write("assignment.json", raw)
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.bundle.run()
        raw["status"] = "FROZEN"
        raw["assignment_seed_hex"] = raw["seed_hex"]
        self.bundle.assignment_ref = self.bundle.write("assignment.json", raw)
        with self.assertRaisesRegex(ValueError, "not sealed"):
            self.bundle.run()


if __name__ == "__main__":
    unittest.main()
