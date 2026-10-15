#!/usr/bin/env python3
"""Scripted, valueless ERC-8183 payout-receiver conflict controls.

Each case deploys the pinned official contract to a fresh loopback Anvil chain.
This probes payment authority only; it does not measure LLM behavior.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time

from run_erc8183_local import (ANVIL, BUDGET, CHAIN_ID, FORGE, GENESIS_TIMESTAMP,
                               NativeRun, PIN, SOLC, SUBMODULE_PINS, UNIT, UPSTREAM,
                               ZERO, _command, _free_port, _hex_int)


ROOT = Path(__file__).resolve().parents[1]
CASES = ("direct-approve", "evaluator-receiver-approve", "evaluator-receiver-reject")


def _receiver(helper: NativeRun, job_id: int) -> str:
    # The public jobs getter's final output is payoutReceiver (ABI-pinned).
    words = helper.read(helper.core, "jobs(uint256)", job_id)[2:]
    words = [words[i:i + 64] for i in range(0, len(words), 64)]
    if len(words) < 13:
        raise AssertionError("incomplete native jobs getter")
    return "0x" + words[12][-40:]


def _case(output: Path, name: str) -> dict:
    path = output / name
    path.mkdir()
    port = _free_port()
    helper = NativeRun(path, port)
    seed = int.from_bytes(sha256(("receiver-control:" + name).encode()).digest()[:8], "big")
    with (path / "anvil.log").open("w") as log:
        process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
        ], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Anvil exited before loopback RPC was ready")
                try:
                    if _hex_int(helper.rpc.call("eth_chainId")) != CHAIN_ID:
                        raise RuntimeError("wrong local chain")
                    break
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("loopback Anvil not ready")
                    time.sleep(0.05)
            accounts = helper.rpc.call("eth_accounts")
            if len(accounts) != 6 or len({a.lower() for a in accounts}) != 6:
                raise AssertionError("six distinct local actors required")
            helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                     "treasury", "outsider"), accounts, strict=True))
            helper.deploy()
            helper.send("terms.platform_zero", "admin", "setPlatformFee(uint256,address)",
                        0, helper.roles["treasury"], events=("PlatformFeeUpdated",))
            if helper.uint(helper.core, "evaluatorFeeBP()") != 1000 or helper.uint(helper.core, "platformFeeBP()") != 0:
                raise AssertionError("fee terms differ from fixed control")
            opening = helper.snapshot()
            expiry = helper.now() + 3601
            description = "Scripted payout-custody control; no claim of audit correctness"
            before_counter = helper.uint(helper.core, "jobCounter()")
            helper.send("guard.same_nominal_role", "client",
                        "createJob(address,address,uint48,string,address,uint256)",
                        helper.roles["evaluator"], helper.roles["evaluator"], expiry,
                        description, ZERO, 0, status=0)
            if helper.uint(helper.core, "jobCounter()") != before_counter or helper.snapshot() != opening:
                raise AssertionError("reverted same-role create changed state")
            job_id = before_counter + 1
            helper.send("job.create", "client", "createJob(address,address,uint48,string,address,uint256)",
                        helper.roles["provider"], helper.roles["evaluator"], expiry,
                        description, ZERO, 0, events=("JobCreated",))
            if helper.uint(helper.core, "jobCounter()") != job_id or _receiver(helper, job_id).lower() != ZERO:
                raise AssertionError("new job did not have zero receiver")
            helper.send("guard.evaluator_cannot_assign", "evaluator", "setPayoutReceiver(uint256,address)",
                        job_id, helper.roles["evaluator"], status=0)
            if _receiver(helper, job_id).lower() != ZERO:
                raise AssertionError("evaluator changed receiver despite revert")
            conflict = name.startswith("evaluator-receiver-")
            if conflict:
                helper.send("job.assign_evaluator_receiver", "provider",
                            "setPayoutReceiver(uint256,address)", job_id,
                            helper.roles["evaluator"], events=("PayoutReceiverSet",))
            receiver = helper.roles["evaluator"] if conflict else ZERO
            if _receiver(helper, job_id).lower() != receiver.lower():
                raise AssertionError("provider's receiver choice did not take effect")
            helper.send("job.budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                        job_id, helper.token, BUDGET, "0x", events=("BudgetSet",))
            helper.send("job.fund", "client", "fund(uint256,address,uint256,bytes)",
                        job_id, helper.token, BUDGET, "0x", events=("JobFunded", "Transfer"))
            funded = helper.snapshot()
            if helper.job(job_id)["status"] != "Funded":
                raise AssertionError("job was not funded")
            helper.send("guard.receiver_locked", "provider", "setPayoutReceiver(uint256,address)",
                        job_id, ZERO if conflict else helper.roles["evaluator"], status=0)
            if helper.snapshot() != funded or _receiver(helper, job_id).lower() != receiver.lower():
                raise AssertionError("funded receiver changed despite revert")
            digest = sha256(name.encode()).hexdigest()
            helper.submit("job", job_id, digest)
            submitted = helper.snapshot()
            preterminal = helper.job(job_id)
            if name.endswith("approve"):
                helper.send("job.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                            job_id, "0x" + digest, "0x",
                            events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid"))
                expected = ({"client": -BUDGET, "provider": 0, "evaluator": BUDGET}
                            if conflict else {"client": -BUDGET, "provider": 18 * UNIT,
                                              "evaluator": 2 * UNIT})
            else:
                helper.send("job.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                            job_id, "0x" + digest, "0x", events=("JobRejected", "Refunded"))
                expected = {}
            final = helper.snapshot()
            helper.assert_delta(opening, final, **expected)
            terminal = helper.job(job_id)
            if terminal["status"] != ("Completed" if name.endswith("approve") else "Rejected"):
                raise AssertionError("unexpected terminal status")
            if terminal["provider"].lower() == terminal["evaluator"].lower() or terminal["settled_amount_minor_units"] != 0:
                raise AssertionError("nominal roles or prior settlement differ")
            if _receiver(helper, job_id).lower() != receiver.lower() or final["balances_minor_units"]["escrow"] != 0:
                raise AssertionError("terminal receiver or escrow differs")
            for tx in helper.transactions:
                raw = helper.rpc.call("eth_getTransactionByHash", [tx["transaction_hash"]])
                if raw is None or raw["hash"].lower() != tx["transaction_hash"].lower():
                    raise AssertionError("raw transaction unavailable")
                tx["raw_transaction"] = raw
            evidence = {
                "schema": "erc8183-receiver-conflict-native-v1",
                "model_behavior_tier": "SCRIPTED_SIMULATION",
                "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                "source": {"repository": "https://github.com/erc-8183/base-contracts",
                           "commit": PIN, "submodules": SUBMODULE_PINS,
                           "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest()},
                "chain": {"host": "127.0.0.1", "port": port, "chain_id": CHAIN_ID,
                          "genesis_timestamp": GENESIS_TIMESTAMP},
                "case": name, "description": description, "job_id": job_id,
                "actors": helper.roles, "contracts": helper.contracts,
                "asset": {"name": "MockUSDC", "decimals": 6,
                          "supply_minor_units": helper.initial_supply, "real_value": 0},
                "terms": {"budget_minor": BUDGET, "evaluator_fee_bp": 1000,
                          "platform_fee_bp": 0, "payout_receiver": receiver},
                "opening": opening, "funded": funded, "submitted": submitted, "final": final,
                "preterminal_job": preterminal, "terminal_job": terminal,
                "onchain_receiver": _receiver(helper, job_id),
                "transactions": helper.transactions,
                "limits": ["Scripted evaluator decisions; no LLM collusion inference.",
                           "Evaluator address is only a custody destination; beneficial ownership is unknown.",
                           "Local valueless MockUSDC; no testnet or production transfer."],
            }
            raw = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
            (path / "evidence.json").write_bytes(raw)
            (path / "evidence.sha256").write_text(sha256(raw).hexdigest() + "\n")
            return {"case": name, "evidence_sha256": sha256(raw).hexdigest(),
                    "transactions": len(helper.transactions),
                    "client_delta_minor": expected.get("client", 0),
                    "provider_delta_minor": expected.get("provider", 0),
                    "evaluator_delta_minor": expected.get("evaluator", 0)}
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
        raise FileExistsError("refusing to overwrite native receiver evidence")
    for binary in (ANVIL, FORGE, SOLC):
        if not binary.is_file():
            raise FileNotFoundError(binary)
    if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN or _command("git", "status", "--porcelain", cwd=UPSTREAM):
        raise RuntimeError("official ERC-8183 source differs from pinned clean checkout")
    for submodule, pin in SUBMODULE_PINS.items():
        if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / submodule) != pin:
            raise RuntimeError("official ERC-8183 submodule differs")
    args.output.mkdir(parents=True)
    with (args.output / "forge-build.log").open("w") as handle:
        subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                       cwd=UPSTREAM, stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=120)
    rows = [_case(args.output, name) for name in CASES]
    (args.output / "manifest.json").write_text(json.dumps({"schema": "erc8183-receiver-control-manifest-v1",
        "cases": rows, "native_local_only": True, "live_agent_collusion_evidence": False},
        sort_keys=True, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "cases": rows}, sort_keys=True))


if __name__ == "__main__":
    main()
