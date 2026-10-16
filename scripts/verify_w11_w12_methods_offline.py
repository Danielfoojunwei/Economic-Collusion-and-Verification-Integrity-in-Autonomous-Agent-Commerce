#!/usr/bin/env python3
"""Independently check frozen W11/W12 methods evidence and native tool grants."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from inspect_ai.log import read_eval_log


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    args = parser.parse_args()
    folder = args.input_dir.resolve()
    payload = json.loads((folder / "methods.json").read_text(encoding="utf-8"))
    if payload["status"] != "PASS_METHODS_PROBE_ONLY":
        raise ValueError("methods run is not complete")
    schedule = payload["schedule"]
    schedule_bytes = json.dumps(schedule, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode()
    if sha256(schedule_bytes).hexdigest() != payload["schedule_sha256"]:
        raise ValueError("assignment schedule hash mismatch")
    markets: dict[str, list[dict]] = {}
    people: dict[str, str] = {}
    for row in schedule:
        markets.setdefault(row["market_id"], []).append(row)
        if row["randomization_unit"] != "market":
            raise ValueError("assignment unit is not market")
        for identity in (row["provider_id"], row["verifier_id"]):
            prior_market = people.setdefault(identity, row["market_id"])
            if prior_market != row["market_id"]:
                raise ValueError("agent identity leaks across markets")
    expected_arms = {
        "REPEAT_DIRECT", "REPEAT_NO_DIRECT", "TURNOVER_DIRECT",
        "TURNOVER_NO_DIRECT", "CROSSOVER_NO_DIRECT",
    }
    if len(markets) != len(expected_arms) or {rows[0]["arm"] for rows in markets.values()} != expected_arms:
        raise ValueError("assignment arms are not balanced")
    for rows in markets.values():
        if len(rows) != 4 or [row["round_index"] for row in rows] != [0, 1, 2, 3]:
            raise ValueError("market rounds are missing or out of order")
        if rows[2]["arm"] == "TURNOVER_NO_DIRECT" and (
            rows[2]["communication_mode"] != "NONE"
            or rows[2]["verifier_visible_prior_episode_ids"]
            or rows[2]["verifier_id"] == rows[1]["verifier_id"]
            or rows[2]["provider_visible_prior_episode_ids"]
            != [rows[0]["episode_id"], rows[1]["episode_id"]]
        ):
            raise ValueError("turnover no-channel control does not replace/reset verifier")
    native_path = folder / "inspect.eval"
    if sha256(native_path.read_bytes()).hexdigest() != payload["probe_native_inspect_sha256"]:
        raise ValueError("native Inspect log hash mismatch")
    log = read_eval_log(str(native_path))
    if log.status != "success" or not log.eval.model.startswith("mockllm/") or len(log.samples or []) != 1:
        raise ValueError("native probe is not one successful scripted Inspect episode")
    sample = log.samples[0]
    if sample.id != payload["probe_assignment"]["task_id"]:
        raise ValueError("native sample task differs from assignment")
    if sample.scores["protected_receipt_score"].metadata["payment_tier"] != "NOT_EXECUTED":
        raise ValueError("probe unexpectedly executed payment")
    spans = {event.id: event for event in sample.events if event.event == "span_begin"}
    allowed = {
        "worker": {"read_provider_receipts", "submit_receipt_artifact"},
        "auditor": {"view_receipt_submission", "priced_receipt_check", "issue_receipt_verdict"},
    }
    counts = {"worker": 0, "auditor": 0, "channel_tool_calls": 0}
    for event in sample.events:
        if event.event not in {"model", "tool"}:
            continue
        span_id = getattr(event, "span_id", None)
        seen = set()
        actor = None
        while span_id is not None and span_id not in seen:
            seen.add(span_id)
            span = spans.get(span_id)
            if span is None:
                break
            if span.type == "agent":
                actor = span.name
                break
            span_id = span.parent_id
        if actor not in allowed:
            raise ValueError("native event is not under an assigned role")
        if event.event == "model":
            names = {tool.name for tool in event.tools}
            if names != allowed[actor]:
                raise ValueError("native model was offered unexpected role/channel tools")
            counts[actor] += 1
        elif event.function not in allowed[actor]:
            raise ValueError("native role executed an unexpected or channel tool")
    if not counts["worker"] or not counts["auditor"]:
        raise ValueError("both native agent roles did not run")
    claimed = payload["probe_native_capability_audit"]
    if claimed != {
        "provider_model_events": counts["worker"],
        "verifier_model_events": counts["auditor"],
        "channel_tool_calls": counts["channel_tool_calls"],
    }:
        raise ValueError("native grant counts differ from manifest")
    print(json.dumps({"status": "VERIFIED_METHODS_ONLY",
                      "schedule_sha256": payload["schedule_sha256"],
                      "native_sha256": payload["probe_native_inspect_sha256"],
                      "model_events": counts["worker"] + counts["auditor"]}, sort_keys=True))


if __name__ == "__main__":
    main()
