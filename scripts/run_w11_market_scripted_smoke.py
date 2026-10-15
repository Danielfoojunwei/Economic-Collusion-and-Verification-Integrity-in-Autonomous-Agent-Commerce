#!/usr/bin/env python3
"""Run local scripted W11 market controls with real persistent ERC-8183 jobs."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.w11_market_native import (  # noqa: E402
    LiveNativeMarket, verify_market_evidence,
)
from agent_economic_trust.w11_market_plan import (  # noqa: E402
    VerifiedHistoryEntry, make_market_schedule,
)
from agent_economic_trust.w11_market_reporting import export_market_episode  # noqa: E402
from agent_economic_trust.w11_market_task import (  # noqa: E402
    assigned_message, audit_saved_market_log, build_market_task,
)
from tests.test_w11_market_task import model_for  # noqa: E402


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def run(plan_dir: Path, output: Path) -> dict:
    import importlib.util

    spec = importlib.util.spec_from_file_location("w11_freeze", ROOT / "scripts/freeze_w11_market.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.verify(plan_dir)
    frozen = json.loads((plan_dir / "assignment_manifest.json").read_bytes())
    assignment_sha = sha(plan_dir / "assignment_manifest.json")
    seed = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    rows = make_market_schedule(seed,
                                blocks=len({row["block_id"] for row in frozen["rows"]}),
                                r_values=tuple(sorted({row["r"] for row in frozen["rows"]})))
    chosen = []
    for arm, r, count in (("FRESH_NONE", 1, 2), ("REPEAT_DIRECT", 1, 4),
                          ("REPEAT_DIRECT", 0, 4)):
        market_id = next(row.market_id for row in rows if row.arm == arm and row.r == r)
        chosen.append((market_id, sorted((row for row in rows if row.market_id == market_id),
                                         key=lambda row: row.round_index)[:count]))
    if output.exists():
        raise FileExistsError("scripted market smoke output already exists")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    results = []
    for market_id, market_rows in chosen:
        market_dir = output / market_id
        market_dir.mkdir()
        entries = {}
        with LiveNativeMarket(market_id, market_dir / "native", r=market_rows[0].r,
                              assignment_manifest_sha256=assignment_sha) as native:
            for row in market_rows:
                altered_promise = (row.r == 0 and row.offer_variant == "AUTHORED_UNTRUSTED_PROMISE")
                episode_dir = market_dir / "episodes" / row.episode_id
                episode_dir.mkdir(parents=True)
                opened = native.open_round(
                    episode_id=row.episode_id, obligation_id=row.obligation_id,
                    artifact_digest=row.artifact_digest,
                    public_task_digest=row.public_task_digest,
                    provider_id=row.provider_id, auditor_id=row.verifier_id,
                )
                task = build_market_task(
                    row, entries=entries, fee_tier="NATIVE_LOCAL_VERIFIED",
                    fee_receipt_sha256=opened["fee_receipt_sha256"],
                )
                [log] = inspect_eval(
                    task, model=model_for(
                        row, post_override="Provider says: please review the receipt."
                        if altered_promise else None),
                    log_dir=str(episode_dir / "temporary-inspect"),
                    display="none", log_realtime=False, max_retries=0,
                )
                if log.status != "success":
                    raise ValueError("scripted market ORBIT round did not complete")
                saved_path = episode_dir / "inspect.eval"
                shutil.copyfile(log.location, saved_path)
                saved = read_eval_log(str(saved_path), resolve_attachments=True)
                audit = audit_saved_market_log(
                    saved, row, entries=entries,
                    expected_message=assigned_message(row),
                    require_delivery=row.communication_mode == "DIRECT" and not altered_promise,
                )
                if altered_promise and (audit["assigned_message_posted"]
                                        or audit["assigned_message_read"]):
                    raise ValueError("altered assigned promise falsely counted as exposure")
                score = saved.samples[0].scores["protected_receipt_score"].metadata
                verdict = score["V"]
                if verdict not in {"ACCEPT", "REJECT"}:
                    raise ValueError("scripted auditor did not issue a verdict")
                native.verify_open_round(row.obligation_id)
                payout = native.settle_round(row.obligation_id, verdict,
                                             row.artifact_digest)
                native_path = episode_dir / "native_evidence.json"
                shutil.copyfile(market_dir / "native" / "evidence.json", native_path)
                verify_market_evidence(native_path)
                record = {
                    "status": "COMPLETE", "market_id": row.market_id,
                    "episode_id": row.episode_id, "round_index": row.round_index,
                    "arm": row.arm, "R": row.r,
                    "assignment_manifest_sha256": assignment_sha,
                    "offer_variant": row.offer_variant,
                    "model_tier": "SCRIPTED", "payment_tier": "NATIVE_LOCAL_CHAIN",
                    "verdict": verdict, "checked": bool(score["Q"]),
                    "check_spent_units": score["check_spent_units"],
                    "oracle_truth": score["Y"],
                    "payment_status": "PAID" if payout["provider_paid"] else "NOT_PAID",
                    "provider_payout_minor_units": payout["provider_payout_minor_units"],
                    "channel_audit": audit,
                    "native_inspect_sha256": sha(saved_path),
                    "native_payment_sha256": sha(native_path),
                    "model_calls": 0, "model_cost_usd_estimate": "0",
                    "ledger_run_id": "w11-scripted-" + row.episode_id,
                    "ledger_last_hash": None,
                    "source_sha256": frozen["source_sha256"],
                }
                (episode_dir / "episode_record.json").write_text(
                    json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                exported = export_market_episode(
                    episode_dir, row=row, saved_log=saved,
                    native_data=json.loads(native_path.read_bytes()), record=record,
                    assignment_manifest_sha256=assignment_sha,
                    model_behavior_tier="SCRIPTED", model_id="mockllm/w11-scripted-capability-control",
                    source_sha256=frozen["source_sha256"],
                )
                if altered_promise:
                    events = [json.loads(line) for line in (episode_dir / "events.jsonl").read_text().splitlines()]
                    sent = [event for event in events if event["event_type"] == "COMMUNICATION_SENT"]
                    read = [event for event in events if event["event_type"] == "COMMUNICATION_READ"]
                    with (episode_dir / "episode_outcomes.csv").open(newline="") as outcome_file:
                        outcomes = list(csv.DictReader(outcome_file))
                    if (len(sent) != 1 or len(read) != 1 or len(outcomes) != 1
                            or sent[0]["payload"]["actual_message_classification"] != "OTHER_UNTRUSTED_MESSAGE"
                            or sent[0]["payload"]["assigned_message_posted"] is not False
                            or read[0]["payload"]["assigned_message_read"] is not False
                            or outcomes[0]["offer_variant"] != "AUTHORED_UNTRUSTED_PROMISE"
                            or outcomes[0]["direct_message_read"] != "False"):
                        raise ValueError("negative-control export lost assignment or falsely counted exposure")
                entries[row.episode_id] = VerifiedHistoryEntry(
                    market_id=row.market_id, episode_id=row.episode_id,
                    round_index=row.round_index, provider_id=row.provider_id,
                    verifier_id=row.verifier_id, task_id=row.task_id,
                    bid_fee_minor_units=None,
                    audit_fee_payer_id=row.provider_id if row.r else "client",
                    audit_fee_minor_units=row.audit_fee_minor_units,
                    verdict=verdict,
                    provider_payout_minor_units=payout["provider_payout_minor_units"],
                    payment_status=record["payment_status"],
                    native_evidence_sha256=sha(native_path),
                    inspect_eval_sha256=sha(saved_path),
                    event_export_sha256=sha(episode_dir / "events.jsonl"),
                    verifier_status="PASS",
                )
                results.append({"market_id": market_id, "episode_id": row.episode_id,
                                "arm": row.arm, "R": row.r,
                                "round_index": row.round_index,
                                "offer_variant": row.offer_variant,
                                "scripted_altered_promise": altered_promise,
                                "channel_audit": audit, "verdict": verdict,
                                "payment_status": record["payment_status"],
                                "native_evidence_sha256": sha(native_path),
                                "run_manifest_sha256": exported["run_manifest_sha256"]})
    report = {"schema": "w11-scripted-market-smoke-v1", "assignment_sha256": assignment_sha,
              "model_behavior_tier": "SCRIPTED", "payment_tier": "NATIVE_LOCAL_CHAIN",
              "model_calls": 0, "project_ledger_changed": False,
              "episodes": results,
              "assigned_promise_denominator": sum(
                  item["offer_variant"] == "AUTHORED_UNTRUSTED_PROMISE" for item in results),
              "observed_assigned_promise_exposures": sum(
                  item["offer_variant"] == "AUTHORED_UNTRUSTED_PROMISE"
                  and item["channel_audit"]["assigned_message_read"] for item in results),
              "altered_promise_control_count": sum(
                  item["scripted_altered_promise"] for item in results)}
    if (report["assigned_promise_denominator"] != 2
            or report["observed_assigned_promise_exposures"] != 1
            or report["altered_promise_control_count"] != 1):
        raise ValueError("scripted direct-promise control denominator differs from plan")
    (output / "summary.json").write_text(json.dumps(report, sort_keys=True) + "\n")
    return {"episodes": len(results), "direct_messages_read": sum(
        item["channel_audit"]["assigned_message_read"] for item in results),
        "assigned_promise_denominator": report["assigned_promise_denominator"],
        "observed_assigned_promise_exposures": report["observed_assigned_promise_exposures"],
        "summary_sha256": sha(output / "summary.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
