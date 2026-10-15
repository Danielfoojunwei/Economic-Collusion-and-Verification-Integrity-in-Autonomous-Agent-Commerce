#!/usr/bin/env python3
"""Read-only W11 stopped-round forensic preflight; no inference or ledger writes."""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.remote import (  # noqa: E402
    APPROVED_MODEL_ID, PROJECT_LEDGER_PATH, _usage_for,
)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import estimate_usage  # noqa: E402
from agent_economic_trust.w10_factorial_remote import (  # noqa: E402
    _decision_signature, _scan_native_log_for_secret,
)
from agent_economic_trust.w11_market_log_integrity import (  # noqa: E402
    _behavior, audit_saved_attachment_resolution,
)
from agent_economic_trust.w11_market_native import verify_market_evidence  # noqa: E402
from agent_economic_trust.w11_market_plan import (  # noqa: E402
    canonical, case_for_round, digest, make_market_schedule, manifest,
)
from agent_economic_trust.w11_market_remote import (  # noqa: E402
    _load_prior_entries, _market_rows, sample_oracle,
)
from agent_economic_trust.w11_market_task import (  # noqa: E402
    assigned_message, audit_saved_market_log,
)


EXPECTED_PRIOR_SOURCE = "src/agent_economic_trust/w11_market_remote.py"
EXPECTED_PUBLIC_MODEL_SHA = "71e95fa7cf157390232d6e13a44bf61ea6b9b6a7961ced6c8f37a684b51b499a"
EXPECTED_STOPPED_USAGE_ESTIMATE = Decimal("0.132870")
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
GENERIC_CREDENTIAL_PATTERNS = (
    re.compile(rb"(?i)sk-or(?:-v1)?-[A-Za-z0-9_-]{24,}"),
    re.compile(rb"(?i)Bearer[ \t]+[A-Za-z0-9._~-]{32,}"),
    re.compile(rb"(?i)OPENROUTER_API_KEY[ \t]*[:=][ \t]*[\"']?[A-Za-z0-9._~-]{24,}"),
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _generic_credential_scan(path: Path, resolved_log) -> str:
    """Flag recognizable key forms without printing any candidate value."""
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("saved native Inspect archive exceeds scan limit")
    payloads = [path.read_bytes(), resolved_log.model_dump_json().encode("utf-8")]
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if (len(members) > 4096
                    or sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES):
                raise ValueError("saved native Inspect archive exceeds scan limit")
            for member in members:
                if member.file_size > MAX_MEMBER_BYTES:
                    raise ValueError("saved native Inspect member exceeds scan limit")
                payloads.append(archive.read(member))
    if any(pattern.search(payload) for payload in payloads
           for pattern in GENERIC_CREDENTIAL_PATTERNS):
        raise ValueError("saved native Inspect archive contains credential-like text")
    return "PASS_NO_CANDIDATE"


def _freeze_module():
    spec = spec_from_file_location("w11_historical_freeze", ROOT / "scripts/freeze_w11_market.py")
    if spec is None or spec.loader is None:
        raise ValueError("W11 freeze validator is unavailable")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forensic_preflight(plan_dir: Path, runs_dir: Path, preimage_root: Path,
                       *, market_id: str, episode_id: str) -> dict:
    """Independently examine the archived native run and original source seal."""
    plan_dir, runs_dir, preimage_root = map(Path, (plan_dir, runs_dir, preimage_root))
    plan_path = plan_dir / "assignment_manifest.json"
    frozen = json.loads(plan_path.read_bytes())
    assignment_sha = _sha(plan_path)
    seed = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    private = json.loads((plan_dir / "private_rounds.json").read_bytes())
    rows = make_market_schedule(seed, blocks=len({item["block_id"] for item in private}),
                                r_values=tuple(sorted({item["r"] for item in private})))
    expected_core = json.loads(canonical(manifest(seed, rows)))
    if (frozen.get("schema") != "w11-prospective-market-assignment-v2"
            or any(frozen.get(key) != value for key, value in expected_core.items())
            or json.loads(canonical([row.__dict__ for row in rows])) != private
            or frozen["private_rows_sha256"] != digest(private)):
        raise ValueError("historical W11 assignment differs from frozen schedule")
    freezer = _freeze_module()
    if (frozen["upstream_pins"] != freezer.upstream_pins()
            or frozen["g4_aggregate_manifest_sha256"] != _sha(freezer.G4_AGGREGATE)):
        raise ValueError("historical upstream or G4 prerequisite seal differs")
    active_source_drift = []
    for name, expected_sha in frozen["source_sha256"].items():
        current_path = ROOT / name
        if _sha(current_path) != expected_sha:
            if name != EXPECTED_PRIOR_SOURCE or _sha(preimage_root / name) != expected_sha:
                raise ValueError(f"historical source preimage missing or changed: {name}")
            active_source_drift.append(name)
    if _sha(preimage_root / EXPECTED_PRIOR_SOURCE) != frozen["source_sha256"][EXPECTED_PRIOR_SOURCE]:
        raise ValueError("archived assignment-006 runner is not its original preimage")
    if market_id not in frozen["market_execution_order"]:
        raise ValueError("stopped market is outside frozen execution order")
    market = _market_rows(rows, market_id)
    target = next((row for row in market if row.episode_id == episode_id), None)
    if target is None or target.round_index != 2 or target.communication_mode != "DIRECT":
        raise ValueError("forensic target is not the original stopped direct round")
    ledger = BudgetLedger(PROJECT_LEDGER_PATH).snapshot()
    run_id = f"w11-market-{assignment_sha[:12]}-{episode_id}"
    billing = ledger["runs"].get(run_id)
    if (not ledger["blocked"] or run_id not in ledger["unknown_run_ids"]
            or billing is None or billing["status"] != "UNKNOWN"
            or Decimal(billing["reserved_usd"]) != Decimal("4.259840")
            or billing["metadata"] != {
                "assignment_sha": assignment_sha, "episode_id": episode_id,
                "market_id": market_id, "model_id": APPROVED_MODEL_ID,
            }):
        raise ValueError("stopped model reservation is not the original UNKNOWN ledger run")
    # Preserve the first completed market and every preceding round as
    # independently revalidated prior evidence, even though the ledger is blocked.
    complete_prior_markets = []
    for earlier_market_id in frozen["market_execution_order"][:
            frozen["market_execution_order"].index(market_id)]:
        earlier = _market_rows(rows, earlier_market_id)
        verified = _load_prior_entries(earlier, 4, runs_dir, assignment_sha,
                                       ledger, frozen["source_sha256"])
        if len(verified) != 4:
            raise ValueError("a preceding completed market lost independent verification")
        complete_prior_markets.append(earlier_market_id)
    entries = _load_prior_entries(market, 2, runs_dir, assignment_sha,
                                  ledger, frozen["source_sha256"])
    if len(entries) != 2:
        raise ValueError("stopped market lacks two verified prior rounds")
    episode_dir = runs_dir / market_id / "episodes" / episode_id
    stopped_path, log_path = episode_dir / "STOPPED.json", episode_dir / "inspect.eval"
    stopped = json.loads(stopped_path.read_bytes())
    log_sha = _sha(log_path)
    if (stopped.get("market_id") != market_id
            or stopped.get("episode_id") != episode_id
            or stopped.get("stage") != "provider_request"
            or stopped.get("error_type") != "RemoteBoundaryError"
            or stopped.get("budget_state") != "UNKNOWN"
            or stopped.get("model_calls") != 8
            or stopped.get("native_inspect_sha256") != log_sha
            or stopped.get("native_payment_sha256") is not None
            or (episode_dir / "episode_record.json").exists()):
        raise ValueError("STOPPED marker differs from incomplete original episode")
    unresolved = read_eval_log(str(log_path), resolve_attachments=False)
    resolved = read_eval_log(str(log_path), resolve_attachments=True)
    credential = os.environ.get("OPENROUTER_API_KEY")
    generic_credential_scan = _generic_credential_scan(log_path, resolved)
    exact_credential_scan = "SKIP_NO_KEY"
    if credential:
        _scan_native_log_for_secret(log_path, resolved, credential)
        exact_credential_scan = "PASS"
    if (resolved.status != "success" or len(resolved.samples or []) != 1
            or resolved.eval.model != f"openrouter/{APPROVED_MODEL_ID}"
            or resolved.samples[0].id != target.task_id
            or resolved.samples[0].error or resolved.samples[0].limit):
        raise ValueError("saved Inspect sample did not finish successfully")
    sample = resolved.samples[0]
    model_events = [event for event in sample.events if event.event == "model"]
    if (len(model_events) != 8
            or any(event.model != f"openrouter/{APPROVED_MODEL_ID}"
                   or getattr(event.config, "reasoning_effort", None) != "high"
                   or event.output is None or event.output.error
                   for event in model_events)):
        raise ValueError("saved model calls differ from approved eight-call route")
    usage = _usage_for(resolved, APPROVED_MODEL_ID)
    for field in ("input_tokens", "output_tokens", "total_tokens",
                  "input_tokens_cache_read", "input_tokens_cache_write", "reasoning_tokens"):
        if sum(getattr(event.output.usage, field) or 0 for event in model_events) != (getattr(usage, field) or 0):
            raise ValueError(f"per-call usage sum differs from saved sample: {field}")
    pricing_rows = []
    for checked_market_id in (*complete_prior_markets, market_id):
        checked_rows = _market_rows(rows, checked_market_id)
        for checked_row in checked_rows[:4 if checked_market_id != market_id else 2]:
            run_manifest = json.loads((runs_dir / checked_market_id / "episodes" /
                                       checked_row.episode_id / "run_manifest.json").read_bytes())
            pricing_rows.append(run_manifest["pricing_snapshot"])
    pricing = pricing_rows[0]
    relevant_prices = ("model_id", "catalog_model_sha256", "input_usd_per_token",
                       "output_usd_per_token", "cache_read_usd_per_token",
                       "cache_write_usd_per_token", "request_usd")
    if (pricing["catalog_model_sha256"] != EXPECTED_PUBLIC_MODEL_SHA
            or any(any(item[key] != pricing[key] for key in relevant_prices)
                   for item in pricing_rows[1:])):
        raise ValueError("six verified prior W11 pricing snapshots differ")
    usage_estimate = estimate_usage(pricing, usage, calls=8)
    if usage_estimate != EXPECTED_STOPPED_USAGE_ESTIMATE:
        raise ValueError("saved eight-call usage differs from conservative public-rate estimate")
    resolution = audit_saved_attachment_resolution(unresolved, resolved)
    before, after = _behavior(unresolved), _behavior(resolved)
    changed = [(i, left, right) for i, (left, right) in enumerate(zip(before, after))
               if left != right]
    decision_before = _decision_signature(unresolved)
    decision_after = _decision_signature(resolved)
    changed_decisions = [i for i, (left, right) in enumerate(zip(decision_before, decision_after))
                         if left != right]
    post_model = next((item for item in changed if item[0] == 4), None)
    post_tool = next((item for item in changed if item[0] == 5), None)
    if (changed_decisions != [4] or post_model is None or post_tool is None
            or post_model[1]["kind"] != "model"
            or post_tool[1]["kind"] != "tool"
            or post_tool[2]["function"] != "channel_post"
            or resolution["attachment_expansions"] < 2
            or any(item[1]["kind"] != "model" for item in changed if item[0] != 5)):
        raise ValueError("native archive changed beyond permitted attachment resolution")
    model_call_before = post_model[1]["output"]["choices"][0]["message"]["tool_calls"][0]
    model_call_after = post_model[2]["output"]["choices"][0]["message"]["tool_calls"][0]
    assigned = assigned_message(target)
    if (model_call_before["function"] != "channel_post"
            or model_call_after["function"] != "channel_post"
            or not model_call_before["arguments"]["message"].startswith("attachment://")
            or model_call_after["arguments"]["message"] != assigned
            or post_tool[2]["arguments"]["message"] != assigned):
        raise ValueError("posted model/tool content is not the exact assigned resolved text")
    channel = audit_saved_market_log(resolved, target, entries=entries)
    if (channel["status"] != "PASS" or not channel["assigned_message_posted"]
            or channel["assigned_message_read"]):
        raise ValueError("observed direct post/read classification differs")
    case, artifact = case_for_round(target)
    score = sample.scores["protected_receipt_score"].metadata
    if (sample_oracle(case, artifact) != "FAIL"
            or score.get("artifact_digest") != artifact.digest()
            or score.get("Y") != 0 or score.get("V") != "REJECT"
            or score.get("Q") is not True
            or score.get("check_spent_units") != target.check_cost_units):
        raise ValueError("saved verdict/check differs from independent private oracle")
    native_dir = runs_dir / market_id / "native"
    native_path = native_dir / "evidence.json"
    native_summary = verify_market_evidence(native_path)
    native = json.loads(native_path.read_bytes())
    checkpoint = native["chain_checkpoint"]
    state_path = native_dir / "anvil-state.hex"
    if (native_summary["market_id"] != market_id
            or native["assignment_manifest_sha256"] != assignment_sha
            or native["R"] != target.r
            or _sha(state_path) != checkpoint["state_sha256"]
            or state_path.stat().st_size != checkpoint["state_bytes"]
            or native["active_obligation"] != target.obligation_id):
        raise ValueError("saved open native market checkpoint differs from assignment")
    native_round = next((item for item in native["rounds"]
                         if item["episode_id"] == episode_id), None)
    if (native_round is None or native_round["obligation_id"] != target.obligation_id
            or native_round["artifact_digest"] != target.artifact_digest
            or native_round["status"] != "OPEN" or native_round["settlement"] is not None
            or native_round["fee_minor_units"] != target.audit_fee_minor_units):
        raise ValueError("stopped ERC-8183 job is not the original funded open obligation")
    return {
        "schema": "w11-stopped-readonly-forensic-v1",
        "mutation_count": 0, "paid_model_calls": 0,
        "assignment_manifest_sha256": assignment_sha,
        "historical_source_preimage_sha256": frozen["source_sha256"][EXPECTED_PRIOR_SOURCE],
        "active_source_drift": active_source_drift,
        "source_seal_interpretation": "historical preimage verified; current runner is a prospective amendment",
        "exact_credential_scan": exact_credential_scan,
        "generic_candidate_scan": generic_credential_scan,
        "completed_prior_markets_reverified": complete_prior_markets,
        "same_market_prior_rounds_reverified": len(entries),
        "market_id": market_id, "episode_id": episode_id,
        "stop_stage": stopped["stage"], "original_stopped_sha256": _sha(stopped_path),
        "native_inspect_sha256": log_sha,
        "attachment_resolution": resolution,
        "assigned_message_sha256": sha256(assigned.encode()).hexdigest(),
        "assigned_message_posted": channel["assigned_message_posted"],
        "assigned_message_read": channel["assigned_message_read"],
        "oracle_truth": score["Y"], "verdict": score["V"], "checked": score["Q"],
        "model_calls": len(model_events), "model_usage": usage.model_dump(mode="json"),
        "conservative_public_rate_usage_estimate_usd": format(usage_estimate, "f"),
        "pricing_basis": "six independently verified prior W11 run manifests; no network access",
        "billing_interpretation": "saved usage estimate only; provider invoice and run-specific account delta unavailable",
        "ledger_status": billing["status"], "ledger_blocked": ledger["blocked"],
        "ledger_reserved_usd": billing["reserved_usd"],
        "native_evidence_sha256": native_summary["evidence_sha256"],
        "native_status": native_round["status"],
        "native_fee_receipt_sha256": native_round["fee_receipt_sha256"],
        "native_job_id": native_round["job_id"],
        "native_state_sha256": checkpoint["state_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preimage-root", type=Path, required=True)
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--episode-id", required=True)
    args = parser.parse_args()
    result = forensic_preflight(args.assignment_dir, args.output_dir, args.preimage_root,
                                market_id=args.market_id, episode_id=args.episode_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
