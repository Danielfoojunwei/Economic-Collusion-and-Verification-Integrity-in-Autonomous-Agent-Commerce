"""Local ERC-8183 job and fee remain live through ORBIT verdict controls."""

from __future__ import annotations

import os
from pathlib import Path
import json
import shutil
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    audit_independent_pair_log, make_assignments, task_for_trial,
)
from agent_economic_trust.w10_live_native import LiveNativeTrial  # noqa: E402
from agent_economic_trust.w10_factorial_remote import (  # noqa: E402
    _decision_signature, _score_trial,
)
from agent_economic_trust.w10_factorial_reporting import export_factorial_trial  # noqa: E402
from tests.test_protected_receipts import scripted_model  # noqa: E402


ROWS = make_assignments("04" * 32)


class W10LiveNativeTests(unittest.TestCase):
    def test_native_fee_and_erc8183_payout_follow_isolated_scripted_verdicts(self):
        with tempfile.TemporaryDirectory(prefix="w10-live-native-", dir="/workspace") as directory:
            root = Path(directory)
            for truth, r, policy, expected_verdict, expected_paid in (
                ("good", 0, "check", "ACCEPT", True),
                ("bad", 1, "check", "REJECT", False),
                ("bad", 0, "accept", "ACCEPT", True),
            ):
                trial = next(row for row in ROWS
                             if row.fixture_id == f"delivery-{truth}"
                             and row.r == r and row.s == 0 and row.p == 0)
                name = f"{truth}-R{r}-{policy}"
                with LiveNativeTrial(trial, root / name / "native",
                                     pair_index=ROWS.index(trial),
                                     assignment_manifest_sha256="a" * 64) as native:
                    funding = native(trial)
                    self.assertEqual(funding.payer_role, "worker" if r else "client")
                    self.assertEqual(native.helper.job(native.job_id)["status"], "Funded")
                    [log] = inspect_eval(
                        task_for_trial(trial, verify_funding=native, scheduler_seconds=60),
                        model=scripted_model(policy),
                        log_dir=str(root / name / "inspect"),
                        display="none", log_realtime=False, max_retries=0,
                    )
                    self.assertEqual(log.status, "success", log.error)
                    native_log_path = root / name / "saved.eval"
                    native_log_path.write_bytes(Path(log.location).read_bytes())
                    saved = read_eval_log(str(native_log_path), resolve_attachments=True)
                    self.assertEqual(_decision_signature(saved), _decision_signature(log))
                    self.assertEqual(audit_independent_pair_log(saved)["channel_isolation_audit"],
                                     "PASS")
                    scored = _score_trial(
                        saved, trial, "protected-receipt-control",
                        expected_log_model="mockllm/protected-receipt-control",
                    )
                    score = saved.samples[0].scores["protected_receipt_score"].metadata
                    self.assertEqual(score["V"], expected_verdict)
                    self.assertEqual(scored["verdict"], expected_verdict)
                    self.assertEqual(score["oracle_status"], "PASS" if truth == "good" else "FAIL")
                    settlement = native.settle_task(score["V"], trial.artifact_digest)
                    self.assertEqual(settlement["provider_paid"], expected_paid)
                    self.assertEqual(settlement["job_status"],
                                     "Completed" if expected_paid else "Rejected")
                    self.assertEqual(settlement["before"]["balances_minor_units"]["evaluator"], 2_000_000)
                    self.assertEqual(settlement["after"]["balances_minor_units"]["evaluator"], 2_000_000)
                    if truth == "bad" and policy == "accept":
                        self.assertTrue(score["false_approval"])
                        self.assertEqual(settlement["provider_payout_minor_units"],
                                         20_000_000)
                self.assertTrue((root / name / "native" / "evidence.json").is_file())
                evidence = json.loads((root / name / "native" / "evidence.json").read_text())
                self.assertEqual(evidence["fee_terms"]["conditional_evaluator_fee_bps"], 0)
                self.assertEqual(evidence["fee_terms"]["platform_fee_bps"], 0)
                self.assertEqual(set(evidence["contracts"]),
                                 {"MockUSDC", "ERC8183", "ERC1967Proxy"})
                if truth == "bad" and r == 1:
                    output = root / name
                    shutil.copyfile(output / "saved.eval", output / "inspect.eval")
                    shutil.copyfile(output / "native" / "evidence.json",
                                    output / "native_evidence.json")
                    import hashlib
                    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
                    record = {
                        "trial_id": trial.trial_id,
                        "assignment_manifest_sha256": "a" * 64,
                        "status": "COMPLETE", "verdict": scored["verdict"],
                        "checked": scored["checked"],
                        "check_spent_units": scored["check_spent_units"],
                        "false_approval": scored["false_approval"],
                        "payment_status": "PAID" if settlement["provider_paid"] else "NOT_PAID",
                        "provider_payout_minor_units": settlement["provider_payout_minor_units"],
                        "channel_isolation_audit": "PASS",
                        "native_inspect_sha256": digest(output / "inspect.eval"),
                        "native_payment_sha256": digest(output / "native_evidence.json"),
                        "model_cost_usd_estimate": "0",
                        "ledger_run_id": "scripted-native-control",
                    }
                    (output / "trial_record.json").write_text(json.dumps(record) + "\n")
                    exported = export_factorial_trial(
                        output, trial=trial, record=record,
                        saved_log=read_eval_log(str(output / "inspect.eval"),
                                                resolve_attachments=True),
                        native_data=json.loads((output / "native_evidence.json").read_text()),
                        model_id="mockllm/protected-receipt-control",
                        model_behavior_tier="SCRIPTED",
                    )
                    self.assertGreater(exported["events"], 8)
                    self.assertEqual(exported["outcomes"], 1)


if __name__ == "__main__":
    unittest.main()
