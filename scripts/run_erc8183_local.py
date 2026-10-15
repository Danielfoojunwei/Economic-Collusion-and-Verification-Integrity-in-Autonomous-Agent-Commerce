#!/usr/bin/env python3
"""Exercise pinned ERC-8183 contracts on a disposable, localhost-only Anvil chain.

All ERC-20 units are minted by the upstream MockUSDC test contract. The auditor
decisions in this script are fixed controls, not observed LLM behavior. Raw native
receipts, event log indexes, state reads, and balances are saved for review.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT.parent / "upstreams" / "erc8183"
TOOLS = ROOT.parent / ".tools"
CAST = TOOLS / "foundry" / "v1.8.5" / "cast"
FORGE = TOOLS / "foundry" / "v1.8.5" / "forge"
ANVIL = TOOLS / "foundry" / "v1.8.5" / "anvil"
SOLC = TOOLS / "solc" / "v0.8.28" / "solc"
PIN = "142e669c1fd318486a4628395b629f033654dd06"
SUBMODULE_PINS = {
    "lib/forge-std": "620536fa5277db4e3fd46772d5cbc1ea0696fb43",
    "lib/openzeppelin-contracts": "5fd1781b1454fd1ef8e722282f86f9293cacf256",
    "lib/openzeppelin-contracts-upgradeable": "7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf",
}
ZERO = "0x" + "00" * 20
UNIT = 1_000_000  # upstream MockUSDC uses six decimals
BUDGET = 20 * UNIT
GENESIS_TIMESTAMP = 1_760_000_000
CHAIN_ID = 31_337
STATUS = ("Open", "Funded", "Submitted", "Completed", "Rejected", "Expired")


def _command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _hex_int(value: str) -> int:
    return int(value, 16)


def _address(word: str) -> str:
    return "0x" + word[-40:]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RPC:
    """JSON-RPC client with a fixed loopback destination and no proxy fallback."""

    def __init__(self, port: int):
        if not 1 <= port <= 65535:
            raise ValueError("invalid loopback port")
        self.port = port
        self.next_id = 1

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or []})
        self.next_id += 1
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/", payload, {"Content-Type": "application/json"})
            response = conn.getresponse()
            body = json.loads(response.read())
        finally:
            conn.close()
        if response.status != 200 or "error" in body:
            raise RuntimeError(f"local RPC {method} failed: {body.get('error', response.status)}")
        return body["result"]


class NativeRun:
    def __init__(self, output: Path, port: int):
        self.output = output
        self.port = port
        self.rpc = RPC(port)
        self.transactions: list[dict[str, Any]] = []
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.contracts: dict[str, dict[str, Any]] = {}
        self.abi_topics: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.token = ""
        self.core = ""
        self.initial_supply = 0

    def calldata(self, signature: str, *args: object) -> str:
        return _command(str(CAST), "calldata", signature, *(str(arg) for arg in args))

    def read(self, to: str, signature: str, *args: object) -> str:
        return self.rpc.call("eth_call", [{"to": to, "data": self.calldata(signature, *args)}, "latest"])

    def uint(self, to: str, signature: str, *args: object) -> int:
        return _hex_int(self.read(to, signature, *args))

    def _event_names(self, artifact: dict[str, Any]) -> None:
        for entry in artifact["abi"]:
            if entry["type"] != "event" or entry.get("anonymous", False):
                continue
            signature = entry["name"] + "(" + ",".join(item["type"] for item in entry["inputs"]) + ")"
            topic = _command(str(CAST), "keccak", signature).lower()
            self.abi_topics[topic] = entry["name"]

    def tx(self, step: str, actor: str, to: str | None, data: str, *, status: int = 1,
           events: tuple[str, ...] = ()) -> dict[str, Any]:
        request: dict[str, str] = {
            "from": self.roles[actor], "data": data, "gas": hex(8_000_000),
        }
        if to is not None:
            request["to"] = to
        tx_hash = self.rpc.call("eth_sendTransaction", [request])
        deadline = time.monotonic() + 15
        while True:
            receipt = self.rpc.call("eth_getTransactionReceipt", [tx_hash])
            if receipt is not None:
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"no receipt for {step}: {tx_hash}")
            time.sleep(0.05)
        actual = _hex_int(receipt["status"])
        if actual != status:
            raise AssertionError(f"{step}: expected receipt status {status}, got {actual}")
        logs = [
            {"log_index": _hex_int(log["logIndex"]), "address": log["address"],
             "name": self.abi_topics.get(log["topics"][0].lower(), "UNKNOWN") if log["topics"] else "UNKNOWN",
             "topics": log["topics"], "data": log["data"]}
            for log in receipt["logs"]
        ]
        observed = {log["name"] for log in logs}
        if not set(events).issubset(observed):
            raise AssertionError(f"{step}: missing events {set(events) - observed}")
        if status == 0 and logs:
            raise AssertionError(f"{step}: reverted transaction emitted retained logs")
        block = self.rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
        self.transactions.append({
            "step": step, "actor_role": actor, "expected_status": status,
            "status": actual, "transaction_hash": tx_hash,
            "block_number": _hex_int(receipt["blockNumber"]),
            "block_timestamp": _hex_int(block["timestamp"]),
            "gas_used": _hex_int(receipt["gasUsed"]),
            "contract_address": receipt.get("contractAddress"),
            "logs": logs, "raw_receipt": receipt,
        })
        return receipt

    def send(self, step: str, actor: str, signature: str, *args: object,
             status: int = 1, events: tuple[str, ...] = ()) -> dict[str, Any]:
        return self.tx(step, actor, self.core, self.calldata(signature, *args), status=status, events=events)

    def balance(self, address: str) -> int:
        return self.uint(self.token, "balanceOf(address)", address)

    def snapshot(self) -> dict[str, Any]:
        balances = {role: self.balance(address) for role, address in self.roles.items()}
        balances["escrow"] = self.balance(self.core)
        supply = self.uint(self.token, "totalSupply()")
        if supply != self.initial_supply or sum(balances.values()) != supply:
            raise AssertionError("MockUSDC balance conservation failed")
        return {"balances_minor_units": balances, "total_supply_minor_units": supply}

    def job(self, job_id: int) -> dict[str, Any]:
        raw = self.read(self.core, "jobs(uint256)", job_id)[2:]
        words = [raw[pos:pos + 64] for pos in range(0, len(raw), 64)]
        if len(words) < 13:
            raise AssertionError("incomplete jobs() response")
        status = int(words[1], 16)
        return {
            "client": _address(words[0]), "status": STATUS[status], "status_code": status,
            "provider": _address(words[2]), "expired_at": int(words[3], 16),
            "evaluator": _address(words[4]), "submitted_at": int(words[5], 16),
            "budget_minor_units": int(words[6], 16), "payment_token": _address(words[8]),
            "settled_amount_minor_units": int(words[11], 16),
        }

    def pending_claim(self, job_id: int) -> str:
        return self.read(self.core, "pendingClaimHash(uint256)", job_id)

    def now(self) -> int:
        return _hex_int(self.rpc.call("eth_getBlockByNumber", ["latest", False])["timestamp"])

    def next_timestamp(self, timestamp: int) -> None:
        if timestamp <= self.now():
            raise AssertionError("test time must move forward")
        self.rpc.call("evm_setNextBlockTimestamp", [hex(timestamp)])

    def assert_delta(self, before: dict[str, Any], after: dict[str, Any], **expected: int) -> None:
        a = after["balances_minor_units"]
        b = before["balances_minor_units"]
        for role in b:
            delta = a[role] - b[role]
            if delta != expected.get(role, 0):
                raise AssertionError(f"{role}: expected token delta {expected.get(role, 0)}, got {delta}")

    def create_funded(self, prefix: str, description: str) -> tuple[int, int]:
        job_id = self.uint(self.core, "jobCounter()") + 1
        expiry = self.now() + 3601
        self.send(prefix + ".create", "client", "createJob(address,address,uint48,string,address,uint256)",
                  self.roles["provider"], self.roles["evaluator"], expiry, description, ZERO, 0,
                  events=("JobCreated",))
        if self.uint(self.core, "jobCounter()") != job_id or self.job(job_id)["status"] != "Open":
            raise AssertionError("native job creation state mismatch")
        self.send(prefix + ".budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("BudgetSet",))
        self.send(prefix + ".fund", "client", "fund(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("JobFunded", "Transfer"))
        if self.job(job_id)["status"] != "Funded":
            raise AssertionError("native fund state mismatch")
        return job_id, expiry

    def submit(self, prefix: str, job_id: int, digest: str) -> None:
        receipt = self.send(prefix + ".submit", "provider", "submit(uint256,bytes32,bytes)",
                            job_id, "0x" + digest, "0x", events=("JobSubmitted",))
        submitted = next(log for log in receipt["logs"] if self.abi_topics.get(log["topics"][0].lower()) == "JobSubmitted")
        if submitted["data"].lower() != "0x" + digest.lower():
            raise AssertionError("on-chain deliverable differs from artifact digest")
        if self.job(job_id)["status"] != "Submitted":
            raise AssertionError("native submit state mismatch")

    def deploy(self) -> None:
        def load(name: str) -> tuple[Path, dict[str, Any]]:
            path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
            return path, json.loads(path.read_text(encoding="utf-8"))

        token_path, token_artifact = load("MockUSDC")
        core_path, core_artifact = load("ERC8183")
        proxy_path, proxy_artifact = load("ERC1967Proxy")
        for artifact in (token_artifact, core_artifact, proxy_artifact):
            self._event_names(artifact)
        for name, path, artifact in (
            ("MockUSDC", token_path, token_artifact),
            ("ERC8183", core_path, core_artifact),
            ("ERC1967Proxy", proxy_path, proxy_artifact),
        ):
            abi_bytes = json.dumps(artifact["abi"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.contracts[name] = {"artifact_path": str(path), "artifact_sha256": _sha256(path),
                                    "abi_sha256": sha256(abi_bytes).hexdigest()}
        self.token = self.tx("deploy.mock_usdc", "admin", None, token_artifact["bytecode"]["object"])["contractAddress"]
        implementation = self.tx("deploy.implementation", "admin", None, core_artifact["bytecode"]["object"])["contractAddress"]
        init_data = self.calldata("initialize(address,address)", self.roles["treasury"], self.roles["admin"])
        constructor_args = _command(str(CAST), "abi-encode", "f(address,bytes)", implementation, init_data)
        proxy_code = proxy_artifact["bytecode"]["object"] + constructor_args[2:]
        self.core = self.tx("deploy.proxy", "admin", None, proxy_code)["contractAddress"]
        for name, address in (("MockUSDC", self.token), ("ERC8183", implementation), ("ERC1967Proxy", self.core)):
            code = bytes.fromhex(self.rpc.call("eth_getCode", [address, "latest"])[2:])
            if not code:
                raise AssertionError(f"{name}: no deployed runtime code")
            self.contracts[name].update({"address": address, "runtime_code_sha256": sha256(code).hexdigest()})
        self.send("setup.allow_token", "admin", "setPaymentTokenAllowed(address,bool)",
                  self.token, "true", events=("PaymentTokenAllowlistUpdated",))
        self.send("setup.evaluator_fee", "admin", "setEvaluatorFee(uint256)", 1000,
                  events=("EvaluatorFeeUpdated",))
        self.send("setup.platform_fee", "admin", "setPlatformFee(uint256,address)", 500,
                  self.roles["treasury"], events=("PlatformFeeUpdated",))
        self.tx("setup.mint", "admin", self.token, self.calldata("mint(address,uint256)",
                self.roles["client"], 6 * BUDGET), events=("Transfer",))
        self.tx("setup.approve", "client", self.token, self.calldata("approve(address,uint256)",
                self.core, 6 * BUDGET), events=("Approval",))
        self.initial_supply = 6 * BUDGET
        self.snapshot()

    def flow(self) -> None:
        sys.path.insert(0, str(ROOT / "src"))
        from agent_economic_trust.core import FIXTURES, OracleStatus, oracle_score

        good_fixture, good_artifact = FIXTURES["good"]
        bad_fixture, bad_artifact = FIXTURES["bad"]
        if oracle_score(good_fixture, good_artifact).status != OracleStatus.PASS:
            raise AssertionError("good independent oracle fixture changed")
        bad_oracle = oracle_score(bad_fixture, bad_artifact)
        if bad_oracle.status != OracleStatus.FAIL:
            raise AssertionError("bad independent oracle fixture changed")

        before = self.snapshot()
        job_id, _ = self.create_funded("good", good_fixture.public_task()["task_prompt"])
        self.submit("good", job_id, good_artifact.digest())
        self.send("good.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, "0x" + "01".zfill(64), "0x",
                  events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        after = self.snapshot()
        self.assert_delta(before, after, client=-BUDGET, provider=17 * UNIT,
                          evaluator=2 * UNIT, treasury=UNIT)
        if self.job(job_id)["status"] != "Completed":
            raise AssertionError("good job did not complete")
        self.send("good.replay_complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, "0x" + "01".zfill(64), "0x", status=0)
        if self.job(job_id)["status"] != "Completed" or self.snapshot() != after:
            raise AssertionError("terminal completion replay changed state or paid twice")
        self.scenarios["good_completed"] = {"job_id": job_id, "oracle_status": "PASS",
                                             "before": before, "after": after, "job": self.job(job_id)}

        before = self.snapshot()
        job_id, _ = self.create_funded("bad", bad_fixture.public_task()["task_prompt"])
        self.submit("bad", job_id, bad_artifact.digest())
        self.send("bad.complete_without_guard", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, "0x" + "02".zfill(64), "0x",
                  events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        after = self.snapshot()
        self.assert_delta(before, after, client=-BUDGET, provider=17 * UNIT,
                          evaluator=2 * UNIT, treasury=UNIT)
        if self.job(job_id)["status"] != "Completed":
            raise AssertionError("bad job was not approved by native evaluator")
        self.scenarios["bad_completed_without_app_guard"] = {
            "job_id": job_id, "oracle_status": bad_oracle.status.value,
            "oracle_reason": bad_oracle.reason_code, "artifact_digest": bad_artifact.digest(),
            "verdict_origin": "fixed scripted evaluator decision", "application_guard": "absent",
            "before": before, "after": after, "job": self.job(job_id),
        }

        before = self.snapshot()
        job_id, _ = self.create_funded("reject", "role and rejection control")
        self.submit("reject", job_id, good_artifact.digest())
        submitted = self.snapshot()
        self.send("reject.wrong_actor_complete", "outsider", "complete(uint256,bytes32,bytes)",
                  job_id, "0x" + "03".zfill(64), "0x", status=0)
        self.send("reject.wrong_actor_reject", "provider", "reject(uint256,bytes32,bytes)",
                  job_id, "0x" + "04".zfill(64), "0x", status=0)
        if self.job(job_id)["status"] != "Submitted" or self.snapshot() != submitted:
            raise AssertionError("wrong-role transaction changed job or token balances")
        self.send("reject.evaluator", "evaluator", "reject(uint256,bytes32,bytes)",
                  job_id, "0x" + "05".zfill(64), "0x", events=("JobRejected", "Refunded"))
        after = self.snapshot()
        self.assert_delta(before, after)
        if self.job(job_id)["status"] != "Rejected":
            raise AssertionError("evaluator reject did not refund")
        self.send("reject.replay_reject", "evaluator", "reject(uint256,bytes32,bytes)",
                  job_id, "0x" + "05".zfill(64), "0x", status=0)
        if self.job(job_id)["status"] != "Rejected" or self.snapshot() != after:
            raise AssertionError("terminal rejection replay changed state or refunded twice")
        self.scenarios["wrong_roles_then_reject"] = {
            "job_id": job_id, "before": before, "funded": submitted,
            "after": after, "job": self.job(job_id),
            "wrong_role_steps": ["reject.wrong_actor_complete", "reject.wrong_actor_reject"],
        }

        before = self.snapshot()
        job_id, expiry = self.create_funded("funded_expiry", "unsubmitted expiry control")
        self.next_timestamp(expiry + 1)
        self.send("funded_expiry.refund", "outsider", "claimRefund(uint256)", job_id,
                  events=("JobExpired", "Refunded"))
        after = self.snapshot()
        self.assert_delta(before, after)
        if self.job(job_id)["status"] != "Expired":
            raise AssertionError("Funded expiry failed")
        self.scenarios["funded_expiry_refund"] = {"job_id": job_id, "expiry": expiry,
                                                   "before": before, "after": after, "job": self.job(job_id)}

        before = self.snapshot()
        job_id, expiry = self.create_funded("submitted_expiry", "submitted grace control")
        self.submit("submitted_expiry", job_id, good_artifact.digest())
        funded = self.snapshot()
        self.next_timestamp(expiry + 1)
        self.send("submitted_expiry.early_refund", "outsider", "claimRefund(uint256)", job_id,
                  status=0)
        if self.job(job_id)["status"] != "Submitted" or self.snapshot() != funded:
            raise AssertionError("grace period revert changed state or balances")
        self.next_timestamp(expiry + 3601)
        self.send("submitted_expiry.refund_after_grace", "outsider", "claimRefund(uint256)", job_id,
                  events=("JobExpired", "Refunded"))
        after = self.snapshot()
        self.assert_delta(before, after)
        if self.job(job_id)["status"] != "Expired":
            raise AssertionError("Submitted expiry failed")
        self.scenarios["submitted_grace_refund"] = {"job_id": job_id, "expiry": expiry,
                                                     "before": before, "after": after, "job": self.job(job_id)}

        before = self.snapshot()
        job_id, expiry = self.create_funded("claim", "partial settlement and pending claim control")
        self.send("claim.direct_settle_5", "client", "settleClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 5 * UNIT, "0x" + good_artifact.digest(), "0x",
                  events=("Settled", "ClaimSettled", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        self.send("claim.provider_submit_8", "provider", "submitClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 8 * UNIT, "0x" + bad_artifact.digest(), "0x", events=("ClaimSubmitted",))
        self.send("claim.reject_8", "client", "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                  job_id, 8 * UNIT, "0x" + bad_artifact.digest(), "0x" + "06".zfill(64), "0x",
                  events=("ClaimRejected",))
        if int(self.pending_claim(job_id), 16) != 0:
            raise AssertionError("rejected claim remains pending")
        self.send("claim.replay_rejected_8", "provider", "submitClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 8 * UNIT, "0x" + bad_artifact.digest(), "0x", status=0)
        self.send("claim.provider_submit_10", "provider", "submitClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 10 * UNIT, "0x" + good_artifact.digest(), "0x", events=("ClaimSubmitted",))
        pending = self.pending_claim(job_id)
        if int(pending, 16) == 0:
            raise AssertionError("provider claim was not pending")
        partial = self.snapshot()
        self.send("claim.wrong_binding", "evaluator", "approveClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 10 * UNIT, "0x" + bad_artifact.digest(), "0x", status=0)
        if self.snapshot() != partial or self.pending_claim(job_id) != pending:
            raise AssertionError("wrong claim binding changed settlement")
        self.next_timestamp(expiry + 1)
        self.send("claim.pending_blocks_refund", "outsider", "claimRefund(uint256)", job_id, status=0)
        if self.snapshot() != partial or self.pending_claim(job_id) != pending:
            raise AssertionError("pending claim refund revert changed escrow")
        self.send("claim.approve_after_expiry", "evaluator", "approveClaim(uint256,uint256,bytes32,bytes)",
                  job_id, 10 * UNIT, "0x" + good_artifact.digest(), "0x",
                  events=("Settled", "ClaimApproved", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        if int(self.pending_claim(job_id), 16) != 0 or self.job(job_id)["settled_amount_minor_units"] != 10 * UNIT:
            raise AssertionError("approved claim did not settle its cumulative amount")
        after_claim = self.snapshot()
        self.send("claim.refund_remaining", "outsider", "claimRefund(uint256)", job_id,
                  events=("JobExpired", "Refunded"))
        after = self.snapshot()
        self.assert_delta(before, after, client=-10 * UNIT, provider=8_500_000,
                          evaluator=UNIT, treasury=500_000)
        if self.job(job_id)["status"] != "Expired":
            raise AssertionError("claim remainder did not expire")
        self.scenarios["partial_claim_after_expiry"] = {
            "job_id": job_id, "expiry": expiry, "pending_claim_hash": pending,
            "before": before, "after_direct_settlement": partial,
            "after_claim_approval": after_claim, "after": after, "job": self.job(job_id),
        }

        if self.balance(self.core) != 0:
            raise AssertionError("nonzero escrow after all jobs finalize")

    def execute(self) -> dict[str, Any]:
        if self.output.exists():
            raise FileExistsError(f"refusing to overwrite native receipts: {self.output}")
        self.output.mkdir(parents=True)
        for executable in (CAST, FORGE, ANVIL, SOLC):
            if not executable.is_file():
                raise FileNotFoundError(executable)
        if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN:
            raise RuntimeError("ERC-8183 upstream checkout is not at the pinned commit")
        if _command("git", "status", "--porcelain", cwd=UPSTREAM):
            raise RuntimeError("ERC-8183 upstream tracked files are modified")
        for name, expected in SUBMODULE_PINS.items():
            if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / name) != expected:
                raise RuntimeError(f"ERC-8183 submodule is not pinned: {name}")
        with (self.output / "forge-build.log").open("w", encoding="utf-8") as build_log:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                           cwd=UPSTREAM, stdout=build_log, stderr=subprocess.STDOUT, check=True)
        with (self.output / "anvil.log").open("w", encoding="utf-8") as anvil_log:
            process = subprocess.Popen([
                str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
                "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
                "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6", "--balance", "1000",
                "--mnemonic", "test test test test test test test test test test test junk", "--quiet",
            ], stdout=anvil_log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Anvil exited before its loopback RPC became ready")
                    try:
                        chain_id = _hex_int(self.rpc.call("eth_chainId"))
                        break
                    except (OSError, ConnectionError):
                        if time.monotonic() > deadline:
                            raise TimeoutError("Anvil loopback RPC did not become ready")
                        time.sleep(0.05)
                if chain_id != CHAIN_ID:
                    raise AssertionError(f"unexpected chain ID {chain_id}")
                accounts = self.rpc.call("eth_accounts")
                if len(accounts) != 6 or len({account.lower() for account in accounts}) != 6:
                    raise AssertionError("Anvil did not provide six distinct local test accounts")
                self.roles = dict(zip(("admin", "client", "provider", "evaluator", "treasury", "outsider"), accounts))
                self.deploy()
                self.flow()
                evidence = {
                    "schema_version": 1, "work_order": "W06", "gate": "G2",
                    "model_behavior_tier": "SCRIPTED", "payment_tier": "NATIVE_LOCAL_CHAIN",
                    "execution_tier": "NATIVE_LOCAL_PROTOCOL",
                    "source": {"repository": "https://github.com/erc-8183/base-contracts",
                               "commit": PIN, "submodules": SUBMODULE_PINS,
                               "license": "MIT", "foundry_version": "1.8.5",
                               "solc_version": "0.8.28+commit.7893614a"},
                    "chain": {"rpc_host": "127.0.0.1", "port": self.port,
                              "chain_id": CHAIN_ID, "hardfork": "cancun",
                              "genesis_timestamp": GENESIS_TIMESTAMP},
                    "actors": self.roles, "contracts": self.contracts,
                    "asset": {"name": "MockUSDC", "decimals": 6,
                              "supply_minor_units": self.initial_supply, "real_value": 0},
                    "transactions": self.transactions, "scenarios": self.scenarios,
                    "limitations": ["Scripted evaluator decisions; no LLM behavior measured.",
                                    "Native escrow does not validate artifact semantics without an application guard.",
                                    "Local test token and isolated chain only; no testnet or production payment."],
                }
                target = self.output / "evidence.json"
                target.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                return evidence
            except Exception as exc:
                (self.output / "failure.json").write_text(json.dumps(
                    {"error_type": type(exc).__name__, "error": str(exc),
                     "transactions": self.transactions}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory for native receipts")
    parser.add_argument("--port", type=int, default=0, help="loopback Anvil port; 0 chooses an unused port")
    args = parser.parse_args()
    port = args.port or _free_port()
    evidence = NativeRun(args.output, port).execute()
    print(json.dumps({"evidence": str(args.output / "evidence.json"),
                      "native_transactions": len(evidence["transactions"]),
                      "scenarios": list(evidence["scenarios"]),
                      "receipt_statuses": {str(status): sum(tx["status"] == status for tx in evidence["transactions"])
                                           for status in (0, 1)}}, sort_keys=True))


if __name__ == "__main__":
    main()
