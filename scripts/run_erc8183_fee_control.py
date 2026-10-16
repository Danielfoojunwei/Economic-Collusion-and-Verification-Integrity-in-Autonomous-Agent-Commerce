#!/usr/bin/env python3
"""Zero-model, native ERC-8183 evaluator-fee versus client-prepay controls.

Every case runs on its own disposable localhost Anvil chain. All amounts are
valueless local MockUSDC. Decisions are scripted controls, not LLM behavior.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

from run_erc8183_local import (ANVIL, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP,
                               PIN, SOLC, SUBMODULE_PINS, UPSTREAM, ZERO, NativeRun,
                               _command, _free_port, _hex_int)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.ap2_live_fixture import invoice_case, protected_buyer_records
from agent_economic_trust.core import OracleStatus, oracle_score

CLIENT_MAX = 20_000_000
AUDITOR_REWARD = 2_000_000
AUDITOR_ENDOWMENT = 500_000
CHECK_PRICE = 200_000
PARTIAL_CLAIM = 5_000_000
NATIVE = "NATIVE_CONTINGENT"
PREPAID = "CLIENT_PREPAID"


@dataclass(frozen=True)
class Case:
    name: str
    arm: str
    truth: str
    verdict: str
    check: bool
    prior_claim: bool = False


CASES = tuple(
    Case(f"{arm.lower()}-{label}", arm, truth, verdict, checked)
    for arm in (NATIVE, PREPAID)
    for label, truth, verdict, checked in (
        ("good-checked-accept", "good", "ACCEPT", True),
        ("bad-checked-reject", "bad", "REJECT", True),
        ("bad-unchecked-accept", "bad", "ACCEPT", False),
        ("good-unchecked-reject", "good", "REJECT", False),
    )
) + (Case("native-bad-prior-claim-reject", NATIVE, "bad", "REJECT", True, True),)


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def _zero_prior_claim_guard(helper: NativeRun, job_id: int) -> None:
    job = helper.job(job_id)
    if (job["status"] != "Submitted" or job["settled_amount_minor_units"] != 0
            or int(helper.pending_claim(job_id), 16) != 0
            or any(log["name"] in {"Settled", "ClaimSettled", "ClaimApproved"}
                   for tx in helper.transactions for log in tx["logs"])):
        raise ValueError("prior claim or settlement prevents clean final-fee attribution")


def _create_funded(helper: NativeRun, case: Case, amount: int, digest: str) -> int:
    job_id = helper.uint(helper.core, "jobCounter()") + 1
    expiry = helper.now() + 3601
    description = json.dumps({"study": "ERC8183_FEE_ZERO_MODEL_010",
                              "public_claim_cents": 350,
                              "acceptance_rule": "independent buyer PO minus credit must equal report"},
                             sort_keys=True)
    helper.send("job.create", "client", "createJob(address,address,uint48,string,address,uint256)",
                helper.roles["provider"], helper.roles["evaluator"], expiry, description,
                ZERO, 0, events=("JobCreated",))
    helper.send("job.set_budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                job_id, helper.token, amount, "0x", events=("BudgetSet",))
    helper.send("job.fund", "client", "fund(uint256,address,uint256,bytes)",
                job_id, helper.token, amount, "0x", events=("JobFunded", "Transfer"))
    if helper.job(job_id)["status"] != "Funded":
        raise AssertionError("job failed to enter Funded")
    if case.prior_claim:
        helper.send("negative.client_settle_claim", "client",
                    "settleClaim(uint256,uint256,bytes32,bytes)", job_id, PARTIAL_CLAIM,
                    "0x" + digest, "0x", events=("Settled", "ClaimSettled",
                                                    "EvaluatorFeePaid", "PaymentReleased"))
    helper.submit("job", job_id, digest)
    return job_id


def _run_case(output: Path, case: Case) -> dict:
    path = output / case.name
    path.mkdir(parents=True, exist_ok=False)
    port = _free_port()
    helper = NativeRun(path, port)
    seed = int.from_bytes(sha256(case.name.encode()).digest()[:8], "big")
    with (path / "anvil.log").open("w", encoding="utf-8") as anvil_log:
        process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(port), "--chain-id",
            str(CHAIN_ID), "--hardfork", "cancun", "--timestamp", str(GENESIS_TIMESTAMP),
            "--accounts", "6", "--balance", "1000", "--mnemonic-seed-unsafe", str(seed),
            "--quiet",
        ], stdout=anvil_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("local Anvil terminated")
                try:
                    if _hex_int(helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise RuntimeError("wrong local chain ID")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil not ready")
                    time.sleep(0.05)
            accounts = helper.rpc.call("eth_accounts")
            if len(accounts) != 6 or len({a.lower() for a in accounts}) != 6:
                raise AssertionError("six unique local accounts required")
            helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                     "treasury", "outsider"), accounts, strict=True))
            helper.deploy()
            # The old G2 helper deploys 1000/500 BP. Set these before this
            # fresh job; no fee-admin transaction is allowed after funding.
            helper.send("terms.platform_zero", "admin", "setPlatformFee(uint256,address)",
                        0, helper.roles["treasury"], events=("PlatformFeeUpdated",))
            if case.arm == PREPAID:
                helper.send("terms.evaluator_zero", "admin", "setEvaluatorFee(uint256)",
                            0, events=("EvaluatorFeeUpdated",))
            helper.tx("endowment.mint", "admin", helper.token,
                      helper.calldata("mint(address,uint256)", helper.roles["evaluator"],
                                      AUDITOR_ENDOWMENT), events=("Transfer",))
            helper.initial_supply += AUDITOR_ENDOWMENT
            opening = helper.snapshot()
            if case.arm == PREPAID:
                helper.tx("terms.client_prepay", "client", helper.token,
                          helper.calldata("transfer(address,uint256)",
                                          helper.roles["evaluator"], AUDITOR_REWARD),
                          events=("Transfer",))
            after_prepay = helper.snapshot()
            fixture, artifact = invoice_case(case.truth)
            oracle = oracle_score(fixture, artifact)
            expected = OracleStatus.PASS if case.truth == "good" else OracleStatus.FAIL
            if oracle.status is not expected or artifact.submitted_amount_cents != 350:
                raise AssertionError("protected equal-claim fixture changed")
            budget = CLIENT_MAX if case.arm == NATIVE else CLIENT_MAX - AUDITOR_REWARD
            # Same public submitted deliverable digest in GOOD and BAD worlds.
            # The protected fixture's task ID never enters native job data.
            public_digest = _hash({"task_prompt": fixture.public_task()["task_prompt"],
                                   "submitted_amount_cents": artifact.submitted_amount_cents})
            job_id = _create_funded(helper, case, budget, public_digest)
            funded = helper.snapshot()
            if case.check:
                helper.tx("check.auditor_debit", "evaluator", helper.token,
                          helper.calldata("transfer(address,uint256)",
                                          helper.roles["outsider"], CHECK_PRICE),
                          events=("Transfer",))
            after_check = helper.snapshot()
            before_guard_tx_count = len(helper.transactions)
            try:
                _zero_prior_claim_guard(helper, job_id)
                guard = "PASS"
            except ValueError:
                guard = "BLOCKED_PRIOR_CLAIM"
            if len(helper.transactions) != before_guard_tx_count:
                raise AssertionError("guard initiated a native transaction")
            if (guard == "PASS") is case.prior_claim:
                raise AssertionError("prior-claim guard differs from scenario")
            preterminal_job = helper.job(job_id)
            # The negative row performs a mechanical REJECT after proving that
            # the clean-attribution guard blocks its primary-study dispatch.
            reason = "0x" + _hash({"case": case.name, "verdict": case.verdict})
            if case.verdict == "ACCEPT":
                helper.send("job.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                            job_id, reason, "0x", events=("JobCompleted", "PaymentReleased",
                                                         "EvaluatorFeePaid" if case.arm == NATIVE
                                                         else "JobCompleted"))
            else:
                helper.send("job.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                            job_id, reason, "0x", events=("JobRejected", "Refunded"))
            final = helper.snapshot()
            final_job = helper.job(job_id)
            if final_job["status"] != ("Completed" if case.verdict == "ACCEPT" else "Rejected"):
                raise AssertionError("native final status differs")
            for tx in helper.transactions:
                raw_tx = helper.rpc.call("eth_getTransactionByHash", [tx["transaction_hash"]])
                if raw_tx is None or raw_tx["hash"].lower() != tx["transaction_hash"].lower():
                    raise AssertionError("missing raw local transaction")
                tx["raw_transaction"] = raw_tx
            evidence = {
                "schema": "erc8183-fee-zero-model-native-v1",
                "model_behavior_tier": "SCRIPTED_SIMULATION",
                "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                "source": {"repository": "https://github.com/erc-8183/base-contracts",
                           "commit": PIN, "submodules": SUBMODULE_PINS,
                           "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                           "fixture_sha256": sha256((ROOT / "src/agent_economic_trust/ap2_live_fixture.py").read_bytes()).hexdigest()},
                "chain": {"host": "127.0.0.1", "port": port, "chain_id": CHAIN_ID,
                          "genesis_timestamp": GENESIS_TIMESTAMP},
                "case": asdict(case), "actors": helper.roles,
                "contracts": helper.contracts,
                "asset": {"name": "MockUSDC", "decimals": 6,
                          "supply_minor_units": helper.initial_supply, "real_value": 0},
                "terms": {"job_budget_minor": budget,
                          "evaluator_fee_bp": 1000 if case.arm == NATIVE else 0,
                          "platform_fee_bp": 0,
                          "client_prepay_minor": AUDITOR_REWARD if case.arm == PREPAID else 0,
                          "auditor_endowment_minor": AUDITOR_ENDOWMENT,
                          "check_price_minor": CHECK_PRICE},
                "invoice": {"submitted_cents": 350,
                            "public_report_digest": public_digest,
                            "oracle_status": oracle.status.value,
                            "buyer_records": protected_buyer_records(case.truth).checked_result()
                            if case.check else None,
                            "check_released_after_native_debit": case.check},
                "job_id": job_id, "opening": opening, "after_prepay": after_prepay,
                "funded": funded, "after_check": after_check,
                "preterminal_job": preterminal_job, "guard": guard,
                "final_job": final_job, "final": final,
                "transactions": helper.transactions,
                "limitations": ["Scripted decisions, not model behavior or collusion.",
                                "Local valueless token and disposable chain only.",
                                "Prior-claim negative bypasses the primary guard only to demonstrate native payment semantics."],
            }
            raw = json.dumps(evidence, sort_keys=True, indent=2).encode() + b"\n"
            (path / "evidence.json").write_bytes(raw)
            (path / "evidence.sha256").write_text(sha256(raw).hexdigest() + "\n")
            return {"name": case.name, "evidence_sha256": sha256(raw).hexdigest(),
                    "transactions": len(helper.transactions), "guard": guard}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite native evidence")
    for executable in (CAST, FORGE, ANVIL, SOLC):
        if not executable.is_file():
            raise FileNotFoundError(executable)
    if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN:
        raise RuntimeError("ERC-8183 upstream pin differs")
    if _command("git", "status", "--porcelain", cwd=UPSTREAM):
        raise RuntimeError("ERC-8183 upstream tracked files differ")
    for name, expected in SUBMODULE_PINS.items():
        if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / name) != expected:
            raise RuntimeError(f"ERC-8183 submodule pin differs: {name}")
    args.output.mkdir(parents=True)
    with (args.output / "forge-build.log").open("w", encoding="utf-8") as build:
        subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                       cwd=UPSTREAM, stdout=build, stderr=subprocess.STDOUT, check=True, timeout=120)
    rows = [_run_case(args.output, case) for case in CASES]
    summary = {"schema": "erc8183-fee-zero-model-summary-v1", "cases": rows,
               "model_calls": 0, "real_spend_usd": "0", "native_chains": len(rows)}
    (args.output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
