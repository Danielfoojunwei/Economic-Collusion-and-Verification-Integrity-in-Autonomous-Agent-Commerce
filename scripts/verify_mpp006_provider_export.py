"""Read-only cross-check of the owner-exported MPP006 billing CSV.

This verifies session/count matches and reports the limits of the export. It
does not call OpenRouter, mutate the budget ledger, or assign a failed-call
charge.
"""

from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from inspect_ai.log import read_eval_log


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/budget/provider-reconciliation-mpp006-001"
CSV = EVIDENCE / "usage_by_session_hourly.csv"
ACCOUNT = EVIDENCE / "account_usage_readonly.json"
CSV_SHA256 = "29481fb76fd22888d810ea58d9bc42ce624bc935e842b54ea2030f28c158ff39"
TARGET_HOUR = "2026-10-15 13:00:00"
COMPLETED = (
    ("OPEN006", "open006-45d3e5f5c000f353052ae159", "OPEN006/runs-invoice-001"),
    ("OPEN006", "open006-c76de603251a134fba5c6868", "OPEN006/runs-invoice-001"),
    ("OPEN006", "open006-d465a82d1e64e0b3f5eccef2", "OPEN006/runs-invoice-001"),
    ("MPP006", "mpp006-dcf4a781b0982260ecfe3012", "MPP006/runs-mixed-001"),
)
STOPPED = "mpp006-bc092a2baae1584874c4f308"


def inspect_sample(subdir: str, episode_id: str):
    path = ROOT / "artifacts/gates" / subdir / "episodes" / episode_id / "inspect.eval"
    log = read_eval_log(str(path))
    if len(log.samples or []) != 1:
        raise ValueError(f"expected one Inspect sample: {episode_id}")
    return log.samples[0], hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict:
    raw = CSV.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CSV_SHA256:
        raise ValueError("owner CSV bytes differ from frozen SHA-256")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    if not rows or set(rows[0]) != {
        "created_at__hour", "session_id", "total_usage", "request_count"
    }:
        raise ValueError("provider CSV columns differ")
    target = [row for row in rows if row["created_at__hour"] == TARGET_HOUR]
    if len(target) != 4:
        raise ValueError("13:00 UTC export is not the four-session snapshot")
    by_session = {row["session_id"]: row for row in target}
    if len(by_session) != 4:
        raise ValueError("duplicate provider session")

    matches = []
    for study, episode_id, subdir in COMPLETED:
        sample, log_sha = inspect_sample(subdir, episode_id)
        row = by_session.get(sample.uuid)
        if row is None:
            raise ValueError(f"completed session not in provider CSV: {episode_id}")
        model_events = sum(getattr(event, "event", None) == "model" for event in sample.events)
        if model_events != int(row["request_count"]):
            raise ValueError(f"provider/Inspect request-count mismatch: {episode_id}")
        if not sample.started_at.startswith("2026-10-15T13:"):
            raise ValueError(f"Inspect episode outside provider hour: {episode_id}")
        matches.append({
            "study": study,
            "episode_id": episode_id,
            "sample_uuid": sample.uuid,
            "started_at_utc": sample.started_at,
            "completed_at_utc": sample.completed_at,
            "inspect_sha256": log_sha,
            "inspect_model_events": model_events,
            "provider_request_count": int(row["request_count"]),
            "provider_session_spend_usd": str(Decimal(row["total_usage"])),
        })
    if set(by_session) != {match["sample_uuid"] for match in matches}:
        raise ValueError("13:00 UTC export contains an unmatched session")

    failed, failed_sha = inspect_sample("MPP006/runs-mixed-001", STOPPED)
    stopped_path = (
        ROOT / "artifacts/gates/MPP006/runs-mixed-001/episodes" / STOPPED / "STOPPED.json"
    )
    stopped_raw = stopped_path.read_bytes()
    stopped = json.loads(stopped_raw)
    if (stopped["budget_state"] != "UNKNOWN" or
            stopped["model_calls_attempted"] != 1 or
            failed.uuid in {row["session_id"] for row in rows} or
            failed.model_usage):
        raise ValueError("stopped session no longer matches archived failure")

    account = json.loads(ACCOUNT.read_text())
    if account["request_kind"] != "READ_ONLY_NO_MODEL_CALL" or account["raw_response_stored"]:
        raise ValueError("account observation is not the sanitized read-only record")
    csv_total = sum((Decimal(row["total_usage"]) for row in rows), Decimal(0))
    target_total = sum((Decimal(row["total_usage"]) for row in target), Decimal(0))
    account_total = Decimal(account["usage_usd"])
    if account_total < csv_total:
        raise ValueError("account aggregate is below the CSV sum")
    return {
        "schema": "mpp006-provider-export-readonly-forensics-v1",
        "result": "INCONCLUSIVE_FOR_EXACT_CHARGE",
        "ledger_mutations": 0,
        "paid_model_calls": 0,
        "provider_csv_sha256": CSV_SHA256,
        "provider_csv_rows": len(rows),
        "provider_csv_total_usd_rounded_6dp": str(csv_total.quantize(Decimal("0.000001"))),
        "provider_13h_total_usd": str(target_total),
        "provider_13h_request_count": sum(int(row["request_count"]) for row in target),
        "completed_session_matches": matches,
        "stopped_episode": {
            "episode_id": STOPPED,
            "sample_uuid": failed.uuid,
            "started_at_utc": failed.started_at,
            "completed_at_utc": failed.completed_at,
            "inspect_sha256": failed_sha,
            "stopped_sha256": hashlib.sha256(stopped_raw).hexdigest(),
            "model_calls_attempted": stopped["model_calls_attempted"],
            "model_usage_empty": not bool(failed.model_usage),
            "session_absent_from_provider_csv": True,
            "budget_state": stopped["budget_state"],
        },
        "account_usage_observation": {
            "observed_before_utc": account["observed_before_utc"],
            "observed_after_utc": account["observed_after_utc"],
            "usage_usd": account["usage_usd"],
            "raw_response_sha256": account["response_sha256"],
            "sanitized_file_sha256": hashlib.sha256(ACCOUNT.read_bytes()).hexdigest(),
            "aggregate_above_csv_usd_rounded_7dp": str(
                (account_total - csv_total).quantize(Decimal("0.0000001"))
            ),
        },
        "limitations": [
            "The user-supplied provider CSV is unsigned and lacks request-level IDs and failed requests.",
            "Absence of the stopped session from this CSV does not establish a final zero-dollar charge.",
            "The later key-level usage exceeds the CSV total and is not attributable to the stopped call.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
