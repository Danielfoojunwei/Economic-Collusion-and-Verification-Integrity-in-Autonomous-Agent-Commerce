#!/usr/bin/env python3
"""Read-only provider-export match for the stopped W11 session.

This command reads the user-supplied OpenRouter Explore CSVs, the original
Inspect archive, frozen assignment, STOPPED record, and hash-chained ledger.
It writes only a new, deterministic evidence report; it never settles a run.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))

from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402


EVIDENCE_DIR = ROOT / "artifacts/budget/provider-reconciliation-001"
EPISODE_DIR = (ROOT / "artifacts/gates/W11_LIVE/market-runs-001/"
               "market-acb40c26ae8838c87fd3/episodes/episode-de0a57bf5b8ca2bbe753")
PLAN_DIR = ROOT / "artifacts/gates/W11_DESIGN/assignment-006"
PREIMAGE = (ROOT / "artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006/"
            "src/agent_economic_trust/w11_market_remote.py")
LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
FROZEN_LEDGER = EVIDENCE_DIR / "openrouter-ledger.pre-settlement.jsonl"
FROZEN_LEDGER_SHA = "9edd923e2ca4cfb329b326ac0f4e743df6a5db4101d0d85ff0fbe7595e55c4ed"
FROZEN_ANCHOR_SHA = "506764391cc43ce8117268c9e4b4ade1ef2fb9e671f64d1a979342a21e4de017"
CSV_HASHES = {
    "request_count_hourly.csv": "036a3624757588dea51a5dc2d690266a9353d11d7b1cf99ac23c020901d8b7b7",
    "usage_count_hourly.csv": "8be54addbc06115536f98479ba7874f6a5109898a17fe5d2578e88019c680d82",
    "usage_by_session.csv": "98ffde82372cf346e6b3b52a98745bf329c71b90e094fb91e2f65e5ef960f27a",
}
STOPPED_SHA = "556b933b2eadd6dbafe41a4bbb089516533b02df796e4d9d027663f50b3da1ae"
INSPECT_SHA = "aa3f66f10f4f9a1165f9990687a7f52963d6c855dc340160aa06dab59efb04cb"
ASSIGNMENT_SHA = "ae037b6df7b0e0130578c6f6f7fe210a23690ad653ee54d0877315173ee9f0d9"
PREIMAGE_SHA = "294e50ddfc3628ba00f9405215ddbe06d45611d4cd95af7294f5d01ceffb2214"
FORENSIC_SHA = "3e24e1cef1665d3de61e12fb5ec967c4ad3a7dc91b7f84a062dae28a144b8643"
LEDGER_HEAD = "6c7220cbf39b8a433645868f70ce175526d4a762e4edc6e5d0e77e8807f40f44"
SESSION_ID = "X3NZV22BrmsPPw3eFEjYkb"
RUN_ID = "w11-market-ae037b6df7b0-episode-de0a57bf5b8ca2bbe753"
HOUR = "2026-10-15 07:00:00"
PROVIDER_MODEL = "GPT-5.6 Sol"
INSPECT_MODEL = "openrouter/openai/gpt-5.6-sol"
UNDERLYING_MODEL = "openai/gpt-5.6-sol"
SESSION_USAGE = Decimal("0.037002")
SESSION_REQUESTS = 8
AGGREGATE_TOLERANCE = Decimal("0.000000000001")


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _pinned_bytes(path: Path, expected: str) -> bytes:
    payload = path.read_bytes()
    if _digest(payload) != expected:
        raise ValueError(f"pinned input changed: {path.name}")
    return payload


def _rows(payload: bytes, fields: tuple[str, ...]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    if tuple(reader.fieldnames or ()) != fields:
        raise ValueError("provider CSV columns differ from expected Explore export")
    result = list(reader)
    if not result or any(None in row or any(value is None for value in row.values()) for row in result):
        raise ValueError("provider CSV has empty or malformed rows")
    return result


def _amount(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("provider CSV has invalid usage amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("provider CSV has invalid usage amount")
    return amount


def _count(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("provider CSV has invalid request count")
    return int(value)


def validate_csv_tables(count_csv: bytes, hourly_csv: bytes,
                        session_csv: bytes) -> dict:
    """Cross-check three independent Explore groupings without trusting headers alone."""
    counts = _rows(count_csv, ("date__hour", "model", "request_count"))
    hourly = _rows(hourly_csv, ("date__hour", "model", "total_usage", "request_count"))
    sessions = _rows(session_csv, ("created_at__hour", "session_id", "total_usage", "request_count"))
    by_hour = {}
    for row in counts:
        key = (row["date__hour"], row["model"])
        if key in by_hour or row["model"] != PROVIDER_MODEL:
            raise ValueError("provider count table has duplicate hour or unexpected model")
        by_hour[key] = _count(row["request_count"])
    usage_by_hour = {}
    for row in hourly:
        key = (row["date__hour"], row["model"])
        if key in usage_by_hour or row["model"] != PROVIDER_MODEL:
            raise ValueError("provider usage table has duplicate hour or unexpected model")
        if key not in by_hour or by_hour[key] != _count(row["request_count"]):
            raise ValueError("hourly provider request counts disagree")
        usage_by_hour[key] = _amount(row["total_usage"])
    if set(by_hour) != set(usage_by_hour) or (HOUR, PROVIDER_MODEL) not in by_hour:
        raise ValueError("hourly provider groups disagree or target hour is absent")
    session_sums: dict[str, Decimal] = {}
    explicit_counts: dict[str, int] = {}
    matching = []
    session_keys = set()
    for row in sessions:
        hour, sid = row["created_at__hour"], row["session_id"]
        if (hour, sid) in session_keys or not sid or (hour, PROVIDER_MODEL) not in by_hour:
            raise ValueError("provider session table has duplicate or unexpected group")
        session_keys.add((hour, sid))
        session_sums[hour] = session_sums.get(hour, Decimal(0)) + _amount(row["total_usage"])
        if sid == "Other":
            if row["request_count"]:
                raise ValueError("provider Other row unexpectedly has a request count")
        else:
            count = _count(row["request_count"])
            explicit_counts[hour] = explicit_counts.get(hour, 0) + count
        if sid == SESSION_ID:
            matching.append(row)
    if len(matching) != 1:
        raise ValueError("stopped Inspect UUID does not have exactly one provider session")
    target = matching[0]
    if (target["created_at__hour"] != HOUR
            or _count(target["request_count"]) != SESSION_REQUESTS
            or _amount(target["total_usage"]) != SESSION_USAGE):
        raise ValueError("stopped provider session does not match count/hour/usage")
    for (hour, _model), hourly_usage in usage_by_hour.items():
        if hour not in session_sums or abs(session_sums[hour] - hourly_usage) > AGGREGATE_TOLERANCE:
            raise ValueError("provider session usage does not sum to model-hour usage")
        if explicit_counts.get(hour, 0) > by_hour[(hour, PROVIDER_MODEL)]:
            raise ValueError("provider named-session counts exceed hour total")
    return {
        "hourly_request_counts": {hour: count for (hour, _), count in sorted(by_hour.items())},
        "hourly_usage_usd": {hour: format(amount, "f") for (hour, _), amount in sorted(usage_by_hour.items())},
        "session_id": SESSION_ID,
        "target_hour_utc": HOUR,
        "target_request_count": SESSION_REQUESTS,
        "target_total_usage_usd": format(SESSION_USAGE, "f"),
        "target_hour_session_sum_usd": format(session_sums[HOUR], "f"),
    }


def validate_ledger_prestate(snapshot: dict) -> dict:
    """Refuse to reconcile a different or already settled budget state."""
    run = snapshot.get("runs", {}).get(RUN_ID)
    if (snapshot.get("seq") != 88 or snapshot.get("last_hash") != LEDGER_HEAD
            or snapshot.get("cap_usd") != "20"
            or snapshot.get("settled_spent_usd") != "2.54464"
            or snapshot.get("reserved_usd") != "4.25984"
            or snapshot.get("blocked") is not True
            or snapshot.get("unknown_run_ids") != [RUN_ID]
            or not isinstance(run, dict) or run.get("status") != "UNKNOWN"
            or run.get("reserved_usd") != "4.25984"
            or run.get("metadata") != {
                "assignment_sha": ASSIGNMENT_SHA,
                "episode_id": "episode-de0a57bf5b8ca2bbe753",
                "market_id": "market-acb40c26ae8838c87fd3",
                "model_id": UNDERLYING_MODEL,
            }):
        raise ValueError("ledger is not the original blocked UNKNOWN reservation")
    return {
        "seq": snapshot["seq"], "head_sha256": snapshot["last_hash"],
        "cap_usd": snapshot["cap_usd"],
        "settled_spent_usd": snapshot["settled_spent_usd"],
        "reserved_usd": snapshot["reserved_usd"],
        "blocked": snapshot["blocked"], "run_id": RUN_ID,
        "run_status": run["status"], "run_reservation_usd": run["reserved_usd"],
    }


def validate_inspect_session(sample, inspect_model: str) -> dict:
    """Tie one saved Inspect session's model calls and times to the CSV hour."""
    events = [event for event in sample.events or [] if event.event == "model"]
    if inspect_model != INSPECT_MODEL or sample.uuid != SESSION_ID or len(events) != SESSION_REQUESTS:
        raise ValueError("Inspect model, sample UUID, or model-call count differs from provider session")
    hour_start = datetime.strptime(HOUR, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    hour_end = hour_start + timedelta(hours=1)
    started = datetime.fromisoformat(sample.started_at.replace("Z", "+00:00"))
    completed = datetime.fromisoformat(sample.completed_at.replace("Z", "+00:00"))
    if not (hour_start <= started <= completed < hour_end):
        raise ValueError("Inspect sample occurred outside provider session's UTC hour")
    for event in events:
        if event.model != INSPECT_MODEL or event.output.model != UNDERLYING_MODEL:
            raise ValueError("Inspect model event differs from provider model")
        timestamp = event.timestamp
        if timestamp.tzinfo is None or not (started <= timestamp <= completed):
            raise ValueError("Inspect model event occurred outside sample window")
    return {
        "inspect_sample_uuid": sample.uuid, "inspect_model": inspect_model,
        "underlying_model": UNDERLYING_MODEL,
        "inspect_started_at_utc": started.isoformat(),
        "inspect_completed_at_utc": completed.isoformat(),
        "model_events": len(events),
    }


def verify(*, csv_dir: Path = EVIDENCE_DIR, log_path: Path = EPISODE_DIR / "inspect.eval",
           stopped_path: Path = EPISODE_DIR / "STOPPED.json",
           plan_path: Path = PLAN_DIR / "assignment_manifest.json",
           preimage_path: Path = PREIMAGE, ledger_path: Path = FROZEN_LEDGER,
           forensic_path: Path = EVIDENCE_DIR / "pre_settlement_forensic.json") -> dict:
    originals = {name: _pinned_bytes(csv_dir / name, digest)
                 for name, digest in CSV_HASHES.items()}
    tables = validate_csv_tables(originals["request_count_hourly.csv"],
                                 originals["usage_count_hourly.csv"],
                                 originals["usage_by_session.csv"])
    stopped = json.loads(_pinned_bytes(stopped_path, STOPPED_SHA))
    if stopped != {
        "budget_state": "UNKNOWN", "episode_id": "episode-de0a57bf5b8ca2bbe753",
        "error_type": "RemoteBoundaryError", "market_id": "market-acb40c26ae8838c87fd3",
        "model_calls": SESSION_REQUESTS, "native_inspect_sha256": INSPECT_SHA,
        "native_payment_sha256": None, "stage": "provider_request",
    }:
        raise ValueError("saved STOPPED state differs from target eight-call run")
    _pinned_bytes(log_path, INSPECT_SHA)
    log = read_eval_log(str(log_path), resolve_attachments=False)
    if log.status != "success" or log.eval.model != INSPECT_MODEL or len(log.samples or []) != 1:
        raise ValueError("saved Inspect archive has wrong status, model, or sample count")
    sample = log.samples[0]
    inspect = validate_inspect_session(sample, log.eval.model)
    plan = json.loads(_pinned_bytes(plan_path, ASSIGNMENT_SHA))
    if plan["source_sha256"]["src/agent_economic_trust/w11_market_remote.py"] != PREIMAGE_SHA:
        raise ValueError("frozen assignment does not pin original W11 runner")
    _pinned_bytes(preimage_path, PREIMAGE_SHA)
    forensic = json.loads(_pinned_bytes(forensic_path, FORENSIC_SHA))
    if (forensic.get("checked") is not True or forensic.get("paid_model_calls") != 0
            or forensic.get("mutation_count") != 0
            or forensic.get("model_calls") != SESSION_REQUESTS
            or forensic.get("native_status") != "OPEN"
            or forensic.get("ledger_status") != "UNKNOWN"
            or forensic.get("native_inspect_sha256") != INSPECT_SHA
            or forensic.get("original_stopped_sha256") != STOPPED_SHA
            or forensic.get("assignment_manifest_sha256") != ASSIGNMENT_SHA
            or forensic.get("historical_source_preimage_sha256") != PREIMAGE_SHA):
        raise ValueError("pre-settlement structural forensic check differs")
    _pinned_bytes(ledger_path, FROZEN_LEDGER_SHA)
    _pinned_bytes(ledger_path.with_name(ledger_path.name + ".anchor"), FROZEN_ANCHOR_SHA)
    ledger = validate_ledger_prestate(BudgetLedger(ledger_path).snapshot())
    ledger["frozen_ledger_sha256"] = FROZEN_LEDGER_SHA
    ledger["frozen_anchor_sha256"] = FROZEN_ANCHOR_SHA
    return {
        "schema": "w11-provider-session-reconciliation-v1",
        "result": "MATCHED_PROVIDER_SESSION",
        "provider_export_kind": "user_uploaded_openrouter_explore_csv",
        "csv_sha256": dict(sorted(CSV_HASHES.items())),
        "provider_tables": tables,
        "saved_run": {
            "inspect_sha256": INSPECT_SHA, "stopped_sha256": STOPPED_SHA,
            "assignment_manifest_sha256": ASSIGNMENT_SHA,
            "frozen_runner_preimage_sha256": PREIMAGE_SHA,
            "pre_settlement_forensic_sha256": FORENSIC_SHA,
            **inspect,
            "stop_stage": stopped["stage"],
        },
        "ledger_prestate": ledger,
        "settlement_candidate_usd": format(SESSION_USAGE, "f"),
        "settlement_candidate_basis": "provider Explore total_usage grouped by exact Inspect sample UUID",
        "limitations": [
            "The user-supplied CSV export is not cryptographically signed by OpenRouter.",
            "The export is a session aggregate; it does not contain eight individual request IDs or costs.",
            "The original W11 episode remains STOPPED and must not be counted as a completed experimental round.",
        ],
        "paid_model_calls": 0,
        "ledger_mutations": 0,
    }


def _report(evidence: dict) -> str:
    row = evidence["provider_tables"]
    run = evidence["saved_run"]
    return ("# W11 stopped session: provider export reconciliation\n\n"
            "Result: **matched provider session; ledger unchanged**. The user-supplied OpenRouter "
            "Explore export reports **USD 0.037002** total usage for one session with eight requests. "
            "This is a settlement candidate for independent review, not a ledger settlement or a completed W11 round.\n\n"
            f"- Provider session ID and Inspect sample UUID: `{row['session_id']}`.\n"
            f"- Model: `GPT-5.6 Sol` in the provider hour table, `{run['inspect_model']}` "
            f"in the saved log (`{run['underlying_model']}` underlying).\n"
            f"- Provider group: {row['target_hour_utc']} UTC, eight requests, "
            f"USD {row['target_total_usage_usd']}. Saved sample: "
            f"{run['inspect_started_at_utc']} to {run['inspect_completed_at_utc']}, "
            f"{run['model_events']} model events.\n"
            "- Both hourly CSVs agree on request counts; the provider session usage sums "
            "to each model-hour usage total within CSV floating-point precision.\n"
            f"- Original STOPPED SHA-256 `{STOPPED_SHA}`; Inspect SHA-256 `{INSPECT_SHA}`; "
            f"assignment SHA-256 `{ASSIGNMENT_SHA}`; archived frozen runner SHA-256 `{PREIMAGE_SHA}`.\n"
            f"- Fresh, read-only structural forensic preflight SHA-256 `{FORENSIC_SHA}`: "
            "eight calls, UNKNOWN reservation, native job OPEN, zero ledger/native mutations.\n"
            f"- Frozen copy of the original hash-chained ledger head `{LEDGER_HEAD}` (seq 88): "
            "UNKNOWN, USD 4.25984 reserved, blocked. The ledger copy SHA-256 is "
            f"`{FROZEN_LEDGER_SHA}`; anchor SHA-256 is `{FROZEN_ANCHOR_SHA}`. "
            "No original budget mutation was made.\n\n"
            "CSV and blocked-ledger originals are copied byte-for-byte beside this report. CSV SHA-256 values "
            "are in `evidence.json`; run "
            "`/workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_w11_provider_reconciliation.py --verify-only` "
            "to reproduce the checks without writing an artifact.\n\n"
            "**Limits:** The CSVs are a user-supplied, unsigned provider export and show only a "
            "session total, not eight request-level charges. The exact Inspect UUID, eight-call count, "
            "matching model and hour, original archive hash, and independent hourly totals support "
            "attributing the USD 0.037002 to this stopped session. The W11 experimental assignment "
            "remains incomplete.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="check inputs without writing evidence")
    args = parser.parse_args()
    evidence = verify()
    if not args.verify_only:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "evidence.json").write_text(
            json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (EVIDENCE_DIR / "report.md").write_text(_report(evidence), encoding="utf-8")
    print(f"MATCHED_PROVIDER_SESSION USD {evidence['settlement_candidate_usd']} "
          f"ledger_mutations={evidence['ledger_mutations']}")


if __name__ == "__main__":
    main()
