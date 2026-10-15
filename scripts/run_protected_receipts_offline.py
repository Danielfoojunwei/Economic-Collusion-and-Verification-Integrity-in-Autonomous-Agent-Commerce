#!/usr/bin/env python3
"""Save native Inspect logs for the protected-receipt blind-auditor control.

This uses the scripted controls from the focused offline test module. It makes
no model-provider or payment-protocol request and cannot establish G4 behavior.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inspect_ai import eval as inspect_eval  # noqa: E402
from agent_economic_trust.protected_receipts import (  # noqa: E402
    ACCEPTED, REJECTED, protected_receipt_orbit,
)
from tests.test_protected_receipts import make_case, scripted_model  # noqa: E402


def _hash(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _without_transport_ids(value):
    if isinstance(value, dict):
        return {key: _without_transport_ids(item) for key, item in value.items()
                if key not in {"id", "tool_call_id"}}
    if isinstance(value, list):
        return [_without_transport_ids(item) for item in value]
    return value


def _agent(event, sample):
    spans = {item.id: item for item in sample.events if item.event == "span_begin"}
    span_id = getattr(event, "span_id", None)
    while span_id is not None:
        span = spans.get(span_id)
        if span is None:
            break
        if span.type == "agent":
            return span.name
        span_id = span.parent_id
    return None


def _observed(sample, case):
    precheck_inputs = []
    view_result = None
    check_result = None
    before_check = True
    for event in sample.events:
        if event.event == "model":
            payload = [message.model_dump(mode="json") for message in event.input]
            if case.private_commitment() in json.dumps(payload):
                raise RuntimeError("private warehouse commitment reached a model")
            if before_check and _agent(event, sample) == "auditor":
                precheck_inputs.append(_without_transport_ids(payload))
        if event.event == "tool" and event.function == "view_receipt_submission":
            view_result = str(event.result)
        if event.event == "tool" and event.function == "priced_receipt_check":
            before_check = False
            check_result = json.loads(str(event.result))
    if not precheck_inputs or view_result is None or check_result is None:
        raise RuntimeError("missing auditor precheck input, view, or purchased result")
    score = sample.scores["protected_receipt_score"].metadata
    return {
        "public_task_sha256": _hash(_canonical(case.public_task())),
        "provider_copy_sha256": _hash(_canonical(case.provider_copy())),
        "auditor_precheck_model_inputs_sha256": _hash(_canonical(precheck_inputs)),
        "auditor_view_sha256": _hash(view_result.encode("utf-8")),
        "check_result": check_result,
        "score": score,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = {
        "study_type": "SCRIPTED_OFFLINE_CALIBRATION",
        "model_behavior_tier": "SCRIPTED",
        "payment_tier": "NOT_EXECUTED",
        "upstreams": {"orbit": "1.0.3", "inspect_ai": "0.3.263"},
        "worlds": {},
    }
    for name, status in (("good", ACCEPTED), ("bad", REJECTED)):
        case = make_case(status)
        run_dir = output / name
        [log] = inspect_eval(
            protected_receipt_orbit(case, budget_units=1),
            model=scripted_model("check"), log_dir=str(run_dir),
            display="none", log_realtime=False, max_retries=0,
        )
        if log.status != "success" or not log.samples or len(log.samples) != 1:
            raise RuntimeError(f"{name} Inspect calibration failed: {log.error}")
        sample = log.samples[0]
        if sample.error or sample.limit:
            raise RuntimeError(f"{name} sample failed: {sample.error or sample.limit}")
        native = run_dir / "inspect.eval"
        Path(log.location).replace(native)
        evidence["worlds"][name] = {
            **_observed(sample, case),
            "private_warehouse_commitment": case.private_commitment(),
            "native_inspect_log": str(native.relative_to(output)),
            "native_inspect_log_sha256": _hash(native.read_bytes()),
        }
    good = evidence["worlds"]["good"]
    bad = evidence["worlds"]["bad"]
    for field in (
        "public_task_sha256", "provider_copy_sha256",
        "auditor_precheck_model_inputs_sha256", "auditor_view_sha256",
    ):
        if good[field] != bad[field]:
            raise RuntimeError(f"auditor-visible precheck field differs: {field}")
    if [good["score"]["oracle_status"], bad["score"]["oracle_status"]] != ["PASS", "FAIL"]:
        raise RuntimeError("private warehouse worlds failed opposite-oracle calibration")
    evidence["status"] = "PASS"
    (output / "calibration.json").write_bytes(_canonical(evidence) + b"\n")
    print(json.dumps({
        "status": "PASS", "worlds": list(evidence["worlds"]),
        "same_precheck_model_inputs_sha256": good["auditor_precheck_model_inputs_sha256"],
        "oracle_statuses": [good["score"]["oracle_status"],
                            bad["score"]["oracle_status"]],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
