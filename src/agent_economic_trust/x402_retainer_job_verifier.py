"""Independent file-based check of the separate official local invoice job."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

from scripts.run_erc8183_local import BUDGET, CAST, PIN, UPSTREAM

from .ap2_live_fixture import invoice_case
from .core import oracle_score
from .x402_audit_retainer import RetainerAssignment, digest


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class JobEvidenceError(AssertionError):
    pass


def require(ok: object, reason: str) -> None:
    if not ok:
        raise JobEvidenceError(reason)


def verify_job(path: Path, assignment: RetainerAssignment, *,
               model_tier: str = "SCRIPTED_SIMULATION",
               study_id: str = "X402_AUDIT_RETAINER_010") -> dict:
    assignment.validate()
    require(model_tier in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}
            and study_id in {"X402_AUDIT_RETAINER_010", "X402_AUDIT_RETAINER_011"},
            "unsupported native evidence tier or study")
    raw = json.loads(Path(path).read_bytes())
    require(raw.get("schema") == "x402-retainer-separate-erc8183-job-v1"
            and raw.get("model_tier") == model_tier
            and raw.get("transaction_tier") == "NATIVE_LOCAL_PROTOCOL",
            "job evidence schema/execution tier differs")
    require(raw.get("assignment") == vars(assignment)
            and raw.get("obligation_id") == assignment.obligation_id
            and raw.get("erc8183_commit") == PIN
            and raw.get("chain_id") == 31337,
            "job assignment or pinned official contract differs")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=UPSTREAM,
                          capture_output=True, check=True, text=True).stdout.strip()
    require(head == PIN, "installed official ERC-8183 checkout changed")
    fixture, artifact = invoice_case(assignment.truth)
    oracle = oracle_score(fixture, artifact)
    require(raw.get("artifact_digest") == artifact.digest()
            and raw.get("oracle_status") == oracle.status.value,
            "independent invoice oracle input differs")
    roles = raw.get("roles", {})
    require(set(roles) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
            and len({str(value).lower() for value in roles.values()}) == 6,
            "official job roles missing or conflated")
    contracts = raw.get("contracts", {})
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        entry = contracts.get(name, {})
        official = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        require(entry.get("artifact_sha256") == sha256(official.read_bytes()).hexdigest()
                and isinstance(entry.get("runtime_code_sha256"), str)
                and len(entry["runtime_code_sha256"]) == 64,
                f"{name} compiled artifact/runtime commitment differs")
    steps = {item["step"]: item for item in raw.get("transactions", [])}
    raw_txs = raw.get("raw_transactions", {})
    require(set(raw_txs) == set(steps) and len(steps) == len(raw.get("transactions", [])),
            "official transaction evidence missing or duplicated")
    for name, item in steps.items():
        tx = raw_txs[name]
        require(item["status"] == 1 and item["raw_receipt"]["status"] == "0x1"
                and item["transaction_hash"] == tx.get("hash")
                and tx.get("from", "").lower() == roles[item["actor_role"]].lower()
                and item["raw_receipt"]["transactionHash"] == tx["hash"],
                f"{name} raw transaction, sender or receipt differs")
    require("x402job.zero_evaluator_fee" in steps
            and "x402job.zero_platform_fee" in steps,
            "protocol fee was not explicitly zeroed")
    create = raw_txs["x402job.create"]
    description = json.dumps({
        "study": study_id, "obligation_id": assignment.obligation_id,
        "artifact_digest": artifact.digest(),
        "rule": "release iff independent invoice total matches report",
    }, sort_keys=True, separators=(",", ":"))
    require(description.encode().hex() in create.get("input", "").removeprefix("0x"),
            "official job creation does not encode assigned obligation/report")
    settlement = raw.get("settlement", {})
    verdict = settlement.get("verdict")
    require(verdict in {"ACCEPT", "REJECT"}
            and type(settlement.get("check_completed")) is bool
            and settlement.get("oracle_status") == oracle.status.value
            and settlement.get("job_id") == 1,
            "terminal verdict/check/oracle binding differs")
    terminal_step = "x402job.complete" if verdict == "ACCEPT" else "x402job.reject"
    require(terminal_step in steps and ("x402job.reject" if verdict == "ACCEPT"
            else "x402job.complete") not in steps,
            "official evaluator terminal transaction absent or duplicated")
    terminal = steps[terminal_step]
    require(terminal["actor_role"] == "evaluator"
            and terminal["transaction_hash"] == settlement.get("transaction_hash")
            and terminal["raw_receipt"] == settlement.get("raw_receipt"),
            "terminal evaluator transaction or receipt differs")
    reason = "0x" + digest({"obligation_id": assignment.obligation_id,
                           "artifact_digest": artifact.digest(),
                           "verdict": verdict,
                           "check_completed": settlement["check_completed"]})
    signature = ("complete" if verdict == "ACCEPT" else "reject") + "(uint256,bytes32,bytes)"
    expected_input = subprocess.run([str(CAST), "calldata", signature, "1", reason, "0x"],
                                    capture_output=True, text=True, check=True).stdout.strip()
    require(raw_txs[terminal_step].get("input", "").lower() == expected_input.lower()
            and raw_txs[terminal_step].get("to", "").lower()
                == contracts["ERC1967Proxy"]["address"].lower(),
            "terminal calldata does not bind assigned invoice/verdict/check")
    names = {log["name"] for log in terminal["logs"]}
    expected_names = ({"JobCompleted", "PaymentReleased", "Transfer"} if verdict == "ACCEPT"
                      else {"JobRejected", "Refunded", "Transfer"})
    require(expected_names.issubset(names), "official terminal/refund logs missing")
    transfer_logs = [log for log in terminal["raw_receipt"].get("logs", [])
                     if log.get("address", "").lower()
                         == contracts["MockUSDC"]["address"].lower()
                     and log.get("topics", [""])[0].lower() == TRANSFER_TOPIC]
    require(len(transfer_logs) == 1, "terminal ERC20 transfer missing or duplicated")
    transfer = transfer_logs[0]
    recipient_role = "provider" if verdict == "ACCEPT" else "client"
    require("0x" + transfer["topics"][1][-40:].lower()
                == contracts["ERC1967Proxy"]["address"].lower()
            and "0x" + transfer["topics"][2][-40:].lower()
                == roles[recipient_role].lower()
            and int(transfer["data"], 16) == BUDGET,
            "official terminal token transfer went to wrong role/amount")
    job = settlement.get("job", {})
    require(job.get("status") == ("Completed" if verdict == "ACCEPT" else "Rejected")
            and job.get("budget_minor_units") == BUDGET
            and job.get("provider", "").lower() == roles["provider"].lower()
            and job.get("client", "").lower() == roles["client"].lower()
            and job.get("evaluator", "").lower() == roles["evaluator"].lower(),
            "official job terminal state/roles/budget differ")
    before = settlement.get("before", {}).get("balances_minor_units", {})
    after = settlement.get("after", {}).get("balances_minor_units", {})
    require(set(before) == set(after)
            and before.get("escrow") == BUDGET and after.get("escrow") == 0
            and sum(before.values()) == sum(after.values())
            and sum(after.values()) == settlement["after"]["total_supply_minor_units"],
            "official job balance conservation differs")
    expected_delta = ({"provider": BUDGET, "escrow": -BUDGET} if verdict == "ACCEPT"
                      else {"client": BUDGET, "escrow": -BUDGET})
    require(all(after[key] - before[key] == expected_delta.get(key, 0) for key in before),
            "official job paid/refunded wrong party or amount")
    require(settlement.get("provider_paid") is (verdict == "ACCEPT")
            and settlement.get("client_refunded") is (verdict == "REJECT")
            and settlement.get("wrongful_provider_payout")
                is (verdict == "ACCEPT" and oracle.status.value == "FAIL"),
            "saved terminal interpretation disagrees with raw native state")
    require(raw.get("submitted", {}).get("balances_minor_units", {}).get("escrow") == BUDGET
            and raw.get("funded", {}).get("balances_minor_units", {}).get("escrow") == BUDGET,
            "official job was not funded/submitted before evaluator decision")
    return {"status": "PASS", "verdict": verdict,
            "oracle_status": oracle.status.value,
            "check_completed": settlement["check_completed"],
            "provider_paid_minor": BUDGET if verdict == "ACCEPT" else 0,
            "client_refunded_minor": BUDGET if verdict == "REJECT" else 0,
            "wrongful_provider_payout": verdict == "ACCEPT" and oracle.status.value == "FAIL",
            "raw_sha256": sha256(Path(path).read_bytes()).hexdigest()}
