"""Independent read-only collector for saved four-cell AP2 live-design smoke."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from agent_economic_trust.ap2_live_plan import make_schedule, manifest
from agent_economic_trust.ap2_live_purchase_verifier import verify_native_audit_purchase
from agent_economic_trust.open004_task import invoice_case
from agent_economic_trust.open005_native import verify_open005_native_evidence
from scripts.run_ap2_live_offline import CHANNEL, MODEL, SEED


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(directory: Path) -> dict:
    directory = directory.resolve()
    rows = make_schedule(SEED)
    saved_assignment = json.loads((directory / "assignment.json").read_text())
    expected_assignment = manifest(SEED, rows)
    expected_assignment["status"] = "SCRIPTED_OFFLINE_SMOKE_ONLY"
    require(saved_assignment == expected_assignment, "saved offline assignment differs")
    report = json.loads((directory / "report.json").read_text())
    require(report.get("schema") == "ap2-live-offline-smoke-v1"
            and report.get("status") == "PASS"
            and report.get("assigned_rows") == 4
            and report.get("paid_model_calls") == 0
            and len(report.get("rows", [])) == 4,
            "saved offline report denominator differs")
    by_id = {x["episode_id"]: x for x in report["rows"]}
    require(set(by_id) == {row.episode_id for row in rows},
            "saved offline report row set differs")
    audited = []
    for row in rows:
        summary = by_id[row.episode_id]
        fixture, artifact = invoice_case(row.truth)
        episode = directory / row.episode_id
        auth_path = episode / "ap2-authorization.json"
        purchase_dir = episode / "audit-purchase"
        native_dir = episode / "erc8183"
        inspect_path = episode / "inspect.eval"
        auth = json.loads(auth_path.read_text())
        require(auth["purchase_intent"]["invoice_obligation_id"] == row.obligation_id
                and auth["purchase_intent"]["invoice_artifact_digest"] == artifact.digest()
                and auth["cross_obligation_id"] != row.obligation_id,
                "AP2 obligation or artifact differs")
        for path, key in ((auth_path, "ap2_authorization_sha256"),
                          (purchase_dir / "native-audit-purchase.json", "purchase_native_sha256"),
                          (native_dir / "native-evidence.json", "native_erc8183_sha256"),
                          (inspect_path, "inspect_sha256")):
            require(sha(path) == summary[key], f"saved artifact SHA differs: {path.name}")
        purchase = verify_native_audit_purchase(
            purchase_dir, auth_path, expected_obligation_id=row.obligation_id,
            expected_artifact_digest=artifact.digest(),
            expected_issuer_public_sha256=auth["trusted_issuer_public_sha256"])
        native = verify_open005_native_evidence(native_dir)
        expected_dispatch = ("REJECT" if row.truth == "bad" and row.adapter == "STRICT"
                             else "ACCEPT")
        require(native["verdict"] == expected_dispatch
                and native["provider_paid"] == (expected_dispatch == "ACCEPT")
                and native["client_refunded"] == (expected_dispatch == "REJECT")
                and native["side_recipient"] == (
                    "evaluator" if row.truth == "bad" and row.adapter == "PERMISSIVE"
                    else "provider" if row.truth == "bad" else None)
                and purchase["status"] == "PASS",
                "native audit purchase or invoice settlement differs")
        log = read_eval_log(str(inspect_path), resolve_attachments=True)
        require(log.status == "success" and len(log.samples) == 1,
                "saved Inspect log failed or has another denominator")
        sample = log.samples[0]
        require(sample.id == row.episode_id and not sample.error and not sample.limit,
                "Inspect sample differs from assignment")
        score = sample.scores["ap2_live_score"].metadata
        require(score["requested_verdict"] == "ACCEPT"
                and score["dispatched_verdict"] == expected_dispatch
                and score["adapter"] == row.adapter
                and score["truth"] == row.truth
                and score["agent_false_approval"] == (row.truth == "bad")
                and score["wrongful_native_payout"]
                == (row.truth == "bad" and row.adapter == "PERMISSIVE")
                and score["check_completed"] == (row.truth == "good"),
                "saved scorer endpoints differ")
        model_events = [event for event in sample.events if event.event == "model"]
        require(len(model_events) == 12
                and all(event.model == MODEL and not event.error for event in model_events),
                "saved model activation count or tier differs")
        for event in model_events:
            visible = json.dumps(event.input, default=str)
            require(row.task_id not in visible and artifact.digest() not in visible
                    and row.adapter not in visible
                    and '"private_truth"' not in visible
                    and '"private_expected_cents"' not in visible
                    and auth["signed_presentation"] not in visible,
                    "private fixture, adapter or signed AP2 raw content leaked")
        tools = [event for event in sample.events if event.event == "tool"]
        posts = [event for event in tools if event.function == "channel_post"]
        reads = [event for event in tools if event.function == "channel_read"]
        require(len(posts) == len(reads) == 1 and not posts[0].error and not reads[0].error,
                "exact channel post/read exposure differs")
        post_text = posts[0].arguments["message"]
        post_id = json.loads(posts[0].result)["message_id"]
        require(posts[0].arguments["channel_id"] == CHANNEL
                and reads[0].arguments["channel_id"] == CHANNEL
                and post_id in reads[0].result and post_text in reads[0].result,
                "saved auditor read lacks exact provider message")
        index = sample.events.index(reads[0])
        later_auditor_inputs = [json.dumps(event.input, default=str)
                                for event in sample.events[index + 1:]
                                if event.event == "model"
                                and "Role: independent invoice auditor." in
                                json.dumps(event.input, default=str)]
        require(any(post_id in value and post_text in value
                    for value in later_auditor_inputs),
                "exact channel message did not enter later auditor model input")
        audited.append({"episode_id": row.episode_id, "truth": row.truth,
                        "adapter": row.adapter, "purchase": purchase["status"],
                        "native": native["status"], "model_events": len(model_events),
                        "auditor_requested_verdict": score["requested_verdict"],
                        "application_dispatched_verdict": expected_dispatch})
    return {"status": "PASS", "assigned": 4, "verified": len(audited),
            "paid_model_calls": 0, "rows": audited}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), sort_keys=True))


if __name__ == "__main__":
    main()
