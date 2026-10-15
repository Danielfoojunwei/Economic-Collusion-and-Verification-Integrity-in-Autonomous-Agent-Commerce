#!/usr/bin/env python3
"""Freeze a W11 schedule and probe ORBIT's no-direct-channel tool grants.

This uses a scripted Inspect model only. It does not execute the longitudinal
market, call a paid model, or settle a payment.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("XDG_DATA_HOME", "/workspace/.local/share")
os.environ.setdefault("XDG_CACHE_HOME", "/workspace/.cache")
os.environ.setdefault("XDG_CONFIG_HOME", "/workspace/.config")

from inspect_ai import eval as inspect_eval  # noqa: E402
from agent_economic_trust.market_assignment import (  # noqa: E402
    assert_native_channel_adherence, build_market_schedule, schedule_sha256,
)
from agent_economic_trust.protected_receipts import (  # noqa: E402
    ACCEPTED, protected_receipt_orbit,
)
from tests.test_protected_receipts import make_case, scripted_model  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    case = make_case(ACCEPTED)
    tasks = ("warmup-0", "warmup-1", case.task_id, "followup-3")
    schedule = build_market_schedule(seed=73, task_ids=tasks)
    no_channel = next(
        row for row in schedule if row.arm == "TURNOVER_NO_DIRECT" and row.round_index == 2
    )
    task = protected_receipt_orbit(case, budget_units=1)
    # multi_agent_task always installs an empty CommunicationConfig and thus
    # grants channel_post/read/list. The low-level ORBIT ExperimentConfig
    # accepts None; this is a focused offline probe of that documented path.
    config = task.dataset.samples[0].metadata["experiment"]
    if (
        config["execution"]["observation"]["mode"] != "none"
        or config["setup"].get("communication_edges") is not None
        or config["setup"]["memory"].get("shared")
        or config["setup"]["memory"].get("shared_groups")
    ):
        raise RuntimeError("task has another cross-agent communication path")
    config["communication"] = None
    [log] = inspect_eval(
        task, model=scripted_model("check"), log_dir=str(output),
        display="none", log_realtime=False, max_retries=0,
    )
    if log.status != "success" or not log.samples or len(log.samples) != 1:
        raise RuntimeError(f"scripted native channel probe failed: {log.error}")
    sample = log.samples[0]
    inspection = assert_native_channel_adherence(
        no_channel, sample, provider_agent_name="worker", verifier_agent_name="auditor",
    )
    native = output / "inspect.eval"
    Path(log.location).replace(native)
    pins = json.loads((ROOT / "UPSTREAM_PINNED.json").read_text())["sources"]
    result = {
        "status": "PASS_METHODS_PROBE_ONLY",
        "model_behavior_tier": "SCRIPTED_SIMULATION",
        "payment_tier": "NO_PAYMENT",
        "source_pins": {
            "orbit": pins["orbit"], "inspect_ai": pins["inspect_ai"],
            "colosseum": pins["colosseum"],
        },
        "code_sha256": {
            relative: sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "src/agent_economic_trust/coordination_metrics.py",
                "src/agent_economic_trust/market_assignment.py",
                "src/agent_economic_trust/protected_receipts.py",
                "scripts/run_w11_w12_methods_offline.py",
            )
        },
        "assignment_seed": 73,
        "assignment_unit": "market",
        "schedule_sha256": schedule_sha256(schedule),
        "schedule": [asdict(row) for row in schedule],
        "probe_assignment": asdict(no_channel),
        "probe_native_inspect_sha256": sha256(native.read_bytes()).hexdigest(),
        "probe_communication_config": None,
        "probe_native_capability_audit": inspection,
        "limitations": (
            "No longitudinal relationship, randomized model behavior, real payment, "
            "or observed collusion. A full W11 runner must enforce these grants "
            "and histories in every assigned episode."
        ),
    }
    (output / "methods.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: result[key] for key in (
        "status", "assignment_seed", "assignment_unit", "schedule_sha256",
        "probe_native_capability_audit",
    )}, sort_keys=True))


if __name__ == "__main__":
    main()
