"""Read-only saved native receipt check for an AP2-authorized local purchase.

This verifies internal saved RPC consistency and pinned contract source. Saved
localhost RPC responses alone do not attest a past public chain.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from .ap2_live_purchase import validate_ap2_authorization
from scripts import run_erc8183_local as native


AP2_CENTS = 2_500
LOCAL_UNITS = 25_000_000
INITIAL_CLIENT_UNITS = 120_000_000
MERCHANT = "demo-merchant-1"
SOURCE_PIN = "142e669c1fd318486a4628395b629f033654dd06"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def number(value: Any) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        return int(value, 16 if value.startswith("0x") else 10)
    raise ValueError("invalid native numeric value")


def address(value: Any) -> str:
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is not None,
            "invalid native address")
    return value.lower()


def verify_native_audit_purchase(directory: Path, authorization_path: Path, *,
                                 expected_obligation_id: str,
                                 expected_artifact_digest: str,
                                 expected_issuer_public_sha256: str) -> dict:
    directory = Path(directory)
    evidence_path = directory / "native-audit-purchase.json"
    raw = evidence_path.read_bytes().rstrip(b"\n")
    checksum = (directory / "native-audit-purchase.sha256").read_text().strip()
    require(checksum == f"{sha256(raw).hexdigest()}  native-audit-purchase.json",
            "native audit purchase file checksum differs")
    e = json.loads(raw)
    require(e.get("schema") == "ap2-application-erc20-audit-purchase-v1",
            "audit purchase schema differs")
    require(e.get("payment_execution") == "APPLICATION_LOCAL_ERC20; AP2 SDK PAYMENT_NONE",
            "AP2/native execution tier differs")
    require(e.get("service_id") == "independent-invoice-audit/v1"
            and e.get("obligation_id") == expected_obligation_id
            and e.get("artifact_digest") == expected_artifact_digest,
            "audit purchase obligation binding differs")
    require(e.get("ap2_amount_cents") == AP2_CENTS
            and e.get("local_amount_minor") == LOCAL_UNITS
            and e.get("merchant_mapping") == {MERCHANT: "evaluator"}
            and e.get("merchant_role") == "evaluator"
            and e.get("payer_role") == "client", "purchase amount or payee mapping differs")
    require(e.get("ap2_authorization_sha256") == sha256(authorization_path.read_bytes()).hexdigest()
            and e.get("trusted_issuer_public_sha256") == expected_issuer_public_sha256,
            "AP2 signed authorization archive differs")
    ap2 = validate_ap2_authorization(
        authorization_path, obligation_id=expected_obligation_id,
        artifact_digest=expected_artifact_digest,
        issuer_public_sha256=expected_issuer_public_sha256)
    require(e.get("ap2_authorization_reference") == ap2["authorization_reference"],
            "AP2 authorization reference differs")
    source = Path("/workspace/upstreams/erc8183")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, check=True,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=source, check=True,
                           capture_output=True, text=True).stdout.strip()
    require(head == SOURCE_PIN and not dirty and e.get("erc8183_source_commit") == SOURCE_PIN,
            "official MockUSDC source pin differs")
    token_artifact = source / "out/MockUSDC.sol/MockUSDC.json"
    require(e.get("mock_usdc_artifact_sha256") == sha256(token_artifact.read_bytes()).hexdigest()
            and e.get("contracts", {}).get("MockUSDC", {}).get("artifact_sha256")
            == sha256(token_artifact.read_bytes()).hexdigest(), "MockUSDC build artifact differs")
    roles = {key: address(value) for key, value in e["roles"].items()}
    require(len(set(roles.values())) == len(roles), "native role addresses overlap")
    token = address(e["token_address"])
    require(address(e["contracts"]["MockUSDC"]["address"]) == token,
            "token address differs from saved deployment")
    require(e.get("chain_id") == 31337, "local chain ID differs")
    transactions = e["transactions"]
    require(len(transactions) == 9 and len({x["transaction_hash"] for x in transactions}) == 9,
            "native setup and purchase transaction count differs")
    steps = [x["step"] for x in transactions]
    require(steps == ["deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
                      "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
                      "setup.mint", "setup.approve", "ap2_application.audit_service_purchase"],
            "native transaction sequence differs")
    for tx in transactions:
        receipt, raw_tx = tx["raw_receipt"], tx["raw_transaction"]
        require(number(receipt["status"]) == 1 and number(tx["status"]) == 1
                and receipt["transactionHash"].lower() == tx["transaction_hash"].lower()
                and raw_tx["hash"].lower() == tx["transaction_hash"].lower()
                and address(raw_tx["from"]) == roles[tx["actor_role"]]
                and address(receipt["from"]) == roles[tx["actor_role"]]
                and number(raw_tx["chainId"]) == 31337,
                "saved native transaction or receipt identity differs")
    purchase = transactions[-1]
    receipt, raw_tx = purchase["raw_receipt"], purchase["raw_transaction"]
    require(e["transaction_hash"].lower() == purchase["transaction_hash"].lower()
            and e["raw_receipt"] == receipt and e["raw_transaction"] == raw_tx,
            "purchase summary differs from transaction list")
    cast = Path("/workspace/.tools/foundry/v1.8.5/cast")
    calldata = subprocess.run([str(cast), "calldata", "transfer(address,uint256)",
                               roles["evaluator"], str(LOCAL_UNITS)], check=True,
                              capture_output=True, text=True).stdout.strip().lower()
    topic = subprocess.run([str(cast), "keccak", "Transfer(address,address,uint256)"],
                           check=True, capture_output=True, text=True).stdout.strip().lower()
    require(address(raw_tx["to"]) == token and address(receipt["to"]) == token
            and raw_tx["input"].lower() == calldata and number(raw_tx["value"]) == 0,
            "purchase native payee or calldata differs")
    require(len(receipt["logs"]) == 1, "purchase requires one raw Transfer log")
    log = receipt["logs"][0]
    require(address(log["address"]) == token and len(log["topics"]) == 3
            and log["topics"][0].lower() == topic
            and address("0x" + log["topics"][1][-40:]) == roles["client"]
            and address("0x" + log["topics"][2][-40:]) == roles["evaluator"]
            and number(log["data"]) == LOCAL_UNITS,
            "purchase raw ERC20 Transfer event differs")
    before, after = e["before"], e["after"]
    b, a = before["balances_minor_units"], after["balances_minor_units"]
    require(before["total_supply_minor_units"] == INITIAL_CLIENT_UNITS
            and after["total_supply_minor_units"] == INITIAL_CLIENT_UNITS
            and b["client"] == INITIAL_CLIENT_UNITS and b["evaluator"] == 0
            and a["client"] == INITIAL_CLIENT_UNITS - LOCAL_UNITS
            and a["evaluator"] == LOCAL_UNITS
            and all(a[key] == b[key] for key in b if key not in {"client", "evaluator"}),
            "purchase saved balances differ from raw transfer")
    mint = transactions[-3]["raw_receipt"]
    require(len(mint["logs"]) == 1 and address(mint["logs"][0]["address"]) == token
            and mint["logs"][0]["topics"][0].lower() == topic
            and address("0x" + mint["logs"][0]["topics"][2][-40:]) == roles["client"]
            and number(mint["logs"][0]["data"]) == INITIAL_CLIENT_UNITS,
            "local client endowment mint differs")
    return {"status": "PASS", "native_purchase_verified": True,
            "ap2_signed_scope_verified": True, "ap2_cross_obligation_rejected": True,
            "payment_execution": "APPLICATION_LOCAL_ERC20",
            "local_amount_minor": LOCAL_UNITS, "transaction_hash": e["transaction_hash"],
            "obligation_id": expected_obligation_id,
            "invoice_quality_verified_by_purchase": False}
