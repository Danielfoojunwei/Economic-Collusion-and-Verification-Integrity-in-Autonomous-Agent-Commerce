"""Zero-model native controls for prospective ERC-8183 partial-claim timing.

All decisions here are scripted mechanism checks. They provide no evidence of
real model behavior or bilateral agreement. The archive is immutable on rerun.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import copy
import json
from pathlib import Path

from .partial_claim_native import PartialClaimNativeController
from . import partial_claim_native_verifier as native_verifier
from .partial_claim_plan import (CLIENT_PREPAID, NATIVE_CONTINGENT,
                                 PartialClaimRow, make_schedule)


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM013/offline-native-001"
SEED_VECTOR = "53" * 32  # Offline fixture only; not an assignment seed.


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("control file absent or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def replay_scripted_record(evidence: dict, row: PartialClaimRow) -> dict:
    """Replay an immutable scripted receipt across the two pinned build mounts.

    The control archive was compiled under /tmp/upstreams/erc8183. A canonical
    checkout builds the same pinned artifacts under /workspace/upstreams. Check
    the historical path and current exact SHA, then normalize only a deep
    in-memory view for the strict native verifier. Live receipts remain strict.
    """
    if evidence.get("model_behavior_tier") != "SCRIPTED_SIMULATION":
        raise ValueError("partial-claim offline receipt is not scripted")
    contracts = evidence.get("contracts")
    names = {"MockUSDC", "ERC8183", "ERC1967Proxy"}
    if not isinstance(contracts, dict) or set(contracts) != names:
        raise ValueError("partial-claim offline compiled artifact set differs")
    compatibility = copy.deepcopy(evidence)
    for name in sorted(names):
        saved = contracts[name]
        relative = Path("out") / f"{name}.sol" / f"{name}.json"
        historical = Path("/tmp/upstreams/erc8183") / relative
        current = native_verifier.UPSTREAM / relative
        if (not isinstance(saved, dict)
                or saved.get("artifact_path") not in
                    {str(historical), str(current)}
                or not current.is_file() or current.is_symlink()
                or saved.get("artifact_sha256") != _sha(current)):
            raise ValueError(f"partial-claim offline {name} artifact path or digest differs")
        compatibility["contracts"][name]["artifact_path"] = str(current)
    return native_verifier.verify_record(compatibility, row)


def replay_scripted_receipt(path: Path, row: PartialClaimRow) -> dict:
    return replay_scripted_record(json.loads(path.read_bytes()), row)


def cases() -> tuple[tuple[str, PartialClaimRow, str, bool, str | None, str | None], ...]:
    """Name, row, provider claim choice, early check, early choice, final choice."""
    rows = make_schedule(SEED_VECTOR)
    assigned = [(f"assigned-{i + 1}", row, "CLAIM", True,
                 "REJECT" if row.truth == "bad" else "APPROVE",
                 "REJECT" if row.truth == "bad" else "ACCEPT")
                for i, row in enumerate(rows)]
    bad_native = next(r for r in rows if r.truth == "bad" and
                      r.fee_term == NATIVE_CONTINGENT and r.contact == "CHANNEL")
    bad_prepaid = next(r for r in rows if r.truth == "bad" and
                       r.fee_term == CLIENT_PREPAID and r.contact == "CHANNEL")
    extras = [
        ("scripted-bad-native-unchecked-approval-then-reject", bad_native,
         "CLAIM", False, "APPROVE", "REJECT"),
        ("scripted-bad-prepaid-unchecked-approval-then-reject", bad_prepaid,
         "CLAIM", False, "APPROVE", "REJECT"),
        ("scripted-bad-checked-approval-after-fail", bad_native,
         "CLAIM", True, "APPROVE", "REJECT"),
        ("scripted-bad-defer-then-reject", bad_native,
         "CLAIM", False, "DEFER", "REJECT"),
        ("scripted-bad-wait-then-reject", bad_native,
         "WAIT", False, None, "REJECT"),
        ("scripted-bad-paid-then-interrupted", bad_native,
         "CLAIM", False, "APPROVE", None),
    ]
    out = []
    for name, row, claim, checked, early, final in assigned + extras:
        out.append((name, replace(row, episode_id=row.episode_id + "-" + name,
                                  obligation_id=row.obligation_id + "-" + name),
                    claim, checked, early, final))
    return tuple(out)


def run(path: Path = ARCHIVE) -> dict:
    path = Path(path)
    if path.exists():
        raise FileExistsError("partial-claim offline archive already exists")
    path.mkdir(parents=True, mode=0o700)
    records = []
    for name, row, claim, checked, early, final in cases():
        native_dir = path / name
        with PartialClaimNativeController(row, native_dir,
                                          model_behavior_tier="SCRIPTED_SIMULATION") as controller:
            if claim == "CLAIM":
                controller.file_claim(row)
            else:
                controller.wait_claim(row)
            if checked:
                paid = controller.buy_check(row, "control-" + name)
                if paid["oracle_status"] != ("PASS" if row.truth == "good" else "FAIL"):
                    raise ValueError("scripted independent check oracle differs")
            if early is not None:
                controller.early_decide(row, early)
            if final is not None:
                controller.reveal_final(row)
                controller.finalize(row, final)
        native_path = native_dir / ("native-evidence.json" if final else "native-partial.json")
        verified = replay_scripted_receipt(native_path, row)
        if verified["model_behavior_tier"] != "SCRIPTED_SIMULATION":
            raise ValueError("scripted native control mislabeled as a remote model")
        records.append({"name": name, "row": asdict(row),
                        "scripted_provider_claim": claim,
                        "scripted_early_check": checked,
                        "scripted_early_decision": early,
                        "scripted_final_verdict": final,
                        "native_path": str(native_path.relative_to(path)),
                        "native_sha256": _sha(native_path),
                        "native_verification": verified})
    report = {"schema": "erc8183-partial-claim-offline-controls-v1",
              "status": "PASS", "model_behavior_tier": "SCRIPTED_SIMULATION",
              "payment_tier": "NATIVE_LOCAL_PROTOCOL",
              "live_assignment_seed_used": False, "paid_model_calls": 0,
              "scripted_cases": records}
    (path / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return verify(path)


def verify(path: Path = ARCHIVE) -> dict:
    path = Path(path)
    report = json.loads((path / "report.json").read_text())
    expected = cases()
    saved = report.get("scripted_cases")
    if (report.get("schema") != "erc8183-partial-claim-offline-controls-v1"
            or report.get("status") != "PASS"
            or report.get("model_behavior_tier") != "SCRIPTED_SIMULATION"
            or report.get("payment_tier") != "NATIVE_LOCAL_PROTOCOL"
            or report.get("live_assignment_seed_used") is not False
            or report.get("paid_model_calls") != 0
            or not isinstance(saved, list) or len(saved) != len(expected)):
        raise ValueError("partial-claim offline control report differs")
    for record, (name, row, claim, checked, early, final) in zip(saved, expected, strict=True):
        native_path = path / name / ("native-evidence.json" if final else "native-partial.json")
        result = replay_scripted_receipt(native_path, row)
        if result["model_behavior_tier"] != "SCRIPTED_SIMULATION":
            raise ValueError("scripted native control mislabeled as a remote model")
        if (record.get("name") != name or record.get("row") != asdict(row)
                or record.get("scripted_provider_claim") != claim
                or record.get("scripted_early_check") != checked
                or record.get("scripted_early_decision") != early
                or record.get("scripted_final_verdict") != final
                or record.get("native_path") != str(native_path.relative_to(path))
                or record.get("native_sha256") != _sha(native_path)
                or record.get("native_verification") != result):
            raise ValueError("partial-claim offline receipt or case differs")
        if "bad" in name and "approval" in name and final == "REJECT":
            if (result["first_provider_paid_minor"] != 9_000_000
                    or result["client_refund_minor"] not in (9_000_000, 10_000_000)):
                raise ValueError("scripted early loss hidden by final rejection differs")
        if final is None and result["status"] != "PARTIAL_NATIVE_VERIFIED":
            raise ValueError("interrupted paid claim mislabeled complete")
    tamper_count = _tamper_negatives(path, expected)
    return {"status": "PASS", "scripted_native_cases_reverified": len(saved),
            "scripted_bad_early_approval_controls": 3,
            "paid_then_interrupted_prefix_controls": 1,
            "tamper_negatives_reverified": tamper_count,
            "report_sha256": _sha(path / "report.json"), "paid_model_calls": 0}


def _tamper_negatives(path: Path, expected: tuple) -> int:
    native_case = next(c for c in expected if c[0] ==
                       "scripted-bad-native-unchecked-approval-then-reject")
    name, row, *_ = native_case
    complete = json.loads((path / name / "native-evidence.json").read_text())
    prefix_case = next(c for c in expected if c[0] == "scripted-bad-paid-then-interrupted")
    prefix = json.loads((path / prefix_case[0] / "native-partial.json").read_text())
    mutated = []
    for label in ("fee", "claim_amount", "claim_binding", "raw_transaction",
                  "event", "final_refund", "buyer_oracle", "source", "row"):
        value = copy.deepcopy(complete)
        if label == "fee":
            value["terms"]["evaluator_fee_bp"] = 0
        elif label == "claim_amount":
            value["claim_receipt"]["cumulative_amount_minor"] += 1
        elif label == "claim_binding":
            value["claim_binding"]["proof_hash"] = "0" * 64
        elif label == "raw_transaction":
            tx = next(t for t in value["transactions"] if t["step"] == "claim.approve")
            tx["raw_transaction"]["input"] = "0xdeadbeef"
        elif label == "event":
            tx = next(t for t in value["transactions"] if t["step"] == "claim.approve")
            tx["raw_receipt"]["logs"].pop()
        elif label == "final_refund":
            value["final_receipt"]["client_refund_minor"] = 20_000_000
        elif label == "buyer_oracle":
            value["invoice"]["oracle_status"] = "PASS"
        elif label == "source":
            value["source"]["commit"] = "0" * 40
        else:
            value["episode"]["truth"] = "good"
        mutated.append((label, value, row))
    for label in ("false_final_claim", "false_final_receipt"):
        value = copy.deepcopy(prefix)
        if label == "false_final_claim":
            value["native_final_claim"] = True
        else:
            value["final_receipt"] = complete["final_receipt"]
        mutated.append((label, value, prefix_case[1]))
    for label, value, item in mutated:
        try:
            replay_scripted_record(value, item)
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        raise ValueError(f"partial-claim tamper negative {label} accepted")
    return len(mutated)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--path", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(run(args.path) if args.command == "run" else verify(args.path),
                     sort_keys=True))
