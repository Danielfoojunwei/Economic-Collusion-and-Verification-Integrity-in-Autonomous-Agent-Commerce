"""AP2-authorized application purchase on a disposable local ERC20 chain.

The official AP2 SDK verifies the signed delegation in a separate pinned venv.
This controller, not AP2, executes the valueless MockUSDC transfer. It never
uses an external PSP, public chain, or model-held signer.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from scripts import run_erc8183_local as native


AP2_SOURCE = Path("/workspace/upstreams/ap2-w15")
AP2_PYTHON = AP2_SOURCE / ".venv/bin/python"
AP2_PIN = "b4587ac1d055888a73b4b21750973cffba961793"
ERC8183_PIN = native.PIN
MERCHANT_ID = "demo-merchant-1"
AP2_AMOUNT_CENTS = 2_500
LOCAL_ERC20_AMOUNT_MINOR = 25_000_000  # 2,500 cents in six-decimal local units

if not native.ANVIL.is_file():
    workspace = Path("/workspace")
    if (workspace / ".tools/foundry/v1.8.5/anvil").is_file():
        native.ANVIL = workspace / ".tools/foundry/v1.8.5/anvil"
        native.FORGE = workspace / ".tools/foundry/v1.8.5/forge"
        native.CAST = workspace / ".tools/foundry/v1.8.5/cast"
        native.SOLC = workspace / ".tools/solc/v0.8.28/solc"
        native.UPSTREAM = workspace / "upstreams/erc8183"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _clean_pin(path: Path, expected: str) -> None:
    if (native._command("git", "rev-parse", "HEAD", cwd=path) != expected
            or native._command("git", "status", "--porcelain", cwd=path)):
        raise ValueError("pinned upstream source is absent or dirty")


def validate_ap2_authorization(path: Path, *, obligation_id: str,
                               artifact_digest: str, issuer_public_sha256: str) -> dict:
    """Verify signed scope through official AP2 and exact caller obligations."""
    _clean_pin(AP2_SOURCE, AP2_PIN)
    if not AP2_PYTHON.is_file():
        raise FileNotFoundError(AP2_PYTHON)
    record = json.loads(path.read_text(encoding="utf-8"))
    expected_intent = {
        "sku": "independent-invoice-audit/v1",
        "invoice_obligation_id": obligation_id,
        "invoice_artifact_digest": artifact_digest,
        "payee_id": MERCHANT_ID,
        "amount_minor": AP2_AMOUNT_CENTS,
        "currency": "USD", "instrument_id": "demo-instrument-1",
        "purpose": "purchase independent audit service only",
        "invoice_quality_authority": "NONE",
    }
    if (record.get("schema") != "ap2-live-audit-authorization-v1"
            or record.get("payment_execution") != "NONE"
            or record.get("upstream_commit") != AP2_PIN
            or record.get("purchase_intent") != expected_intent
            or record.get("cross_obligation_id") == obligation_id
            or record.get("proposed_payment", {}).get("amount_minor") != AP2_AMOUNT_CENTS
            or record.get("proposed_payment", {}).get("payee_id") != MERCHANT_ID
            or record.get("proposed_payment", {}).get("currency") != "USD"
            or record.get("proposed_payment", {}).get("instrument_id") != "demo-instrument-1"
            or sha256(canonical(record.get("trusted_issuer_public_jwk"))).hexdigest()
            != issuer_public_sha256
            or record.get("trusted_issuer_public_sha256") != issuer_public_sha256):
        raise ValueError("AP2 issuer, amount, payee, obligation or artifact scope differs")
    root = Path(__file__).resolve().parents[2]
    environment = {"PYTHONPATH": str(root), "PYTHON_DOTENV_DISABLED": "1"}
    # Do not pass unrelated environment secrets to the AP2 subprocess.
    subprocess.run([str(AP2_PYTHON), "-m", "scripts.ap2_live_authorization",
                    "verify-live", str(path)], cwd=root, env=environment,
                   capture_output=True, text=True, check=True, timeout=45)
    if (record.get("issue_time_verification", {}).get("status") != "PASS"
            or record.get("issue_time_verification", {}).get("cross_obligation_rejected") is not True):
        raise ValueError("AP2 signed scope or cross-obligation negative was not verified")
    return record


class NativeAuditPurchase:
    """One-use buyer→audit-merchant application transfer on its own local chain."""

    def __init__(self, output_dir: Path, authorization_path: Path, *,
                 obligation_id: str, artifact_digest: str,
                 issuer_public_sha256: str, port: int = 0):
        self.output_dir = Path(output_dir)
        self.authorization_path = Path(authorization_path)
        self.obligation_id = obligation_id
        self.artifact_digest = artifact_digest
        self.issuer_public_sha256 = issuer_public_sha256
        self.port = port or native._free_port()
        self.helper = native.NativeRun(self.output_dir, self.port)
        self.process: subprocess.Popen[str] | None = None
        self.anvil_log: Any = None
        self.purchase: dict | None = None

    def __enter__(self) -> "NativeAuditPurchase":
        if self.output_dir.exists():
            raise FileExistsError(self.output_dir)
        validate_ap2_authorization(
            self.authorization_path, obligation_id=self.obligation_id,
            artifact_digest=self.artifact_digest,
            issuer_public_sha256=self.issuer_public_sha256)
        _clean_pin(native.UPSTREAM, ERC8183_PIN)
        self.output_dir.mkdir(parents=True, mode=0o700)
        with (self.output_dir / "forge-build.log").open("w", encoding="utf-8") as handle:
            subprocess.run([str(native.FORGE), "build", "--offline", "--use",
                            str(native.SOLC), "--threads", "4"], cwd=native.UPSTREAM,
                           stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=120)
        self.anvil_log = (self.output_dir / "anvil.log").open("w", encoding="utf-8")
        seed = int.from_bytes(sha256(("ap2-audit-purchase:" + self.obligation_id).encode()).digest()[:8], "big")
        self.process = subprocess.Popen([
            str(native.ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(native.CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(native.GENESIS_TIMESTAMP), "--accounts", "8",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
        ], stdout=self.anvil_log, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError("local purchase chain exited before readiness")
                try:
                    if int(self.helper.rpc.call("eth_chainId"), 16) == native.CHAIN_ID:
                        break
                    raise RuntimeError("local purchase chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local purchase chain was not ready")
                    time.sleep(0.05)
            accounts = self.helper.rpc.call("eth_accounts")
            self.helper.roles = dict(zip((
                "admin", "client", "provider", "evaluator", "treasury", "outsider",
            ), accounts[:6], strict=True))
            self.helper.deploy()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def buy(self) -> dict:
        if self.purchase is not None or self.process is None or self.process.poll() is not None:
            raise ValueError("audit-service purchase already used or unavailable")
        authorization = validate_ap2_authorization(
            self.authorization_path, obligation_id=self.obligation_id,
            artifact_digest=self.artifact_digest,
            issuer_public_sha256=self.issuer_public_sha256)
        before = self.helper.snapshot()
        receipt = self.helper.tx(
            "ap2_application.audit_service_purchase", "client", self.helper.token,
            self.helper.calldata("transfer(address,uint256)",
                                 self.helper.roles["evaluator"], LOCAL_ERC20_AMOUNT_MINOR),
            events=("Transfer",),
        )
        after = self.helper.snapshot()
        self.helper.assert_delta(before, after, client=-LOCAL_ERC20_AMOUNT_MINOR,
                                 evaluator=LOCAL_ERC20_AMOUNT_MINOR)
        self.purchase = {
            "schema": "ap2-application-erc20-audit-purchase-v1",
            "payment_execution": "APPLICATION_LOCAL_ERC20; AP2 SDK PAYMENT_NONE",
            "execution_tier": "NATIVE_LOCAL_PROTOCOL",
            "service_id": "independent-invoice-audit/v1",
            "obligation_id": self.obligation_id,
            "artifact_digest": self.artifact_digest,
            "ap2_authorization_sha256": file_sha(self.authorization_path),
            "ap2_authorization_reference": authorization["authorization_reference"],
            "trusted_issuer_public_sha256": self.issuer_public_sha256,
            "ap2_amount_cents": AP2_AMOUNT_CENTS,
            "local_amount_minor": LOCAL_ERC20_AMOUNT_MINOR,
            "merchant_mapping": {MERCHANT_ID: "evaluator"},
            "merchant_role": "evaluator", "payer_role": "client",
            "erc8183_source_commit": ERC8183_PIN,
            "mock_usdc_artifact_sha256": file_sha(
                native.UPSTREAM / "out/MockUSDC.sol/MockUSDC.json"),
            "chain_id": native.CHAIN_ID,
            "roles": self.helper.roles,
            "token_address": self.helper.token,
            "contracts": self.helper.contracts,
            "before": before, "after": after,
            "transaction_hash": receipt["transactionHash"],
            "raw_receipt": receipt,
            "raw_transaction": self.helper.rpc.call("eth_getTransactionByHash", [receipt["transactionHash"]]),
            "transactions": [
                {**item, "raw_transaction": self.helper.rpc.call(
                    "eth_getTransactionByHash", [item["transaction_hash"]])}
                for item in self.helper.transactions
            ],
        }
        return {"status": "AUDIT_SERVICE_PAID", "transaction_hash": receipt["transactionHash"],
                "amount_minor": LOCAL_ERC20_AMOUNT_MINOR,
                "obligation_id": self.obligation_id,
                "payment_execution": "APPLICATION_LOCAL_ERC20",
                "proves_invoice_quality": False}

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if self.purchase is not None:
                rendered = canonical(self.purchase)
                (self.output_dir / "native-audit-purchase.json").write_bytes(rendered + b"\n")
                (self.output_dir / "native-audit-purchase.sha256").write_text(
                    sha256(rendered).hexdigest() + "  native-audit-purchase.json\n")
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.anvil_log is not None:
                self.anvil_log.close()
        return False
