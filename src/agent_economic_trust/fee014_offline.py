"""Reverify FEE012's eight official local controls for the FEE014 terms.

The protocol controller, service, fee terms, and protected buyer oracle are
unchanged. This immutable predecessor archive includes six assigned scripted
cells, one deliberately wrongful BAD ACCEPT, and one no-verdict prefix. Its
verifier replays seven tamper negatives. No remote model is used here.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .fee012_offline import ARCHIVE as PREDECESSOR_ARCHIVE
from .fee012_offline import verify as verify_predecessor


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "artifacts/prospective/ERC8183_FEE014/offline-native-001"


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE014 offline report or predecessor missing")
    return sha256(path.read_bytes()).hexdigest()


def expected() -> dict:
    predecessor = verify_predecessor(PREDECESSOR_ARCHIVE)
    if (predecessor["status"] != "PASS"
            or predecessor["scripted_native_cases_reverified"] != 8
            or predecessor["scripted_bad_accept_positive_controls"] != 1
            or predecessor["no_verdict_prefix_controls"] != 1
            or predecessor["tamper_negatives_reverified"] != 7
            or predecessor["paid_model_calls"] != 0):
        raise ValueError("FEE014 predecessor controls differ")
    return {"schema": "fee014-reused-offline-native-controls-v1",
            "status": "PASS", "paid_model_calls": 0,
            "model_behavior_tier": "SCRIPTED_SIMULATION",
            "source_study": "ERC8183_FEE012",
            "source_report_sha256": _sha(PREDECESSOR_ARCHIVE / "report.json"),
            "source_report_path": str((PREDECESSOR_ARCHIVE / "report.json").relative_to(ROOT)),
            "replay": predecessor,
            "not_live_collusion_evidence": True}


def run(path: Path = ARCHIVE) -> dict:
    path = Path(path)
    if path.exists():
        raise FileExistsError("FEE014 offline report already exists")
    result = expected()
    path.mkdir(parents=True, mode=0o700)
    (path / "report.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return verify(path)


def verify(path: Path = ARCHIVE) -> dict:
    saved = json.loads((Path(path) / "report.json").read_bytes())
    current = expected()
    if saved != current:
        raise ValueError("FEE014 reused native controls differ")
    return current
