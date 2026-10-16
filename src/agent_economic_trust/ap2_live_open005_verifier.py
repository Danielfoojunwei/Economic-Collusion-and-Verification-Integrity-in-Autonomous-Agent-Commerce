"""AP2-scoped compatibility verifier for OPEN005-format native evidence."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .ap2_live_native_verifier import (
    verify_funded_evidence as verify_open004_funded,
    verify_native_evidence as verify_open004_terminal,
)


SCHEMA = "open005-native-erc8183-amendment-v1"
AMENDMENT = {
    "version": "OPEN005",
    "source_version": "OPEN004_NATIVE_COMPATIBLE",
    "preflight_before_official_terminal": True,
    "fixed_stress_term_without_provider_finalize": True,
}


def _load(path_or_dict: Path | str | Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    checks: list[str] = []
    if isinstance(path_or_dict, Mapping):
        evidence = deepcopy(dict(path_or_dict))
    else:
        path = Path(path_or_dict)
        directory = path.is_dir()
        path = path / "native-evidence.json" if directory else path
        raw = path.read_bytes().rstrip(b"\n")
        checksum = path.with_suffix(".sha256")
        if directory or checksum.exists():
            expected = f"{sha256(raw).hexdigest()}  {path.name}"
            if checksum.read_text(encoding="utf-8").strip() != expected:
                raise ValueError("OPEN005 native evidence file digest differs")
            checks.append("OPEN005 evidence file checksum")
        evidence = json.loads(raw)
    if evidence.get("schema") != SCHEMA:
        raise ValueError("OPEN005 native evidence schema differs")
    if evidence.get("amendment") != AMENDMENT:
        raise ValueError("OPEN005 native amendment metadata differs")
    evidence["schema"] = "open004-native-erc8183-v1"
    evidence.pop("amendment", None)
    return evidence, checks


def _verify(path_or_dict: Path | str | Mapping[str, Any], *, terminal: bool,
            source_root: Path | str | None) -> dict[str, Any]:
    try:
        evidence, checks = _load(path_or_dict)
        verifier = verify_open004_terminal if terminal else verify_open004_funded
        report = verifier(evidence, source_root=source_root)
        if not report["ok"]:
            return report
        return {**report, "experiment_version": "OPEN005",
                "amendment_metadata_verified": True,
                "preflight_execution_provenance_verified": False,
                "amendment_claim_scope": (
                    "HEADER_METADATA_AND_OPEN004_COMPATIBLE_NATIVE_LEDGER_ONLY"),
                "amendment_evidence_limit": (
                    "A compatible OPEN004 evidence record can be relabeled with the OPEN005 "
                    "header; saved receipts do not prove that preflight code executed before "
                    "the official terminal transaction."),
                "checks": checks + list(report.get("checks", []))}
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        return {"ok": False, "status": "FAIL", "errors": [str(error)],
                "checks": [], "experiment_version": "OPEN005",
                "amendment_metadata_verified": False,
                "preflight_execution_provenance_verified": False}


def verify_native_evidence(path_or_dict: Path | str | Mapping[str, Any], *,
                           source_root: Path | str | None = None) -> dict[str, Any]:
    return _verify(path_or_dict, terminal=True, source_root=source_root)


def verify_funded_evidence(path_or_dict: Path | str | Mapping[str, Any], *,
                           source_root: Path | str | None = None) -> dict[str, Any]:
    return _verify(path_or_dict, terminal=False, source_root=source_root)


def verify_ap2_native_evidence(path: Path) -> dict[str, Any]:
    report = verify_native_evidence(path)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return report


def verify_ap2_funded_evidence(path: Path) -> dict[str, Any]:
    report = verify_funded_evidence(path)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return report

