"""Zero-model local ERC-8183 native controls for the prospective FEE012 block.

The fixed seed is an offline test vector. It is never a live assignment seed.
The deliberately wrongful BAD ACCEPT row is a scripted mechanism control, not
an observation of LLM behavior or bilateral collusion.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .erc8183_fee_native import FeeNativeController
from .erc8183_fee_native_verifier import verify_complete, verify_prefix
from .fee012_plan import Fee012Row, make_schedule
from scripts import verify_erc8183_fee_control as controls


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "artifacts/prospective/ERC8183_FEE012/offline-native-001"
SEED_VECTOR = "49" * 32


class OfflineFeeNativeController(FeeNativeController):
    """Use unchanged official controller, but label its scripted receipt truthfully."""

    def _evidence(self) -> dict:
        evidence = super()._evidence()
        if evidence["model_behavior_tier"] != "REAL_LLM_REMOTE_APPROVED":
            raise ValueError("inherited native controller tier changed")
        evidence["model_behavior_tier"] = "SCRIPTED_SIMULATION"
        return evidence


def replay_scripted_receipt(path: Path, row: Fee012Row) -> dict:
    """Replay immutable raw receipt across the known isolated-build path.

    The archived control was compiled at /tmp/upstreams/erc8183. A canonical
    checkout builds the *same pinned artifacts* under /workspace/upstreams.
    The inherited verifier compares absolute artifact_path strings as well as
    hashes. Validate each historical path and current SHA before changing only
    the in-memory compatibility view. Never read a historical alias or rewrite
    a saved receipt, so a fresh setup needs no /tmp/upstreams symlink.
    """
    evidence = json.loads(path.read_text())
    if evidence.get("model_behavior_tier") != "SCRIPTED_SIMULATION":
        raise ValueError("FEE012 offline receipt is mislabeled as a remote model")
    contracts = evidence.get("contracts")
    names = {"MockUSDC", "ERC8183", "ERC1967Proxy"}
    if not isinstance(contracts, dict) or set(contracts) != names:
        raise ValueError("FEE012 offline compiled artifact set differs")
    compatibility = copy.deepcopy(evidence)
    for name in sorted(names):
        saved = contracts[name]
        historical = Path("/tmp/upstreams/erc8183/out") / f"{name}.sol" / f"{name}.json"
        current = controls.UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        if (not isinstance(saved, dict)
                or saved.get("artifact_path") != str(historical)
                or not current.is_file() or current.is_symlink()
                or saved.get("artifact_sha256") != _sha(current)):
            raise ValueError(f"FEE012 offline {name} artifact path or digest differs")
        compatibility["contracts"][name]["artifact_path"] = str(current)
    compatibility["model_behavior_tier"] = "REAL_LLM_REMOTE_APPROVED"
    result = (verify_complete(compatibility, row) if path.name == "native-evidence.json"
              else verify_prefix(compatibility, row))
    return {**result, "model_behavior_tier": "SCRIPTED_SIMULATION"}


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE012 control file absent or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def cases() -> tuple[tuple[str, Fee012Row, str | None], ...]:
    rows = make_schedule(SEED_VECTOR)
    result = [(f"assigned-{i + 1}", row,
               "REJECT" if row.truth == "bad" else "ACCEPT")
              for i, row in enumerate(rows)]
    unsafe = next(row for row in rows if row.truth == "bad"
                  and row.fee_term == "NATIVE_CONTINGENT" and row.contact == "CHANNEL")
    result.append(("scripted-bad-accept-positive-control",
                   replace(unsafe, episode_id=unsafe.episode_id + "-unsafe",
                           obligation_id=unsafe.obligation_id + "-unsafe"), "ACCEPT"))
    incomplete = next(row for row in rows if row.truth == "bad"
                      and row.fee_term == "CLIENT_PREPAID"
                      and row.contact == "NO_CONTACT")
    result.append(("checked-no-verdict-prefix-control",
                   replace(incomplete, episode_id=incomplete.episode_id + "-prefix",
                           obligation_id=incomplete.obligation_id + "-prefix"), None))
    return tuple(result)


def run(path: Path = ARCHIVE) -> dict:
    path = Path(path)
    if path.exists():
        raise FileExistsError("FEE012 offline archive already exists")
    path.mkdir(parents=True, mode=0o700)
    records = []
    for name, row, verdict in cases():
        native_dir = path / name
        with OfflineFeeNativeController(row, native_dir) as controller:
            checked = controller.buy_check(row, "control-" + name)
            if checked["oracle_status"] != ("PASS" if row.truth == "good" else "FAIL"):
                raise ValueError("control buyer oracle changed")
            if verdict is not None:
                controller.settle(row, verdict, True)
        native_path = native_dir / (
            "native-evidence.json" if verdict else "native-partial.json")
        verified = replay_scripted_receipt(native_path, row)
        records.append({"name": name, "row": asdict(row),
                        "scripted_verdict": verdict,
                        "native_path": str(native_path.relative_to(path)),
                        "native_sha256": _sha(native_path),
                        "native_verification": verified})
    report = {"schema": "fee012-offline-native-controls-v1",
              "status": "PASS", "model_behavior_tier": "SCRIPTED_SIMULATION",
              "payment_tier": "NATIVE_LOCAL_PROTOCOL",
              "live_assignment_seed_used": False,
              "paid_model_calls": 0,
              "cases": records}
    (path / "report.json").write_text(json.dumps(report, sort_keys=True,
                                               indent=2) + "\n")
    return verify(path)


def verify(path: Path = ARCHIVE) -> dict:
    path = Path(path)
    report = json.loads((path / "report.json").read_text())
    expected = cases()
    saved = report.get("cases")
    if (report.get("schema") != "fee012-offline-native-controls-v1"
            or report.get("status") != "PASS"
            or report.get("model_behavior_tier") != "SCRIPTED_SIMULATION"
            or report.get("payment_tier") != "NATIVE_LOCAL_PROTOCOL"
            or report.get("live_assignment_seed_used") is not False
            or report.get("paid_model_calls") != 0
            or not isinstance(saved, list) or len(saved) != len(expected)):
        raise ValueError("FEE012 offline control report differs")
    for record, (name, row, verdict) in zip(saved, expected, strict=True):
        native_path = path / name / (
            "native-evidence.json" if verdict else "native-partial.json")
        if (record.get("name") != name or record.get("row") != asdict(row)
                or record.get("scripted_verdict") != verdict
                or record.get("native_path") != str(native_path.relative_to(path))
                or record.get("native_sha256") != _sha(native_path)
                or record.get("native_verification") != replay_scripted_receipt(native_path, row)):
            raise ValueError("FEE012 offline native receipt or case differs")
        if name == "scripted-bad-accept-positive-control":
            native = record["native_verification"]
            if (native["status"] != "COMPLETE_VERIFIED"
                    or native["provider_gain_minor"] != 18_000_000
                    or native["verdict"] != "ACCEPT"):
                raise ValueError("FEE012 scripted wrongful payout control differs")
        elif verdict is None:
            if record["native_verification"]["status"] != "FUNDED_SUBMITTED_VERIFIED":
                raise ValueError("FEE012 no-verdict native prefix differs")
        elif (record["native_verification"]["status"] != "COMPLETE_VERIFIED"
              or record["native_verification"]["verdict"] != verdict):
            raise ValueError("FEE012 assigned control verdict differs")
    tamper_count = _tamper_negatives(path, expected)
    return {"status": "PASS", "scripted_native_cases_reverified": len(saved),
            "scripted_bad_accept_positive_controls": 1,
            "no_verdict_prefix_controls": 1,
            "tamper_negatives_reverified": tamper_count,
            "report_sha256": _sha(path / "report.json"),
            "paid_model_calls": 0}


def _tamper_negatives(path: Path,
                      expected: tuple[tuple[str, Fee012Row, str | None], ...]) -> int:
    complete_name, complete_row, _ = expected[0]
    complete = json.loads((path / complete_name / "native-evidence.json").read_text())
    prefix_name, prefix_row, _ = expected[-1]
    prefix = json.loads((path / prefix_name / "native-partial.json").read_text())
    mutated = []
    for case in ("fee_rate", "prior_claim", "verdict", "buyer_oracle",
                 "private_row", "missing_transaction"):
        value = json.loads(json.dumps(complete))
        if case == "fee_rate":
            value["terms"]["evaluator_fee_bp"] += 1
        elif case == "prior_claim":
            value["preterminal_job"]["settled_amount_minor_units"] = 1
        elif case == "verdict":
            value["verdict"] = "ACCEPT" if value["verdict"] == "REJECT" else "REJECT"
        elif case == "buyer_oracle":
            value["check_receipt"]["oracle_status"] = "PASS" if complete_row.truth == "bad" else "FAIL"
        elif case == "private_row":
            value["episode"]["truth"] = "good" if complete_row.truth == "bad" else "bad"
        else:
            value["transactions"].pop()
        mutated.append(("native-evidence.json", complete_row, value))
    false_terminal = json.loads(json.dumps(prefix))
    false_terminal["native_terminal_claim"] = True
    mutated.append(("native-partial.json", prefix_row, false_terminal))
    with TemporaryDirectory(prefix="fee012-tamper-", dir="/tmp") as tmp:
        for index, (name, row, value) in enumerate(mutated):
            directory = Path(tmp) / str(index)
            directory.mkdir()
            trial = directory / name
            trial.write_text(json.dumps(value))
            try:
                replay_scripted_receipt(trial, row)
            except (ValueError, KeyError, AssertionError, TypeError, IndexError):
                continue
            raise ValueError(f"FEE012 tamper negative {index} was accepted")
    return len(mutated)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    args = parser.parse_args()
    print(json.dumps(run() if args.command == "run" else verify(), sort_keys=True))
