#!/usr/bin/env python3
"""Exercise the new MPP008 bridge with scripted agents and real local MPP."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_PARENT = Path(__file__).resolve().parents[2]
os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("XDG_DATA_HOME", str(PROJECT_PARENT / ".local/share"))
os.environ.setdefault("XDG_CACHE_HOME", str(PROJECT_PARENT / ".cache"))
os.environ.setdefault("XDG_CONFIG_HOME", str(PROJECT_PARENT / ".config"))

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from agent_economic_trust.mpp008_native_service import (
    NativeMeetingService, inspect_native_service_log, native_service_orbit)
from agent_economic_trust.mpp008_boundary import (
    expected_serialized_tools, verify_strict_tool_schemas)
from agent_economic_trust.open_mpp_smoke import MODEL, scripted_model


ROOT = Path(__file__).resolve().parents[1]


def run_new_native_controls() -> dict:
    rows = []
    with TemporaryDirectory(prefix="mpp008-native-control-", dir="/tmp") as temporary:
        for index, (truth, flow) in enumerate((("GOOD", "charge"), ("BAD", "session"))):
            directory = Path(temporary) / truth.lower()
            service = NativeMeetingService(directory.resolve())
            asyncio.run(service.prepare())
            task = native_service_orbit(truth, service=service, condition="OPEN",
                trial_id=f"mpp008-offline-{index:02}", scheduler_seconds=120,
                task_token_limit=20000)
            [log] = inspect_eval(task, model=scripted_model(checked=True, flow=flow),
                log_dir=str(directory / "logs"), display="none", log_realtime=False,
                max_retries=0, retry_on_error=0)
            if log.status != "success" or not log.location:
                raise ValueError("MPP008 scripted native ORBIT control failed")
            raw = read_eval_log(log.location, resolve_attachments=True)
            sample = raw.samples[0]
            counts = {"provider": 0, "auditor": 0}
            for event in sample.events:
                if event.event != "model":
                    continue
                names = {tool.name for tool in event.tools}
                actor = "provider" if "select_mpp_flow" in names else "auditor"
                counts[actor] += 1
                verify_strict_tool_schemas(expected_serialized_tools(event.tools), actor)
            if not all(counts.values()):
                raise ValueError("MPP008 native control omitted a model role")
            decision = asyncio.run(inspect_native_service_log(raw, service=service,
                quality=truth, condition="OPEN", expected_model=MODEL))
            decision_path = directory / "decision.json"
            decision_path.write_text(json.dumps(decision, sort_keys=True) + "\n")
            compensation = directory / "compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/meeting-local.mjs",
                decision_path, flow, compensation))
            asyncio.run(service._command(ROOT / "protocols/mpp/verify-meeting-evidence.mjs",
                compensation))
            if (decision["verdict"] != ("ACCEPT" if truth == "GOOD" else "REJECT")
                    or decision["checked"] is not True
                    or any(event.event == "tool" and event.error for event in sample.events)):
                raise ValueError("MPP008 scripted native verdict/check differs")
            rows.append({"truth": truth, "flow": flow, "verdict": decision["verdict"],
                         "checked": True, "model_events": counts,
                         "payment_execution": "NATIVE_LOCAL_PROTOCOL",
                         "model_execution": "SCRIPTED_SIMULATION"})
    return {"status": "PASS", "rows": rows, "real_remote_model_calls": 0,
            "meaning": "transport and payment plumbing only; no agent collusion inference"}


if __name__ == "__main__":
    print(json.dumps(run_new_native_controls(), sort_keys=True))
