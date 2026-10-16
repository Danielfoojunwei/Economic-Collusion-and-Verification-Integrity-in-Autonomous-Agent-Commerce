"""Public pre-view funding replay and negative tests; no RPC/network/native calls."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from agent_economic_trust.bilateral030_funding_verifier import (
    _artifacts, _calldata, verify_funding_file, verify_funding_record,
)

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "artifacts/prospective/ERC8183_BILATERAL030_PREVIEW_FUNDING_V2_001"
PINNED = ROOT / "tests/fixtures/bilateral030_native/v2_public_assignments.json"
NAMES = ("funded", "unfunded")
ARCHIVE_SHA256 = {
    "funded": "232bf3127a8ad1d94dd9b39a4e10733994dd1aa6f98aa72a6fc8b98212b6bb33",
    "unfunded": "7ceffdc7c82c4367ac6db67182c44be348c64f4f25f2622ba719dbcce9aa6a6a",
}


class SavedChainRPC:
    """Deterministic fake of read-only responses for the two stopped fixtures."""

    def __init__(self, saved: dict, artifacts: dict) -> None:
        self.saved = saved
        self.by_hash = {tx["transaction_hash"]: tx for tx in saved["transactions"]}
        self.codes = {}
        for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
            artifact = artifacts[name]
            code = bytearray.fromhex(artifact["deployedBytecode"]["object"][2:])
            for group in (artifact["deployedBytecode"].get("immutableReferences") or {}).values():
                for ref in group:
                    address_word = saved["contracts"][name]["address"][2:].rjust(64, "0")
                    code[ref["start"]:ref["start"] + ref["length"]] = bytes.fromhex(address_word)
            self.codes[saved["contracts"][name]["address"].lower()] = "0x" + code.hex()
        self.codes[saved["hook"].lower()] = saved["hook_runtime_code"]
        job = saved["funded_job"]
        self.job_words = [job["client"], job["status_code"], job["provider"],
                          job["expired_at"], job["evaluator"], job["submitted_at"],
                          job["budget_minor_units"], saved["hook"], job["payment_token"],
                          0, 0, job["settled_amount_minor_units"], 0]

    @staticmethod
    def word(value: int | str) -> str:
        return f"{int(value, 16) if isinstance(value, str) else value:064x}"

    def __call__(self, method: str, params: list):
        saved = self.saved
        if method == "eth_chainId":
            return hex(saved["chain"]["chain_id"])
        if method == "eth_getBlockByNumber":
            last = saved["transactions"][-1]
            return {"number": hex(last["block_number"]),
                    "timestamp": hex(last["block_timestamp"]),
                    "hash": last["raw_receipt"]["blockHash"]}
        if method == "eth_getTransactionByHash":
            return deepcopy(self.by_hash[params[0]]["raw_transaction"])
        if method == "eth_getTransactionReceipt":
            return deepcopy(self.by_hash[params[0]]["raw_receipt"])
        if method == "eth_getCode":
            return self.codes[params[0].lower()]
        if method == "eth_call":
            target, data = params[0]["to"].lower(), params[0]["data"].lower()
            core = saved["contracts"]["ERC1967Proxy"]["address"].lower()
            token = saved["contracts"]["MockUSDC"]["address"].lower()
            hook = saved["hook"].lower()
            if target == core:
                if data == _calldata("jobs(uint256)", 1):
                    return "0x" + "".join(self.word(value) for value in self.job_words)
                if data == _calldata("evaluatorFeeBP()"):
                    return hex(1000)
                if data == _calldata("platformFeeBP()"):
                    return "0x0"
            if target == hook:
                if data == _calldata("state()"):
                    return hex(saved["hook_state"])
                if data == _calldata("jobId()"):
                    return hex(saved["hook_job_id"])
                if data == _calldata("reportDigest()"):
                    return saved["report_digest"]
            if target == token:
                if data == _calldata("totalSupply()"):
                    return hex(saved["funded"]["total_supply_minor_units"])
                if data.startswith(_calldata("balanceOf(address)", "0x" + "0" * 40)[:10]):
                    address = "0x" + data[-40:]
                    roles = {**{key: value.lower() for key, value in saved["actors"].items()},
                             "erc8183_escrow": core, "bonus_escrow": hook}
                    role = next(key for key, value in roles.items() if value == address)
                    return hex(saved["funded"]["balances_minor_units"][role])
        raise AssertionError(f"unexpected read-only RPC {method}: {params}")


class Bilateral030FundingVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = _artifacts()
        cls.saved = {name: json.loads((PREVIEW / f"{name}.json").read_text())
                     for name in NAMES}
        pinned = json.loads(PINNED.read_text())
        assert pinned["schema"] == "bilateral030-v2-public-assignments-v1"
        assert pinned["plan_source_commit"] == "725e70e"
        assert pinned["plan_source_sha256"] == (
            "fa804cbbd2a8d1d746693384def5b3dfbfe24b5c48c1a7c67e57a560117bf823")
        cls.assignments = pinned["assignments"]
        for name in NAMES:
            assert cls.assignments[name] == cls.saved[name]["public_assignment"]

    def _reject(self, changed: dict, pattern: str, *, name: str = "funded") -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            verify_funding_record(changed, self.assignments[name], bundle=self.bundle)

    @staticmethod
    def _tx(record: dict, step: str) -> dict:
        return next(tx for tx in record["transactions"] if tx["step"] == step)

    def test_funded_and_no_bonus_saved_public_archives(self) -> None:
        expected = {"funded": (5_000_000, 19), "unfunded": (0, 17)}
        for name in NAMES:
            with self.subTest(name=name):
                path = PREVIEW / f"{name}.json"
                result = verify_funding_file(path, self.assignments[name])
                self.assertEqual(result["status"], "FUNDING_ARCHIVE_REPLAYED")
                self.assertFalse(result["live_chain_checked"])
                self.assertFalse(result["model_view_independently_verified"])
                self.assertEqual((result["bonus_minor"], result["archive_transactions_replayed"]),
                                 expected[name])
                self.assertEqual(result["archive_sha256"], sha256(path.read_bytes()).hexdigest())
                self.assertEqual(result["archive_sha256"], ARCHIVE_SHA256[name])
                self.assertEqual(result["public_prefix_sha256"],
                                 self.saved[name]["public_prefix_sha256"])

    def test_trusted_assignment_source_pin_and_privacy_tampering_rejected(self) -> None:
        wrong = deepcopy(self.assignments["funded"])
        wrong["assigned_bonus_minor"] = 0
        with self.assertRaisesRegex(ValueError, "public assignment"):
            verify_funding_record(self.saved["funded"], wrong, bundle=self.bundle)
        record = deepcopy(self.saved["funded"])
        record["source"]["archive_exporter_sha256"] = "0" * 64
        self._reject(record, "source or archive provenance")
        record = deepcopy(self.saved["funded"])
        record["protected_oracle"] = {"buyer_records": {}}
        self._reject(record, "private buyer data")
        record = deepcopy(self.saved["funded"])
        record["public_description"] += " hidden_PO=400"
        self._reject(record, "public report, description")

    def test_create_fund_bind_and_bonus_calldata_tampering_rejected(self) -> None:
        for step in ("job.create", "job.set_budget", "job.fund",
                     "hook.bind", "bonus.approve", "bonus.fund"):
            with self.subTest(step=step):
                record = deepcopy(self.saved["funded"])
                self._tx(record, step)["raw_transaction"]["input"] = "0xdeadbeef"
                self._reject(record, "calldata")

    def test_provider_bonus_source_beneficiary_and_no_bonus_forgery_rejected(self) -> None:
        record = deepcopy(self.saved["funded"])
        token = record["contracts"]["MockUSDC"]["address"].lower()
        tx = self._tx(record, "bonus.fund")
        index = next(i for i, log in enumerate(tx["raw_receipt"]["logs"])
                     if log["address"].lower() == token)
        topics = tx["raw_receipt"]["logs"][index]["topics"][:]
        topics[1] = "0x" + record["actors"]["client"][2:].lower().rjust(64, "0")
        tx["raw_receipt"]["logs"][index]["topics"] = topics
        tx["logs"][index]["topics"] = topics[:]
        self._reject(record, "ERC20 transfer source")
        record = deepcopy(self.saved["funded"])
        hook = record["hook"].lower()
        tx = self._tx(record, "bonus.fund")
        index = next(i for i, log in enumerate(tx["raw_receipt"]["logs"])
                     if log["address"].lower() == hook)
        topics = tx["raw_receipt"]["logs"][index]["topics"][:]
        topics[2] = "0x" + record["actors"]["client"][2:].lower().rjust(64, "0")
        tx["raw_receipt"]["logs"][index]["topics"] = topics
        tx["logs"][index]["topics"] = topics[:]
        self._reject(record, "provider-funded bonus event")
        record = deepcopy(self.saved["funded"])
        tx = self._tx(record, "bonus.fund")
        index = next(i for i, log in enumerate(tx["raw_receipt"]["logs"])
                     if log["address"].lower() == hook)
        tx["raw_receipt"]["logs"][index]["data"] = "0x" + f"{4_000_000:064x}"
        tx["logs"][index]["data"] = tx["raw_receipt"]["logs"][index]["data"]
        self._reject(record, "provider-funded bonus event")
        record = deepcopy(self.saved["funded"])
        record["public_prefix"]["hook_address"] = record["actors"]["evaluator"]
        self._reject(record, "public model-facing funding prefix")
        record = deepcopy(self.saved["unfunded"])
        record["transactions"].append(deepcopy(self._tx(self.saved["funded"], "bonus.fund")))
        self._reject(record, "transaction step order", name="unfunded")
        record = deepcopy(self.saved["unfunded"])
        record["public_prefix"]["bonus_funded"] = True
        self._reject(record, "public model-facing funding prefix", name="unfunded")

    def test_receipt_balance_hook_and_prefix_hash_tampering_rejected(self) -> None:
        record = deepcopy(self.saved["funded"])
        self._tx(record, "job.fund")["raw_receipt"]["transactionHash"] = "0x" + "0" * 64
        self._reject(record, "raw transaction, receipt")
        record = deepcopy(self.saved["funded"])
        record["funded"]["balances_minor_units"]["bonus_escrow"] += 1
        self._reject(record, "token balances")
        record = deepcopy(self.saved["funded"])
        record["hook_state"] = 1
        self._reject(record, "funded official job or hook state")
        record = deepcopy(self.saved["funded"])
        record["public_prefix_sha256"] = "0" * 64
        self._reject(record, "public model-facing funding prefix")
        record = deepcopy(self.saved["funded"])
        record["bonus_funding_receipt_sha256"] = "0" * 64
        self._reject(record, "funding receipt hashes")

    def test_read_only_live_rpc_replay_and_gate_separation(self) -> None:
        for name in NAMES:
            with self.subTest(name=name):
                rpc = SavedChainRPC(self.saved[name], self.bundle[0])
                result = verify_funding_record(self.saved[name], self.assignments[name],
                                               bundle=self.bundle, live_rpc=rpc)
                self.assertEqual(result["status"], "FUNDING_LIVE_TEST_REPLAY")
                self.assertEqual(result["read_only_rpc_source"], "injected_test")
                with patch("agent_economic_trust.bilateral030_funding_verifier._loopback_rpc",
                           return_value=rpc):
                    confirmed = verify_funding_file(PREVIEW / f"{name}.json",
                                                    self.assignments[name], confirm_live=True)
                self.assertEqual(confirmed["status"], "FUNDING_LIVE_CONFIRMED")
                self.assertEqual(confirmed["read_only_rpc_source"], "loopback")
                self.assertTrue(confirmed["live_chain_checked"])

    def test_live_tip_receipt_code_hook_and_balance_tampering_rejected(self) -> None:
        source = self.saved["funded"]
        for attack, expected in (
            ("tip", "live chain tip"),
            ("transaction", "live funding transaction or receipt"),
            ("receipt", "live funding transaction or receipt"),
            ("code", "live bonus hook code"),
            ("hook_state", "live bonus hook or fee terms"),
            ("balance", "live bonus_escrow token balance"),
        ):
            with self.subTest(attack=attack):
                base = SavedChainRPC(source, self.bundle[0])

                def altered(method: str, params: list):
                    value = base(method, params)
                    if attack == "tip" and method == "eth_getBlockByNumber":
                        value["number"] = hex(int(value["number"], 16) + 1)
                    if attack == "transaction" and method == "eth_getTransactionByHash":
                        value["input"] = "0xdeadbeef"
                    if attack == "receipt" and method == "eth_getTransactionReceipt":
                        value["status"] = "0x0"
                    if attack == "code" and method == "eth_getCode" and params[0] == source["hook"]:
                        value = "0xdeadbeef"
                    if attack == "hook_state" and method == "eth_call" and params[0]["to"] == source["hook"]:
                        if params[0]["data"] == _calldata("state()"):
                            value = "0x1"
                    if attack == "balance" and method == "eth_call":
                        if params[0]["to"] == source["contracts"]["MockUSDC"]["address"]:
                            if params[0]["data"].lower() == _calldata("balanceOf(address)", source["hook"]):
                                value = "0x0"
                    return value

                with self.assertRaisesRegex(ValueError, expected):
                    verify_funding_record(source, self.assignments["funded"],
                                          bundle=self.bundle, live_rpc=altered)

    def test_symlink_and_dual_rpc_mode_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            verify_funding_file(PREVIEW / "funded.json", self.assignments["funded"],
                                confirm_live=True, live_rpc=lambda *_: None)
        with TemporaryDirectory() as folder:
            link = Path(folder) / "funded-link.json"
            link.symlink_to(PREVIEW / "funded.json")
            with self.assertRaisesRegex(ValueError, "symlinked"):
                verify_funding_file(link, self.assignments["funded"])


if __name__ == "__main__":
    unittest.main()
