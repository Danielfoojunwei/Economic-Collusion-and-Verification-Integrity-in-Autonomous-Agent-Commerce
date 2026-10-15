#!/usr/bin/env python3
"""Independently re-open and check the zero-model ERC-8183 fee control receipts."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT.parent / "upstreams/erc8183"
CAST = ROOT.parent / ".tools/foundry/v1.8.5/cast"
PIN = "142e669c1fd318486a4628395b629f033654dd06"
ZERO = "0x" + "00" * 20
CLIENT_MAX = 20_000_000
REWARD = 2_000_000
ENDOWMENT = 500_000
CHECK = 200_000
PARTIAL = 5_000_000


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _cast(*args: str) -> str:
    return subprocess.run([str(CAST), *args], check=True, capture_output=True,
                          text=True, timeout=10).stdout.strip().lower()


def _event_topics(artifacts: dict[str, Any]) -> dict[str, str]:
    result = {}
    for artifact in artifacts.values():
        for item in artifact["abi"]:
            if item["type"] != "event" or item.get("anonymous"):
                continue
            signature = item["name"] + "(" + ",".join(x["type"] for x in item["inputs"]) + ")"
            result[_cast("keccak", signature)] = item["name"]
    return result


def _step_names(case: dict[str, Any]) -> list[str]:
    steps = ["deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
             "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
             "setup.mint", "setup.approve", "terms.platform_zero"]
    if case["arm"] == "CLIENT_PREPAID":
        steps.append("terms.evaluator_zero")
    steps.append("endowment.mint")
    if case["arm"] == "CLIENT_PREPAID":
        steps.append("terms.client_prepay")
    steps += ["job.create", "job.set_budget", "job.fund"]
    if case["prior_claim"]:
        steps.append("negative.client_settle_claim")
    steps.append("job.submit")
    if case["check"]:
        steps.append("check.auditor_debit")
    steps.append("job.complete" if case["verdict"] == "ACCEPT" else "job.reject")
    return steps


def _logs(tx: dict[str, Any], name: str, *, address: str | None = None) -> list[dict[str, Any]]:
    return [x for x in tx["raw_receipt"]["logs"] if x["_checked_name"] == name
            and (address is None or x["address"].lower() == address.lower())]


def _event_amount(tx: dict[str, Any], name: str, recipient: str,
                  core: str, job_id: int) -> int:
    logs = _logs(tx, name, address=core)
    _require(len(logs) == 1, f"{tx['step']}: expected one {name}")
    log = logs[0]
    _require(len(log["topics"]) == 3
             and int(log["topics"][1], 16) == job_id
             and ("0x" + log["topics"][2][-40:]).lower() == recipient.lower(),
             f"{tx['step']}: {name} recipient/job differs")
    return int(log["data"], 16)


def _transfer(tx: dict[str, Any], token: str, sender: str, receiver: str,
              amount: int) -> None:
    logs = _logs(tx, "Transfer", address=token)
    matches = [x for x in logs if len(x["topics"]) == 3
               and ("0x" + x["topics"][1][-40:]).lower() == sender.lower()
               and ("0x" + x["topics"][2][-40:]).lower() == receiver.lower()
               and int(x["data"], 16) == amount]
    _require(len(matches) == 1, f"{tx['step']}: exact ERC-20 Transfer missing")


def _calldata(tx: dict[str, Any], signature: str, args: list[int | str]) -> None:
    raw = tx["raw_transaction"]
    data = raw["input"].lower()
    _require(data.startswith(_cast("sig", signature)) and len(data) >= 10 + 64 * len(args),
             f"{tx['step']}: calldata selector/length differs")
    for index, expected in enumerate(args):
        word = data[10 + 64 * index:10 + 64 * (index + 1)]
        actual = int(word, 16)
        want = int(expected, 16) if isinstance(expected, str) and expected.startswith("0x") else int(expected)
        _require(actual == want, f"{tx['step']}: calldata argument {index} differs")


def verify_record(e: dict[str, Any]) -> dict[str, Any]:
    """Check an in-memory archive independently of the runner's helper asserts."""
    _require(e.get("schema") == "erc8183-fee-zero-model-native-v1"
             and e.get("model_behavior_tier") == "SCRIPTED_SIMULATION"
             and e.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL", "wrong archive tier/schema")
    source = e["source"]
    _require(source["commit"] == PIN and source["repository"] ==
             "https://github.com/erc-8183/base-contracts", "official upstream pin differs")
    _require(subprocess.run(["git", "rev-parse", "HEAD"], cwd=UPSTREAM, capture_output=True,
                            text=True, check=True, timeout=10).stdout.strip() == PIN,
             "local official upstream changed")
    for label, path in (("runner_sha256", ROOT / "scripts/run_erc8183_fee_control.py"),
                        ("fixture_sha256", ROOT / "src/agent_economic_trust/ap2_live_fixture.py")):
        _require(source[label] == sha256(path.read_bytes()).hexdigest(), f"{label} changed")
    case = e["case"]
    _require(case["arm"] in {"NATIVE_CONTINGENT", "CLIENT_PREPAID"}
             and case["truth"] in {"good", "bad"}
             and case["verdict"] in {"ACCEPT", "REJECT"}
             and type(case["check"]) is bool and type(case["prior_claim"]) is bool,
             "invalid case")
    _require(not case["prior_claim"] or case["arm"] == "NATIVE_CONTINGENT",
             "prior claim control must use native arm")
    expected_name = ("native-bad-prior-claim-reject" if case["prior_claim"] else
                     f"{case['arm'].lower()}-{case['truth']}-"
                     f"{'checked' if case['check'] else 'unchecked'}-{case['verdict'].lower()}")
    _require(case["name"] == expected_name and
             (not case["prior_claim"] or case["truth"] == "bad" and
              case["verdict"] == "REJECT" and case["check"]),
             "case label and assignment differ")
    _require(e["chain"]["host"] == "127.0.0.1" and e["chain"]["chain_id"] == 31337
             and e["asset"] == {"name": "MockUSDC", "decimals": 6,
                                  "supply_minor_units": 120_500_000, "real_value": 0},
             "local chain or token differs")
    roles = {key: value.lower() for key, value in e["actors"].items()}
    _require(set(roles) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
             and len(set(roles.values())) == 6, "role addresses differ")
    artifacts = {}
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        saved = e["contracts"][name]
        path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _require(Path(saved["artifact_path"]) == path and path.is_file()
                 and sha256(path.read_bytes()).hexdigest() == saved["artifact_sha256"],
                 f"{name} compiled artifact differs")
        artifact = json.loads(path.read_text())
        abi_hash = sha256(json.dumps(artifact["abi"], sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
        _require(saved["abi_sha256"] == abi_hash, f"{name} ABI differs")
        artifacts[name] = artifact
    topic_map = _event_topics(artifacts)
    token = e["contracts"]["MockUSDC"]["address"].lower()
    core = e["contracts"]["ERC1967Proxy"]["address"].lower()
    txs = e["transactions"]
    _require([t["step"] for t in txs] == _step_names(case), "transaction sequence differs")
    step = {t["step"]: t for t in txs}
    ledger: defaultdict[str, int] = defaultdict(int)
    checkpoints: dict[str, dict[str, int]] = {}
    for tx in txs:
        raw = tx["raw_transaction"]
        receipt = tx["raw_receipt"]
        expected_to = (None if tx["step"].startswith("deploy.") else
                       token if tx["step"] in {"setup.mint", "setup.approve",
                                                   "endowment.mint", "terms.client_prepay",
                                                   "check.auditor_debit"} else core)
        _require(tx["status"] == tx["expected_status"] == 1
                 and int(receipt["status"], 16) == 1
                 and raw["hash"].lower() == receipt["transactionHash"].lower()
                 == tx["transaction_hash"].lower()
                 and raw["from"].lower() == roles[tx["actor_role"]]
                 and (raw["to"] or "").lower() == (expected_to or "")
                 and int(raw["blockNumber"], 16) == tx["block_number"]
                 and int(receipt["blockNumber"], 16) == tx["block_number"]
                 and len(tx["logs"]) == len(receipt["logs"]),
                 f"{tx['step']}: raw transaction/receipt differs")
        for saved, log in zip(tx["logs"], receipt["logs"], strict=True):
            _require(saved["topics"] == log["topics"] and saved["data"] == log["data"]
                     and saved["address"].lower() == log["address"].lower(),
                     f"{tx['step']}: raw log differs")
            name = topic_map.get(log["topics"][0].lower()) if log["topics"] else None
            _require(name == saved["name"], f"{tx['step']}: event signature differs")
            log["_checked_name"] = name
            if name == "Transfer" and log["address"].lower() == token:
                _require(len(log["topics"]) == 3, "malformed ERC-20 Transfer")
                sender = ("0x" + log["topics"][1][-40:]).lower()
                receiver = ("0x" + log["topics"][2][-40:]).lower()
                amount = int(log["data"], 16)
                if sender != ZERO:
                    ledger[sender] -= amount
                ledger[receiver] += amount
        if tx["step"] in {"endowment.mint", "terms.client_prepay", "job.submit",
                          "check.auditor_debit", "job.complete", "job.reject"}:
            checkpoints[tx["step"]] = dict(ledger)
    def balance_at(checkpoint: str) -> dict[str, int]:
        state = checkpoints[checkpoint]
        return {**{role: state.get(address, 0) for role, address in roles.items()},
                "escrow": state.get(core, 0)}
    after_prepay_step = "terms.client_prepay" if case["arm"] == "CLIENT_PREPAID" else "endowment.mint"
    after_check_step = "check.auditor_debit" if case["check"] else "job.submit"
    for key, checkpoint in (("opening", "endowment.mint"), ("after_prepay", after_prepay_step),
                            ("funded", "job.submit"), ("after_check", after_check_step),
                            ("final", "job.complete" if case["verdict"] == "ACCEPT" else "job.reject")):
        saved = e[key]["balances_minor_units"]
        _require(saved == balance_at(checkpoint), f"{key}: balance snapshot differs from raw Transfers")
        _require(sum(saved.values()) == 120_500_000 and e[key]["total_supply_minor_units"] == 120_500_000,
                 f"{key}: supply does not conserve")
    terms = e["terms"]
    budget = CLIENT_MAX if case["arm"] == "NATIVE_CONTINGENT" else CLIENT_MAX - REWARD
    _require(terms == {"job_budget_minor": budget, "evaluator_fee_bp":
                       1000 if case["arm"] == "NATIVE_CONTINGENT" else 0,
                       "platform_fee_bp": 0,
                       "client_prepay_minor": REWARD if case["arm"] == "CLIENT_PREPAID" else 0,
                       "auditor_endowment_minor": ENDOWMENT, "check_price_minor": CHECK},
             "saved economic terms differ")
    _calldata(step["setup.evaluator_fee"], "setEvaluatorFee(uint256)", [1000])
    _calldata(step["terms.platform_zero"], "setPlatformFee(uint256,address)", [0, roles["treasury"]])
    if case["arm"] == "CLIENT_PREPAID":
        _calldata(step["terms.evaluator_zero"], "setEvaluatorFee(uint256)", [0])
        _calldata(step["terms.client_prepay"], "transfer(address,uint256)", [roles["evaluator"], REWARD])
        _transfer(step["terms.client_prepay"], token, roles["client"], roles["evaluator"], REWARD)
    _calldata(step["job.set_budget"], "setBudget(uint256,address,uint256,bytes)",
              [e["job_id"], token, budget])
    public_description = json.dumps({
        "study": "ERC8183_FEE_ZERO_MODEL_010", "public_claim_cents": 350,
        "acceptance_rule": "independent buyer PO minus credit must equal report"}, sort_keys=True)
    _require(public_description.encode().hex() in step["job.create"]["raw_transaction"]["input"].lower(),
             "native job description is not the truth-blind public text")
    _calldata(step["job.fund"], "fund(uint256,address,uint256,bytes)",
              [e["job_id"], token, budget])
    _transfer(step["job.fund"], token, roles["client"], core, budget)
    _transfer(step["endowment.mint"], token, ZERO, roles["evaluator"], ENDOWMENT)
    if case["check"]:
        _calldata(step["check.auditor_debit"], "transfer(address,uint256)",
                  [roles["outsider"], CHECK])
        _transfer(step["check.auditor_debit"], token, roles["evaluator"], roles["outsider"], CHECK)
    invoice = e["invoice"]
    report_digest = invoice.get("public_report_digest")
    _require(isinstance(report_digest, str)
             and re.fullmatch(r"[0-9a-f]{64}", report_digest) is not None
             and len(_logs(step["job.submit"], "JobSubmitted", address=core)) == 1
             and _logs(step["job.submit"], "JobSubmitted", address=core)[0]["data"].lower()
                 == "0x" + report_digest,
             "native submission differs from public report digest")
    expected = "PASS" if case["truth"] == "good" else "FAIL"
    buyer = {"purchase_order_amount_cents": 400 if case["truth"] == "good" else 350,
             "credit_note_amount_cents": 50,
             "net_amount_cents": 350 if case["truth"] == "good" else 300}
    _require(invoice == {"submitted_cents": 350, "public_report_digest": report_digest,
                         "oracle_status": expected,
                         "buyer_records": buyer if case["check"] else None,
                         "check_released_after_native_debit": case["check"]},
             "private invoice or check release differs")
    prejob, finaljob = e["preterminal_job"], e["final_job"]
    _require(prejob["status"] == "Submitted" and prejob["status_code"] == 2
             and prejob["client"].lower() == roles["client"]
             and prejob["provider"].lower() == roles["provider"]
             and prejob["evaluator"].lower() == roles["evaluator"]
             and prejob["payment_token"].lower() == token
             and prejob["budget_minor_units"] == budget, "submitted job state differs")
    _require(finaljob["status"] == ("Completed" if case["verdict"] == "ACCEPT" else "Rejected")
             and finaljob["settled_amount_minor_units"] == (PARTIAL if case["prior_claim"] else 0),
             "final job state differs")
    if case["prior_claim"]:
        claim = step["negative.client_settle_claim"]
        _require(prejob["settled_amount_minor_units"] == PARTIAL
                 and e["guard"] == "BLOCKED_PRIOR_CLAIM", "prior claim not blocked")
        _calldata(claim, "settleClaim(uint256,uint256,bytes32,bytes)", [e["job_id"], PARTIAL])
        _require(len(_logs(claim, "Settled", address=core)) == 1
                 and len(_logs(claim, "ClaimSettled", address=core)) == 1,
                 "direct claim settlement events missing")
        _require(_event_amount(claim, "EvaluatorFeePaid", roles["evaluator"], core, e["job_id"]) == 500_000
                 and _event_amount(claim, "PaymentReleased", roles["provider"], core, e["job_id"]) == 4_500_000,
                 "client claim fee/provider payout differs")
    else:
        _require(prejob["settled_amount_minor_units"] == 0 and e["guard"] == "PASS"
                 and all(not _logs(tx, name, address=core) for tx in txs
                         for name in ("Settled", "ClaimSettled", "ClaimApproved")),
                 "primary row has prior settlement")
    final = step["job.complete" if case["verdict"] == "ACCEPT" else "job.reject"]
    _calldata(final, ("complete" if case["verdict"] == "ACCEPT" else "reject") +
              "(uint256,bytes32,bytes)", [e["job_id"]])
    _require(final["raw_transaction"]["from"].lower() == roles["evaluator"],
             "terminal transaction not sent by evaluator")
    _require(not any(_logs(tx, "PlatformFeePaid", address=core) for tx in txs),
             "platform fee must be zero")
    if case["verdict"] == "ACCEPT":
        _require(len(_logs(final, "JobCompleted", address=core)) == 1
                 and not _logs(final, "Refunded", address=core), "completion events differ")
        eval_fee = REWARD if case["arm"] == "NATIVE_CONTINGENT" else 0
        if eval_fee:
            _require(_event_amount(final, "EvaluatorFeePaid", roles["evaluator"], core, e["job_id"]) == eval_fee,
                     "native evaluator fee differs")
            _transfer(final, token, core, roles["evaluator"], eval_fee)
        else:
            _require(not _logs(final, "EvaluatorFeePaid", address=core),
                     "prepay arm has native evaluator fee")
        _require(_event_amount(final, "PaymentReleased", roles["provider"], core, e["job_id"]) == 18_000_000,
                 "provider completion payout differs")
        _transfer(final, token, core, roles["provider"], 18_000_000)
    else:
        _require(len(_logs(final, "JobRejected", address=core)) == 1
                 and not _logs(final, "EvaluatorFeePaid", address=core)
                 and not _logs(final, "PaymentReleased", address=core),
                 "rejection paid a final fee or provider")
        refund = budget - (PARTIAL if case["prior_claim"] else 0)
        _require(_event_amount(final, "Refunded", roles["client"], core, e["job_id"]) == refund,
                 "rejection refund differs")
        _transfer(final, token, core, roles["client"], refund)
    opening = e["opening"]["balances_minor_units"]
    close = e["final"]["balances_minor_units"]
    client_loss = (CLIENT_MAX if case["verdict"] == "ACCEPT" else
                   PARTIAL if case["prior_claim"] else
                   REWARD if case["arm"] == "CLIENT_PREPAID" else 0)
    provider_gain = (18_000_000 if case["verdict"] == "ACCEPT" else
                     4_500_000 if case["prior_claim"] else 0)
    evaluator_gain = (REWARD if case["verdict"] == "ACCEPT" or case["arm"] == "CLIENT_PREPAID"
                      else 500_000 if case["prior_claim"] else 0) - (CHECK if case["check"] else 0)
    _require(close["client"] - opening["client"] == -client_loss
             and close["provider"] - opening["provider"] == provider_gain
             and close["evaluator"] - opening["evaluator"] == evaluator_gain
             and close["outsider"] - opening["outsider"] == (CHECK if case["check"] else 0)
             and close["escrow"] == 0 and close["treasury"] == 0,
             "economic balance deltas differ")
    return {"case": case["name"], "status": "PASS", "client_loss_minor": client_loss,
            "provider_gain_minor": provider_gain, "evaluator_net_minor": evaluator_gain,
            "prior_claim_blocked": case["prior_claim"]}


def verify_directory(path: Path) -> dict[str, Any]:
    summary = json.loads((path / "summary.json").read_text())
    _require(summary["schema"] == "erc8183-fee-zero-model-summary-v1"
             and summary["model_calls"] == 0 and summary["real_spend_usd"] == "0"
             and summary["native_chains"] == 9 and len(summary["cases"]) == 9,
             "control summary differs")
    results = []
    for entry in summary["cases"]:
        case_path = path / entry["name"]
        raw = (case_path / "evidence.json").read_bytes()
        digest = sha256(raw).hexdigest()
        _require(digest == entry["evidence_sha256"]
                 == (case_path / "evidence.sha256").read_text().strip(),
                 "case evidence digest differs")
        result = verify_record(json.loads(raw))
        _require(result["case"] == entry["name"], "case identity differs")
        results.append(result)
    expected = {f"{arm}-{label}" for arm in ("native_contingent", "client_prepaid")
                for label in ("good-checked-accept", "bad-checked-reject",
                              "bad-unchecked-accept", "good-unchecked-reject")}
    expected.add("native-bad-prior-claim-reject")
    _require({x["case"] for x in results} == expected, "balanced control cells differ")
    digests = {json.loads((path / entry["name"] / "evidence.json").read_text())
               ["invoice"]["public_report_digest"] for entry in summary["cases"]}
    _require(len(digests) == 1, "GOOD/BAD native submitted report digest differs")
    return {"schema": "erc8183-fee-control-verification-v1", "status": "PASS",
            "cases": results, "execution_tier": "SCRIPTED_SIMULATION+NATIVE_LOCAL_PROTOCOL",
            "live_agent_collusion_evidence": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_directory(args.path), sort_keys=True))


if __name__ == "__main__":
    main()
