"""Public-only, pre-view funding transcript for a local BILATERAL030 job.

Writing this archive is a controller action, not independent verification. The
model-facing attestation must come from a separate read-only verifier.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from scripts.run_erc8183_local import CHAIN_ID, GENESIS_TIMESTAMP, PIN

from .bilateral030_native import Bilateral030NativeBridge
from .bilateral030_plan import canonical


BASE_STEPS = (
    "deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
    "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
    "setup.mint", "setup.approve", "terms.platform_zero",
    "endowment.mint", "provider_endowment.mint", "hook.deploy",
    "hook.whitelist", "job.create", "job.set_budget", "job.fund", "hook.bind",
)
BONUS_STEPS = ("bonus.approve", "bonus.fund")
ROOT = Path(__file__).resolve().parents[2]


class FundingArchiveError(RuntimeError):
    pass


def make_funding_archive(bridge: Bilateral030NativeBridge) -> dict:
    """Freeze raw public setup/funding receipts before the first model view."""
    if type(bridge) is not Bilateral030NativeBridge:
        raise TypeError("native BILATERAL030 bridge required")
    if (bridge.claim_choice is not None or bridge.claim_receipt is not None
            or bridge.check_receipt is not None or bridge.early_receipt is not None
            or bridge.after_claim is not None or bridge.after_check is not None
            or bridge.after_early is not None or bridge.final is not None
            or bridge.deferred or bridge.buyer_revealed
            or bridge.final_receipt is not None):
        raise FundingArchiveError("funding archive must precede every agent choice")
    prefix = bridge.public_prefix()
    steps = BASE_STEPS + (BONUS_STEPS if bridge.row.accept_bonus_minor else ())
    if tuple(tx["step"] for tx in bridge.helper.transactions) != steps:
        raise FundingArchiveError("native pre-view transaction order differs")
    transactions = [deepcopy(bridge._transaction(step)) for step in steps]
    job_fund = transactions[BASE_STEPS.index("job.fund")]
    bonus_fund = transactions[-1] if bridge.row.accept_bonus_minor else None
    h = bridge.helper
    row = bridge.row
    code = h.rpc.call("eth_getCode", [bridge.hook, "latest"])
    if (h.job(bridge.job_id)["status"] != "Funded"
            or h.uint(bridge.hook, "state()") != (2 if bonus_fund else 1)
            or h.balance(bridge.hook) != row.accept_bonus_minor
            or not code.startswith("0x") or len(code) <= 2):
        raise FundingArchiveError("native funded hook state differs")
    archive = {
        "schema": "erc8183-bilateral030-funding-v1",
        "gate": "PREVIEW_FUNDING_CONTROLLER_ARCHIVE_UNVERIFIED",
        "model_behavior_tier": "NO_MODEL_VIEW_YET",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "public_assignment": {
            "episode_id": row.episode_id,
            "obligation_id": row.obligation_id,
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id,
            "assigned_bonus_minor": row.accept_bonus_minor,
        },
        "source": {
            "official_commit": PIN,
            "bridge_sha256": sha256((Path(__file__).parent / "bilateral030_native.py").read_bytes()).hexdigest(),
            "hook_source_sha256": sha256((ROOT /
                                          "protocols/side_escrow/src/FirstClaimBonusHook.sol").read_bytes()).hexdigest(),
            "archive_exporter_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "chain": {"rpc_host": "127.0.0.1", "port": bridge.port,
                  "chain_id": CHAIN_ID, "genesis_timestamp": GENESIS_TIMESTAMP},
        "actors": dict(h.roles), "contracts": deepcopy(h.contracts),
        "asset": {"name": "MockUSDC", "decimals": 6,
                  "supply_minor_units": h.initial_supply, "real_value": 0},
        "public_prefix": prefix,
        "public_prefix_sha256": sha256(canonical(prefix)).hexdigest(),
        "public_report": dict(bridge.public_report),
        "public_description": bridge.description,
        "report_digest": bridge.report_digest,
        "job_id": bridge.job_id, "expiry": bridge.expiry,
        "hook": bridge.hook, "hook_runtime_code": code,
        "funded_job": h.job(bridge.job_id),
        "hook_state": h.uint(bridge.hook, "state()"),
        "hook_job_id": h.uint(bridge.hook, "jobId()"),
        "opening": deepcopy(bridge.opening), "funded": deepcopy(bridge.funded),
        "job_funding_receipt_sha256": sha256(canonical(job_fund["raw_receipt"])).hexdigest(),
        "bonus_funding_receipt_sha256": (sha256(canonical(bonus_fund["raw_receipt"])).hexdigest()
                                         if bonus_fund else None),
        "transactions": transactions,
        "independent_funding_replay": False,
    }
    serialized = canonical(archive)
    forbidden = (b'"truth"', b'"group"', b'"protected_oracle"', b'"buyer_records"',
                 b'"purchase_order_amount_cents"', b'"credit_note_amount_cents"',
                 b'"net_amount_cents"')
    if any(item in serialized for item in forbidden):
        raise FundingArchiveError("protected buyer data entered the public funding archive")
    return archive


def write_funding_archive(bridge: Bilateral030NativeBridge, target: Path) -> Path:
    """Persist a new public transcript while its funded Anvil job is alive."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    archive = make_funding_archive(bridge)
    target.write_text(json.dumps(archive, sort_keys=True, indent=2) + "\n")
    return target
