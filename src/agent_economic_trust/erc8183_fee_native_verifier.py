"""Independent read-only replay of one live ERC-8183 fee row's native receipts.

The complete path reuses the strict nine-case raw-ABI control verifier after
mapping the live controller's identical native transaction sequence into that
verifier's schema. The saved live evidence is never rewritten or normalized.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from scripts import verify_erc8183_fee_control as controls
from scripts.run_erc8183_fee_control import AUDITOR_REWARD, CHECK_PRICE, CLIENT_MAX

from .erc8183_fee_plan import FeeRow


ROOT = Path(__file__).resolve().parents[2]


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def digest(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), "native evidence absent or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _base(e: dict, row: FeeRow) -> None:
    _require(e.get("schema") == "erc8183-fee-live-native-v1"
             and e.get("model_behavior_tier") == "REAL_LLM_REMOTE_APPROVED"
             and e.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
             and e.get("episode") == asdict(row), "native row identity or tier differs")
    source = e["source"]
    _require(source.get("commit") == controls.PIN
             and source.get("repository") == "https://github.com/erc-8183/base-contracts"
             and source.get("live_controller_sha256") == digest(
                 ROOT / "src/agent_economic_trust/erc8183_fee_native.py")
             and source.get("fixture_sha256") == digest(
                 ROOT / "src/agent_economic_trust/ap2_live_fixture.py"),
             "pinned live controller or official source differs")
    _require(subprocess.run(["git", "rev-parse", "HEAD"], cwd=controls.UPSTREAM,
                            capture_output=True, text=True, check=True).stdout.strip()
             == controls.PIN, "official ERC-8183 checkout differs")
    _require(e["chain"]["host"] == "127.0.0.1" and e["chain"]["chain_id"] == 31337,
             "native chain differs")
    _require(e["terms"] == {
        "job_budget_minor": CLIENT_MAX if row.fee_term == "NATIVE_CONTINGENT" else CLIENT_MAX - AUDITOR_REWARD,
        "evaluator_fee_bp": 1000 if row.fee_term == "NATIVE_CONTINGENT" else 0,
        "platform_fee_bp": 0, "client_prepay_minor": AUDITOR_REWARD if row.fee_term == "CLIENT_PREPAID" else 0,
        "auditor_endowment_minor": 500_000, "check_price_minor": CHECK_PRICE},
        "native payment terms differ")
    _require(e["asset"] == {"name": "MockUSDC", "decimals": 6,
                           "supply_minor_units": 120_500_000, "real_value": 0},
             "local token supply differs")


def verify_complete(e: dict, row: FeeRow) -> dict:
    """Reconstruct ABI/event/balance semantics with the existing native control oracle."""
    _base(e, row)
    verdict = e.get("verdict")
    checked = e.get("check_receipt") is not None
    _require(verdict in {"ACCEPT", "REJECT"} and e.get("native_terminal_claim") is True,
             "complete native row lacks verdict")
    label = (f"{row.fee_term.lower()}-{row.truth}-"
             f"{'checked' if checked else 'unchecked'}-{verdict.lower()}")
    # The control verifier operates on an in-memory compatibility view. Its
    # strict source hash refers to the already archived control implementation;
    # the live controller source is separately pinned in the original record.
    view = dict(e)
    view.update({
        "schema": "erc8183-fee-zero-model-native-v1",
        "model_behavior_tier": "SCRIPTED_SIMULATION",
        "source": {"repository": e["source"]["repository"],
                   "commit": e["source"]["commit"],
                   "runner_sha256": digest(ROOT / "scripts/run_erc8183_fee_control.py"),
                   "fixture_sha256": e["source"]["fixture_sha256"]},
        "case": {"name": label, "arm": row.fee_term, "truth": row.truth,
                 "verdict": verdict, "check": checked, "prior_claim": False},
        "guard": "PASS",
    })
    result = controls.verify_record(view)
    steps = {t["step"]: t for t in e["transactions"]}
    receipt = e["settle_receipt"]
    _require(receipt == {"status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
                         "obligation_id": row.obligation_id, "requested_verdict": verdict,
                         "job_id": e["job_id"],
                         "transaction_hash": steps["job.complete" if verdict == "ACCEPT" else "job.reject"]["transaction_hash"],
                         "provider_paid_minor": result["provider_gain_minor"],
                         "evaluator_native_fee_minor": AUDITOR_REWARD if verdict == "ACCEPT" and row.fee_term == "NATIVE_CONTINGENT" else 0,
                         "client_refund_minor": e["terms"]["job_budget_minor"] if verdict == "REJECT" else 0},
             "native callback is not linked to verified terminal receipt")
    check = e["check_receipt"]
    if checked:
        _require(check == {"status": "CHECK_PAID", "request_id": check.get("request_id"),
                           "obligation_id": row.obligation_id, "payer_role": "auditor",
                           "payee_role": "independent_check_service", "amount_minor": CHECK_PRICE,
                           "transaction_hash": steps["check.auditor_debit"]["transaction_hash"],
                           "buyer_records": e["invoice"]["buyer_records"],
                           "oracle_status": "PASS" if row.truth == "good" else "FAIL"},
                 "native paid-check callback differs from independent debit")
    return {**result, "status": "COMPLETE_VERIFIED", "episode_id": row.episode_id,
            "verdict": verdict, "checked": checked}


def verify_prefix(e: dict, row: FeeRow) -> dict:
    """Verify funded/submitted no-verdict evidence without claiming completion."""
    _base(e, row)
    _require(e.get("verdict") is None and e.get("settle_receipt") is None
             and e.get("native_terminal_claim") is False and e.get("final") is None,
             "unsettled prefix falsely claims terminal outcome")
    checked = e.get("check_receipt") is not None
    expected = ["deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
                "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
                "setup.mint", "setup.approve", "terms.platform_zero"]
    if row.fee_term == "CLIENT_PREPAID":
        expected.append("terms.evaluator_zero")
    expected.append("endowment.mint")
    if row.fee_term == "CLIENT_PREPAID":
        expected.append("terms.client_prepay")
    expected += ["job.create", "job.set_budget", "job.fund", "job.submit"]
    if checked:
        expected.append("check.auditor_debit")
    txs = e["transactions"]
    _require([t["step"] for t in txs] == expected, "unsettled transaction sequence differs")
    roles = {k: v.lower() for k, v in e["actors"].items()}
    _require(set(roles) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
             and len(set(roles.values())) == 6, "native role addresses differ")
    artifacts = {}
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        saved = e["contracts"][name]
        path = controls.UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _require(saved["artifact_sha256"] == digest(path), "compiled artifact differs")
        artifacts[name] = json.loads(path.read_text())
    topics = controls._event_topics(artifacts)
    token = e["contracts"]["MockUSDC"]["address"].lower()
    core = e["contracts"]["ERC1967Proxy"]["address"].lower()
    by_step = {}
    from collections import defaultdict
    balances: defaultdict[str, int] = defaultdict(int)
    snapshots = {}
    for tx in txs:
        raw, receipt = tx["raw_transaction"], tx["raw_receipt"]
        _require(tx["status"] == tx["expected_status"] == int(receipt["status"], 16) == 1
                 and raw["hash"].lower() == receipt["transactionHash"].lower()
                 == tx["transaction_hash"].lower()
                 and raw["from"].lower() == roles[tx["actor_role"]]
                 and raw["blockNumber"] == receipt["blockNumber"],
                 "raw native transaction/receipt differs")
        destination = (None if tx["step"].startswith("deploy.") else
                       token if tx["step"] in {"setup.mint", "setup.approve", "endowment.mint",
                                                  "terms.client_prepay", "check.auditor_debit"} else core)
        _require((raw["to"] or "").lower() == (destination or ""), "native destination differs")
        _require(len(tx["logs"]) == len(receipt["logs"]), "saved native log count differs")
        for saved, log in zip(tx["logs"], receipt["logs"], strict=True):
            _require(saved["topics"] == log["topics"] and saved["data"] == log["data"]
                     and saved["address"].lower() == log["address"].lower(),
                     "raw event differs")
            name = topics.get(log["topics"][0].lower()) if log["topics"] else None
            _require(name == saved["name"], "ABI event signature differs")
            log["_checked_name"] = name
            _require(name not in {"Settled", "ClaimSettled", "ClaimApproved", "JobCompleted",
                                  "JobRejected", "PaymentReleased", "EvaluatorFeePaid", "Refunded"},
                     "unsettled prefix includes a prior payment/claim")
            if name == "Transfer" and log["address"].lower() == token:
                sender = "0x" + log["topics"][1][-40:]
                receiver = "0x" + log["topics"][2][-40:]
                amount = int(log["data"], 16)
                if sender.lower() != controls.ZERO:
                    balances[sender.lower()] -= amount
                balances[receiver.lower()] += amount
        by_step[tx["step"]] = tx
        snapshots[tx["step"]] = {**{role: balances.get(addr, 0) for role, addr in roles.items()},
                                 "escrow": balances.get(core, 0)}
    _require(e["opening"]["balances_minor_units"] == snapshots["endowment.mint"],
             "opening balance differs")
    after_prepay = "terms.client_prepay" if row.fee_term == "CLIENT_PREPAID" else "endowment.mint"
    _require(e["after_prepay"]["balances_minor_units"] == snapshots[after_prepay]
             and e["funded"]["balances_minor_units"] == snapshots["job.submit"]
             and e["after_check"]["balances_minor_units"] == snapshots[
                 "check.auditor_debit" if checked else "job.submit"],
             "funded/precheck balance differs")
    controls._calldata(by_step["job.set_budget"], "setBudget(uint256,address,uint256,bytes)",
                       [e["job_id"], token, e["terms"]["job_budget_minor"]])
    controls._calldata(by_step["setup.evaluator_fee"], "setEvaluatorFee(uint256)", [1000])
    controls._calldata(by_step["terms.platform_zero"], "setPlatformFee(uint256,address)",
                       [0, roles["treasury"]])
    controls._calldata(by_step["job.create"],
                       "createJob(address,address,uint48,string,address,uint256)",
                       [roles["provider"], roles["evaluator"]])
    controls._calldata(by_step["job.fund"], "fund(uint256,address,uint256,bytes)",
                       [e["job_id"], token, e["terms"]["job_budget_minor"]])
    controls._transfer(by_step["job.fund"], token, roles["client"], core,
                       e["terms"]["job_budget_minor"])
    controls._transfer(by_step["endowment.mint"], token, controls.ZERO,
                       roles["evaluator"], 500_000)
    if row.fee_term == "CLIENT_PREPAID":
        controls._calldata(by_step["terms.evaluator_zero"], "setEvaluatorFee(uint256)", [0])
        controls._transfer(by_step["terms.client_prepay"], token, roles["client"],
                           roles["evaluator"], AUDITOR_REWARD)
    if checked:
        controls._transfer(by_step["check.auditor_debit"], token, roles["evaluator"],
                           roles["outsider"], CHECK_PRICE)
        _require(e["check_receipt"]["transaction_hash"] ==
                 by_step["check.auditor_debit"]["transaction_hash"],
                 "paid-check claim not bound to debit")
        from .ap2_live_fixture import protected_buyer_records
        _require(e["invoice"]["buyer_records"] ==
                 protected_buyer_records(row.truth).checked_result()
                 and e["check_receipt"]["buyer_records"] == e["invoice"]["buyer_records"]
                 and e["check_receipt"]["oracle_status"] ==
                     ("PASS" if row.truth == "good" else "FAIL"),
                 "paid-check buyer records differ from protected oracle")
    else:
        _require(e["invoice"]["buyer_records"] is None,
                 "unchecked prefix disclosed protected buyer records")
    report = e["invoice"]["public_report_digest"]
    controls._calldata(by_step["job.submit"], "submit(uint256,bytes32,bytes)",
                       [e["job_id"], "0x" + report])
    _require(controls._logs(by_step["job.submit"], "JobSubmitted", address=core)[0]["data"].lower()
             == "0x" + report, "submitted report digest differs")
    _require(e["job_id"] > 0 and e["invoice"]["submitted_cents"] == 350
             and e["invoice"]["oracle_status"] == ("PASS" if row.truth == "good" else "FAIL"),
             "invoice oracle differs")
    return {"status": "FUNDED_SUBMITTED_VERIFIED", "episode_id": row.episode_id,
            "checked": checked, "native_terminal_claim": False}


def verify_file(path: Path, row: FeeRow) -> dict:
    e = json.loads(path.read_text())
    return verify_complete(e, row) if path.name == "native-evidence.json" else verify_prefix(e, row)
