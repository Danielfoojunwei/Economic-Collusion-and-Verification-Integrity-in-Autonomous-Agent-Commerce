#!/usr/bin/env python3
"""Run native localhost protocol probes and collect heterogeneous service evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.service_terms_suite import (  # noqa: E402
    A2A_PYTHON_COMMIT,
    A2A_SPEC_COMMIT,
    ACP_COMMIT,
    build_service_record,
    collect_bundle,
    file_sha256,
)
from protocols.acp_retail.local_checkout import LocalCheckoutMerchant  # noqa: E402


ORBIT_PYTHON = Path("/workspace/upstreams/orbit-smoke/.venv/bin/python")
AP2_PYTHON = Path("/workspace/upstreams/ap2-w15/.venv/bin/python")
A2A_PYTHON = Path("/workspace/upstreams/w17-a2a-venv/bin/python")
ACP_UPSTREAM = Path("/workspace/upstreams/w17-acp-retail")
TEMPO_IMAGE = ("ghcr.io/tempoxyz/tempo-localnet@"
               "sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b")


def local_only_env() -> dict[str, str]:
    """Retain tool/runtime settings while withholding unrelated credentials."""
    blocked_fragments = ("API_KEY", "TOKEN", "SECRET", "CREDENTIAL", "PASSWORD")
    blocked_prefixes = ("AWS_", "AZURE_", "GOOGLE_", "OPENAI_", "OPENROUTER_", "OAI_")
    return {name: value for name, value in os.environ.items()
            if not any(fragment in name.upper() for fragment in blocked_fragments)
            and not name.upper().startswith(blocked_prefixes)}


def run_logged(name: str, command: list[str], *, output: Path,
               cwd: Path = ROOT, env: dict[str, str] | None = None,
               timeout: int = 180) -> dict:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, env=env or local_only_env(), capture_output=True, text=True,
                            timeout=timeout, check=False)
    (output / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    record = {"name": name, "command": command, "cwd": str(cwd),
              "exit_code": result.returncode,
              "elapsed_seconds": round(time.monotonic() - started, 3)}
    if result.returncode:
        raise RuntimeError(f"{name} failed with {result.returncode}; inspect {output}/{name}.stderr.txt")
    return record


def wait_rpc(port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode()
    while time.monotonic() < deadline:
        try:
            request = Request(f"http://127.0.0.1:{port}", data=payload,
                              headers={"content-type": "application/json"})
            with urlopen(request, timeout=1) as response:
                if json.load(response).get("result") == "0x539":
                    return
        except Exception:
            time.sleep(0.1)
    raise TimeoutError("local Tempo RPC did not become ready")


def checkout_evidence() -> dict:
    merchant = LocalCheckoutMerchant(ACP_UPSTREAM)
    create = merchant.examples["create_checkout_session_request"]
    complete = merchant.examples["complete_checkout_session_request"]
    created = merchant.create("service-create-1", create)
    completed = merchant.complete("service-complete-1", complete)
    replay = merchant.complete("service-complete-1", complete)
    conflict_merchant = LocalCheckoutMerchant(ACP_UPSTREAM)
    conflict_merchant.create("conflict-1", create)
    changed = deepcopy(create)
    changed["currency"] = "eur"
    conflict = conflict_merchant.create("conflict-1", changed)
    return {
        "protocol": "OpenAI/Stripe ACP checkout", "spec_version": "2026-04-17",
        "source_commit": ACP_COMMIT,
        "schema_sha256": file_sha256(ACP_UPSTREAM / "spec/2026-04-17/json-schema/schema.agentic_checkout.json"),
        "execution_tier": "MOCK_LOCAL_SCHEMA_CONFORMANCE", "payment_execution": "NONE",
        "create_status": created.status, "complete_status": completed.status,
        "replay_identical": replay.replayed and replay.body == completed.body,
        "capture_attempts": merchant.capture_attempts,
        "conflict_status": conflict.status, "conflict_code": conflict.body.get("code"),
        "limitations": ["Merchant and capture are local state mocks.",
                        "No payment credential, PSP, transfer, or settlement was exercised."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--x402-port", type=int, default=18940)
    parser.add_argument("--mpp-rpc-port", type=int, default=18970)
    parser.add_argument("--mpp-http-port", type=int, default=18971)
    parser.add_argument("--reuse-mpp-rpc", action="store_true",
                        help="use an already running pinned local Tempo container")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite suite evidence: {output}")
    output.mkdir(parents=True)
    commands: list[dict] = []

    service_record = build_service_record()
    (output / "service-record.json").write_text(
        json.dumps(service_record, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    erc_dir = output / "erc8183"
    commands.append(run_logged("erc8183", [str(ORBIT_PYTHON), "scripts/run_erc8183_local.py",
                                            "--output", str(erc_dir)], output=output))

    x402_dir = output / "x402"
    x402_dir.mkdir()
    commands.append(run_logged("x402", ["node", "scripts/run_x402_local.mjs",
                                         "--port", str(args.x402_port),
                                         "--resource-record-file", str(output / "service-record.json"),
                                         "--output", str(x402_dir / "evidence.json")], output=output))

    ap2_dir = output / "ap2"
    ap2_dir.mkdir()
    commands.append(run_logged("ap2", [str(AP2_PYTHON), "scripts/run_ap2_local.py",
                                        "--output", str(ap2_dir / "evidence.json")], output=output))

    acp_dir = output / "acp"
    acp_dir.mkdir()
    (acp_dir / "evidence.json").write_text(
        json.dumps(checkout_evidence(), sort_keys=True, indent=2) + "\n", encoding="utf-8")

    a2a_dir = output / "a2a"
    a2a_dir.mkdir()
    a2a_command = [str(A2A_PYTHON), "-m", "unittest", "-v", "tests.test_a2a_local"]
    a2a_run = run_logged("a2a", a2a_command, output=output)
    commands.append(a2a_run)
    a2a_text = (output / "a2a.stderr.txt").read_text(encoding="utf-8")
    match = re.search(r"Ran (\d+) test", a2a_text)
    (a2a_dir / "evidence.json").write_text(json.dumps({
        "protocol": "A2A v1.0 HTTP+JSON", "spec_commit": A2A_SPEC_COMMIT,
        "sdk_commit": A2A_PYTHON_COMMIT, "execution_tier": "NATIVE_LOCAL_PROTOCOL",
        "transport": "in-process ASGI through official Python SDK routes/client",
        "application_auth": "MOCK_BEARER", "identity_proof": "NONE",
        "payment_execution": "NONE", "test_exit_code": a2a_run["exit_code"],
        "tests_run": int(match.group(1)) if match else 0,
        "test_source_sha256": file_sha256(ROOT / "tests/test_a2a_local.py"),
    }, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    mpp_dir = output / "mpp"
    mpp_dir.mkdir()
    warehouse = next(case["artifact"] for case in service_record["cases"]
                     if case["case_id"] == "warehouse-good")
    warehouse_path = output / "warehouse-report.json"
    warehouse_path.write_text(json.dumps(warehouse, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    container = f"service-terms-mpp-{os.getpid()}"
    docker = ["docker", "--host=unix:///var/run/docker.sock"]
    docker_env = local_only_env()
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        docker_env.pop(name, None)
    started_container = False
    try:
        if not args.reuse_mpp_rpc:
            commands.append(run_logged("mpp-docker", docker + [
                "run", "--pull=never", "--rm", "-d", "--name", container,
                "-p", f"127.0.0.1:{args.mpp_rpc_port}:8545", TEMPO_IMAGE, "--block-time", "1ms",
            ], output=output, env=docker_env))
            started_container = True
        wait_rpc(args.mpp_rpc_port)
        mpp_env = local_only_env()
        mpp_env.update({
            "MPP_TEMPO_RPC_URL": f"http://127.0.0.1:{args.mpp_rpc_port}",
            "MPP_HTTP_URL": f"http://127.0.0.1:{args.mpp_http_port}",
            "MPP_CROSSRAIL_EVIDENCE_DIR": str(mpp_dir),
            "MPP_CROSSRAIL_REPORT_FILE": str(warehouse_path),
        })
        commands.append(run_logged("mpp", ["node", "--test", "test-crossrail-receipt.mjs"],
                                   output=output, cwd=ROOT / "protocols/mpp", env=mpp_env))
    finally:
        if started_container:
            subprocess.run(docker + ["stop", container], cwd=ROOT, env=docker_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=20)

    (output / "commands.json").write_text(
        json.dumps(commands, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    suite = collect_bundle(output)
    suite["commands"] = commands
    (output / "suite.json").write_text(
        json.dumps(suite, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": suite["status"], "service_cases": suite["service_case_count"],
                      "protocols": sorted(suite["protocols"]),
                      "output": str(output / "suite.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

