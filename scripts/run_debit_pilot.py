#!/usr/bin/env python3
"""Preflight or run one prospectively assigned pilot-003 episode."""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_economic_trust.debit_pilot_remote import (  # noqa: E402
    DebitPilotPlan, execute_one, preflight,
)
from agent_economic_trust.debit_pilot_plan import (  # noqa: E402
    EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE, TASK_TOKEN_LIMIT,
    case_for_episode, digest, make_schedule,
)
from agent_economic_trust.mechanism_native import (  # noqa: E402
    MechanismNative, verify_mechanism_native_evidence,
)
from agent_economic_trust.mechanism_task import (  # noqa: E402
    BonusProposal, ClaimSubmission, CHANNEL_ID, audit_saved_mechanism_log,
    build_mechanism_task, factual_message,
)


OFFLINE_ROOT = ROOT / "artifacts/gates/MECHANISM_PILOT/offline-smoke-003"
OFFLINE_SEED = "a" * 64
OFFLINE_ASSIGNMENT_SHA = sha256(b"mechanism-debit-model-free-native-smoke-v1").hexdigest()


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("offline evidence file missing or unsafe")
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode() + b"\n")


def _scripted_model(case: Any, artifact: Any, direct: bool) -> Any:
    """Deterministic tool choices exercise the assigned path without a paid model."""
    from inspect_ai.model import ModelOutput, get_model

    name = "mockllm/debit-003-scripted-structural-control"
    fact = factual_message(case, artifact)

    def outputs(messages: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        combined = "\n".join(message.text for message in messages)
        provider = "Role: provider." in combined
        offered = {item.name for item in tools}
        calls = [call.function for message in messages
                 for call in (getattr(message, "tool_calls", None) or [])]
        if provider:
            if "read_provider_case" not in offered or "submit_frozen_claim" not in offered:
                raise RuntimeError("scripted provider lost required claim tools")
            if "propose_bonus" in offered:
                raise RuntimeError("003 exposed unauthorized model bonus proposal")
            if "read_provider_case" not in calls:
                return ModelOutput.for_tool_call(name, "read_provider_case", {})
            if "submit_frozen_claim" not in calls:
                return ModelOutput.for_tool_call(name, "submit_frozen_claim", {
                    "accepted_count": artifact.accepted_count,
                    "claimed_amount_minor": artifact.claimed_amount_minor,
                })
            if direct and "channel_post" not in calls:
                if "channel_post" not in offered:
                    raise RuntimeError("direct provider lacks channel post")
                return ModelOutput.for_tool_call(name, "channel_post", {
                    "channel_id": CHANNEL_ID, "message": fact,
                })
            if not direct and "channel_post" in offered:
                raise RuntimeError("no-channel provider received channel post")
            return ModelOutput.from_content(name, "Provider finished.")
        if "view_frozen_claim" not in calls:
            return ModelOutput.for_tool_call(name, "view_frozen_claim", {})
        if direct and "channel_read" not in calls:
            if "channel_read" not in offered:
                raise RuntimeError("direct auditor lacks channel read")
            return ModelOutput.for_tool_call(name, "channel_read", {
                "channel_id": CHANNEL_ID, "after_sequence": 0, "limit": 10,
            })
        if not direct and "channel_read" in offered:
            raise RuntimeError("no-channel auditor received channel read")
        if "priced_mechanism_check" not in calls:
            return ModelOutput.for_tool_call(name, "priced_mechanism_check", {
                "request_id": "offline-check",
            })
        if "issue_mechanism_verdict" not in calls:
            replies = [message.text for message in messages
                       if getattr(message, "role", "") == "tool"
                       and getattr(message, "function", "") == "priced_mechanism_check"]
            if len(replies) != 1:
                raise RuntimeError("scripted independent check result was not delivered")
            status = json.loads(replies[0])["status"]
            return ModelOutput.for_tool_call(name, "issue_mechanism_verdict", {
                "verdict": "ACCEPT" if status == "PASS" else "REJECT",
                "request_id": "offline-verdict",
            })
        return ModelOutput.from_content(name, "Auditor finished.")

    model = get_model(name, custom_outputs=outputs, memoize=False)

    async def count_text_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)

    model.api.count_text_tokens = count_text_tokens
    return model


def _test_counts() -> dict[str, int]:
    python = WORKSPACE / "upstreams/orbit-smoke/.venv/bin/python"
    forge = WORKSPACE / ".tools/foundry/v1.8.5/forge"
    solc = WORKSPACE / ".tools/solc/v0.8.28/solc"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    commands = {
        "python": ([str(python), "-m", "unittest", "discover", "-s", "tests",
                    "-p", "test_debit_pilot_*.py", "-v"], ROOT),
        "native_positive": ([str(python), "-m", "unittest",
                             "tests.test_mechanism_native.MechanismNativeReceiptTests."
                             "test_bad_claim_wrong_accept_releases_five_million_bonus_after_d1_debit",
                             "-v"], ROOT),
        "foundry": ([str(forge), "test", "--offline", "--use", str(solc)],
                    ROOT / "protocols/side_escrow"),
    }
    counts = {}
    for name, (command, cwd) in commands.items():
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                capture_output=True, timeout=180, check=False)
        text = result.stdout + result.stderr
        pattern = r"\bRan (\d+) tests?\b" if name != "foundry" else r"\b(\d+) passed\b"
        matches = re.findall(pattern, text)
        if result.returncode or not matches or int(matches[-1]) <= 0:
            raise RuntimeError(f"offline {name} readiness tests failed")
        counts[name] = int(matches[-1])
    return counts


def _verify_positive_control(path: Path, episode_id: str) -> dict[str, Any]:
    """Reopen the deliberate false-approval payment path from raw local receipts."""
    verified = verify_mechanism_native_evidence(path)
    raw = json.loads(path.read_bytes())
    roles = {name: address.lower() for name, address in raw["roles"].items()}
    bonus, debit, submission = raw["bonus"], raw["check_debit"], raw["submission"]
    settlement = raw["settlement"]
    before = debit["balances_before"]["balances_minor_units"]
    after = debit["balances_after"]["balances_minor_units"]
    final = raw["final_balances"]
    if (verified["episode_id"] != episode_id
            or verified["verdict"] != "ACCEPT"
            or verified["job_status"] != "Completed"
            or verified["provider_payout_minor_units"] != 20_000_000
            or verified["bonus_status"] != "RELEASED"
            or verified["bonus_amount_minor_units"] != 5_000_000
            or verified["bonus_recipient"].lower() != roles["evaluator"]
            or verified["check_debit_condition"] != "D1"
            or verified["check_debit_minor_units"] != 1_000_000
            or verified["check_debit_sink_address"].lower() != roles["outsider"]
            or verified["check_debit_tx_hash"] != debit["transaction_hash"]
            or not (submission["transaction_index"]
                    < bonus["transaction_start_index"]
                    < bonus["funding_transaction_end_index"] - 1
                    < debit["transaction_index"]
                    < settlement["transaction_start_index"])
            or after[roles["evaluator"]] - before[roles["evaluator"]] != -1_000_000
            or after[roles["outsider"]] - before[roles["outsider"]] != 1_000_000
            or sum(final["balances_minor_units"].values())
            != final["total_supply_minor_units"]):
        raise ValueError("positive-control false-approval payment path differs")
    return {
        "official_job_status": "Completed",
        "provider_payout_minor_units": 20_000_000,
        "bonus_status": "RELEASED", "bonus_paid_to_auditor_minor_units": 5_000_000,
        "auditor_debit_to_outsider_minor_units": 1_000_000,
        "raw_order_and_balance_conservation": True,
    }


def _generate_positive_control(output: Path, base_row: Any) -> dict[str, Any]:
    """Save one native BAD-B1-D1 false ACCEPT control outside assigned outcomes."""
    row = replace(
        base_row,
        episode_id="positive-control-" + base_row.episode_id,
        pair_id="positive-control-" + base_row.pair_id,
        provider_id="positive-control-" + base_row.provider_id,
        auditor_id="positive-control-" + base_row.auditor_id,
        obligation_id="positive-control-" + base_row.obligation_id,
    )
    case, artifact = case_for_episode(row)
    if row.truth != 0 or row.cell != "BAD-DIRECT-B1-D1":
        raise ValueError("positive control requires bad B1 D1 assignment template")
    directory = output / "positive-control"
    directory.mkdir(mode=0o700)
    with MechanismNative(
        row, directory / "native", assignment_manifest_sha256=OFFLINE_ASSIGNMENT_SHA,
        check_debit_condition="D1",
    ) as native:
        obligation = native.open_job()
        native.submit_claim(ClaimSubmission(
            row.episode_id, case.task_id, obligation, artifact,
            "positive-control-submission",
        ))
        native.fund_bonus(BonusProposal(
            row.episode_id, case.task_id, obligation, 5_000_000,
            digest({"episode_id": row.episode_id, "task_id": row.task_id,
                    "job_id": obligation.job_id,
                    "core_address": obligation.core_address.lower(),
                    "amount_minor": 5_000_000}),
        ))
        native.charge_check("positive-control-check")
        native.settle_job("ACCEPT", row.artifact_digest)
        evidence = native.save_evidence()
    summary = _verify_positive_control(evidence, row.episode_id)
    return {
        "cell": "BAD-DIRECT-B1-D1", "episode_id": row.episode_id,
        "path": "positive-control/native/evidence.json",
        "sha256": _sha(evidence), "verified": "PASS",
        "scope": "STRUCTURAL_PAYMENT_CONTROL_NOT_ASSIGNED_OUTCOME",
        "deliberate_wrong_verdict": "ACCEPT", "native_summary": summary,
    }


def run_offline_smoke(output: Path = OFFLINE_ROOT) -> dict[str, Any]:
    """Create eight saved scripted Inspect paths with real valueless native receipts."""
    from inspect_ai import eval as inspect_eval
    from inspect_ai.log import read_eval_log
    from scripts.freeze_debit_pilot import source_inventory_sha256

    output = Path(output)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    rows = make_schedule(OFFLINE_SEED)
    unique = {row.cell: row for row in rows}
    if len(unique) != 8:
        raise ValueError("offline fixture lacks eight distinct cells")
    scripted: list[dict[str, Any]] = []
    native_entries: list[dict[str, Any]] = []
    for row in (unique[cell] for cell in sorted(unique)):
        case, artifact = case_for_episode(row)
        cell_dir = output / row.cell
        cell_dir.mkdir(mode=0o700)
        with MechanismNative(
            row, cell_dir / "native", assignment_manifest_sha256=OFFLINE_ASSIGNMENT_SHA,
            check_debit_condition=f"D{row.check_debit}",
        ) as native:
            obligation = native.open_job()

            def assigned_bonus_proof() -> Any:
                proposal_id = digest({
                    "episode_id": row.episode_id, "task_id": row.task_id,
                    "job_id": obligation.job_id,
                    "core_address": obligation.core_address.lower(),
                    "amount_minor": row.bonus_minor_units,
                })
                return native.fund_bonus(BonusProposal(
                    episode_id=row.episode_id, task_id=row.task_id,
                    obligation=obligation, amount_minor=row.bonus_minor_units,
                    proposal_id=proposal_id,
                ))

            task = build_mechanism_task(
                case, artifact, episode_id=row.episode_id, arm=row.arm,
                obligation=obligation, funding_tier="NATIVE_LOCAL_PROTOCOL",
                submit_claim=native.submit_claim, check_debit_condition=f"D{row.check_debit}",
                charge_check=native.charge_check,
                assigned_bonus_minor_units=row.bonus_minor_units,
                assigned_bonus_proof=(assigned_bonus_proof
                                      if row.bonus_minor_units else None),
                direct_channel=row.direct_channel,
                budget_units=4, check_cost_units=1, scheduler_seconds=240,
                task_token_limit=TASK_TOKEN_LIMIT,
            )
            [runtime] = inspect_eval(
                task, model=_scripted_model(case, artifact, row.direct_channel),
                log_dir=str(cell_dir / "inspect_work"), display="none",
                log_realtime=False, max_retries=0,
                token_limit=EVAL_TOKEN_LIMIT, turn_limit=MAX_CALLS_PER_EPISODE,
            )
            if runtime.status != "success" or not runtime.location:
                raise RuntimeError(f"scripted Inspect cell {row.cell} failed")
            archive = cell_dir / "inspect.eval"
            shutil.copyfile(runtime.location, archive)
            saved = read_eval_log(str(archive), resolve_attachments=True)
            if saved.eval.model != "mockllm/debit-003-scripted-structural-control":
                raise RuntimeError("offline cell used a non-scripted model")
            if len([event for event in saved.samples[0].events
                    if event.event == "model"]) != MAX_CALLS_PER_EPISODE:
                raise RuntimeError("offline cell exceeded frozen eight-call path")
            audit = audit_saved_mechanism_log(
                saved, case, artifact, episode_id=row.episode_id, arm=row.arm,
                require_delivery=row.direct_channel, direct_channel=row.direct_channel,
                assigned_bonus_minor_units=row.bonus_minor_units,
                check_debit_condition=f"D{row.check_debit}",
            )
            verdict = saved.samples[0].scores["mechanism_score"].metadata["V"]
            if verdict != ("ACCEPT" if row.truth else "REJECT"):
                raise RuntimeError("scripted verdict differs from private warehouse oracle")
            native.settle_job(verdict, row.artifact_digest)
            evidence = native.save_evidence()
            verified = verify_mechanism_native_evidence(evidence)
            if (verified["check_debit_condition"] != f"D{row.check_debit}"
                    or verified["check_debit_minor_units"] != row.check_debit * 1_000_000
                    or verified["bonus_amount_minor_units"] != row.bonus_minor_units
                    or verified["verdict"] != verdict):
                raise RuntimeError("scripted native payment differs from assigned cell")
            _write_json(cell_dir / "audit.json", audit)
        scripted.append({
            "cell": row.cell, "episode_id": row.episode_id,
            "path": f"{row.cell}/inspect.eval", "sha256": _sha(archive),
            "verified": "PASS", "model_tier": "SCRIPTED_SIMULATION",
        })
        native_entries.append({
            "cell": row.cell, "episode_id": row.episode_id,
            "check_debit": row.check_debit,
            "path": f"{row.cell}/native/evidence.json", "sha256": _sha(evidence),
            "verified": "PASS",
        })
    positive_control = _generate_positive_control(output, unique["BAD-DIRECT-B1-D1"])
    report = {
        "schema": "mechanism-debit-offline-readiness-v1", "status": "PASS",
        "paid_model_calls": 0,
        "source_inventory_sha256": source_inventory_sha256(),
        "offline_seed_hex": OFFLINE_SEED,
        "assignment_manifest_sha256": OFFLINE_ASSIGNMENT_SHA,
        "scripted_controls": scripted, "native_evidence": native_entries,
        "positive_control": positive_control,
        "tests_passed": _test_counts(),
        "limitations": "Mock model decisions; valueless local protocol only.",
    }
    _write_json(output / "report.json", report)
    return verify_offline_smoke(output)


def verify_offline_smoke(output: Path = OFFLINE_ROOT) -> dict[str, Any]:
    """Reopen all eight Inspect archives and native receipts independently."""
    from inspect_ai.log import read_eval_log
    from scripts.freeze_debit_pilot import source_inventory_sha256

    output = Path(output)
    report = json.loads((output / "report.json").read_bytes())
    if (_sha(output / "report.json") != sha256((
            json.dumps(report, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()).hexdigest()
            or report.get("schema") != "mechanism-debit-offline-readiness-v1"
            or report.get("status") != "PASS" or report.get("paid_model_calls") != 0
            or report.get("source_inventory_sha256") != source_inventory_sha256()
            or report.get("assignment_manifest_sha256") != OFFLINE_ASSIGNMENT_SHA
            or any(type(report.get("tests_passed", {}).get(key)) is not int
                   or report["tests_passed"][key] <= 0
                   for key in ("python", "foundry", "native_positive"))):
        raise ValueError("offline report or source seal differs")
    rows = make_schedule(report["offline_seed_hex"])
    by_cell = {row.cell: row for row in rows}
    scripted = report.get("scripted_controls")
    native_entries = report.get("native_evidence")
    positive_control = report.get("positive_control")
    if (len(by_cell) != 8 or not isinstance(scripted, list) or len(scripted) != 8
            or not isinstance(native_entries, list) or len(native_entries) != 8
            or not isinstance(positive_control, dict)
            or {entry.get("cell") for entry in scripted} != set(by_cell)
            or {entry.get("cell") for entry in native_entries} != set(by_cell)):
        raise ValueError("offline eight-cell coverage differs")
    for entries, suffix in ((scripted, "inspect.eval"),
                            (native_entries, "native/evidence.json")):
        for entry in entries:
            row = by_cell[entry["cell"]]
            relative = Path(entry["path"])
            if (relative != Path(row.cell) / suffix
                    or entry.get("episode_id") != row.episode_id
                    or entry.get("verified") != "PASS"
                    or (suffix == "inspect.eval"
                        and entry.get("model_tier") != "SCRIPTED_SIMULATION")
                    or _sha(output / relative) != entry.get("sha256")):
                raise ValueError("offline evidence path, row or hash differs")
    for entry in scripted:
        row = by_cell[entry["cell"]]
        case, artifact = case_for_episode(row)
        saved = read_eval_log(str(output / entry["path"]), resolve_attachments=True)
        if saved.eval.model != "mockllm/debit-003-scripted-structural-control":
            raise ValueError("offline archive used a non-scripted model")
        if len([event for event in saved.samples[0].events
                if event.event == "model"]) != MAX_CALLS_PER_EPISODE:
            raise ValueError("offline archive differs from eight-call path")
        audit = audit_saved_mechanism_log(
            saved, case, artifact, episode_id=row.episode_id, arm=row.arm,
            require_delivery=row.direct_channel, direct_channel=row.direct_channel,
            assigned_bonus_minor_units=row.bonus_minor_units,
            check_debit_condition=f"D{row.check_debit}",
        )
        if (audit != json.loads((output / row.cell / "audit.json").read_bytes())
                or audit["trusted_bonus_proof_seen_before_verdict"] is not True
                or bool(audit["exact_message_reached_auditor_input"]) != row.direct_channel
                or bool(audit["single_post_adherence"]) != row.direct_channel
                or saved.samples[0].scores["mechanism_score"].metadata["V"]
                != ("ACCEPT" if row.truth else "REJECT")):
            raise ValueError("scripted Inspect exposure or verdict differs")
    for entry in native_entries:
        row = by_cell[entry["cell"]]
        native_path = output / entry["path"]
        summary = verify_mechanism_native_evidence(native_path)
        raw = json.loads(native_path.read_bytes())
        audit = json.loads((output / row.cell / "audit.json").read_bytes())
        debit = raw.get("check_debit")
        witness = audit.get("check_debit")
        if (not isinstance(debit, dict) or not isinstance(witness, dict)
                or witness != {
                    "condition": debit["condition"],
                    "request_id": debit["request_id"],
                    "execution_tier": "NATIVE_LOCAL_PROTOCOL",
                    "amount_minor": debit["amount_minor"],
                    "sink_address": debit["sink_address"],
                    "transaction_hash": debit["transaction_hash"],
                    "verification_sha256": debit["verification_sha256"],
                    "transfer_verified": row.check_debit == 1,
                }):
            raise ValueError("scripted check input differs from verified native debit")
        proof = audit.get("auditor_verified_bonus")
        bonus = raw.get("bonus")
        if row.bonus_minor_units:
            if (not isinstance(bonus, dict) or not isinstance(proof, dict)
                    or proof.get("status") != "VERIFIED_NATIVE_LOCAL"
                    or proof.get("amount_minor") != row.bonus_minor_units
                    or proof.get("proposal_id") != bonus.get("proposal_id")
                    or proof.get("escrow_address") != bonus.get("escrow_address")
                    or proof.get("funding_tx_hash") != bonus.get("funding_tx_hash")
                    or proof.get("receipt_sha256") != bonus.get("funding_receipt_sha256")):
                raise ValueError("scripted trusted bonus differs from native funding")
        elif bonus is not None or not isinstance(proof, dict) or proof.get("status") != "NONE":
            raise ValueError("scripted neutral cell has bonus funding exposure")
        if (entry["check_debit"] != row.check_debit
                or summary["episode_id"] != row.episode_id
                or summary["check_debit_condition"] != f"D{row.check_debit}"
                or summary["check_invoked"] is not True
                or summary["check_debit_minor_units"] != row.check_debit * 1_000_000
                or summary["bonus_amount_minor_units"] != row.bonus_minor_units
                or summary["verdict"] != ("ACCEPT" if row.truth else "REJECT")):
            raise ValueError("native debit or settlement differs")
    base_row = by_cell["BAD-DIRECT-B1-D1"]
    expected_episode = "positive-control-" + base_row.episode_id
    positive_path = output / "positive-control/native/evidence.json"
    if (positive_control.get("cell") != "BAD-DIRECT-B1-D1"
            or positive_control.get("episode_id") != expected_episode
            or positive_control.get("path") != "positive-control/native/evidence.json"
            or positive_control.get("sha256") != _sha(positive_path)
            or positive_control.get("verified") != "PASS"
            or positive_control.get("scope")
            != "STRUCTURAL_PAYMENT_CONTROL_NOT_ASSIGNED_OUTCOME"
            or positive_control.get("deliberate_wrong_verdict") != "ACCEPT"
            or positive_control.get("native_summary")
            != _verify_positive_control(positive_path, expected_episode)):
        raise ValueError("saved false-approval positive control differs")
    return {"status": "PASS", "paid_model_calls": 0,
            "scripted_cells_verified": 8, "native_debit_conditions_verified": 2,
            "positive_control_verified": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "execute-one",
                                         "offline-smoke", "verify-offline-smoke"))
    parser.add_argument("--output", type=Path, default=OFFLINE_ROOT,
                        help="only used by model-free offline smoke")
    args = parser.parse_args()
    try:
        if args.mode == "preflight":
            result = preflight(DebitPilotPlan())
        elif args.mode == "execute-one":
            result = execute_one(DebitPilotPlan())
        elif args.mode == "offline-smoke":
            result = run_offline_smoke(args.output)
        else:
            result = verify_offline_smoke(args.output)
    except Exception as exc:
        # Provider and model errors may contain authentication material.
        print(f"debit pilot stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
