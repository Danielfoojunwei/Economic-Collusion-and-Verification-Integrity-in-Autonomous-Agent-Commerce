"""Isolated chain identity and unchanged MPP010 native helper overlay.

Only chain ports and the independently saved first transfer marker differ from
the pinned MPP010 JS helper. The protocol, signer, and receipt-verifier modules
are byte-identical copies; this module itself does no model or chain call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from inspect_ai.tool import ToolError

from .free_mpp_native_orbit004_lifecycle import ARMS, assigned_row
from .mpp010_native_service import NativeMeetingService


ROOT = Path(__file__).resolve().parents[2]
RPC_URL = "http://127.0.0.1:19997"
HTTP_URL = "http://127.0.0.1:19989"
CONTAINER = "free-mpp-live-orbit004-localnet"
IMAGE = ("ghcr.io/tempoxyz/tempo-localnet@sha256:"
         "86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b")
HELPERS = (
    "mpp010-chain-identity.mjs", "mpp010-meeting-service.mjs",
    "mpp010-verify-meeting-service.mjs", "mpp010-meeting-local.mjs",
    "mpp010-verify-meeting-evidence.mjs", "package-lock.json",
)


def sha(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def validate_marker(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("independent isolated chain marker absent")
    marker = json.loads(path.read_bytes())
    source = ROOT / "protocols/mpp/free-orbit004-chain-marker.mjs"
    if (marker.get("rpc_url") != RPC_URL or marker.get("container") != CONTAINER
            or marker.get("image") != IMAGE or marker.get("chain_id") != 1337
            or marker.get("test_only") is not True or marker.get("marker_amount_atomic") != "1014"
            or marker.get("source_sha256") != sha(source)):
        raise ValueError("isolated chain marker source, asset, or network differs")
    for name in ("genesis_hash", "marker_transaction_hash", "marker_block_hash"):
        if re.fullmatch(r"0x[0-9a-f]{64}", marker.get(name, "")) is None:
            raise ValueError("isolated chain marker hash invalid")
    if int(marker.get("marker_block_number", 0)) <= 0:
        raise ValueError("isolated chain marker block invalid")
    return marker


def adapted_chain_identity(marker: dict) -> bytes:
    source = (ROOT / "protocols/mpp/mpp010-chain-identity.mjs").read_text()
    replacements = {
        "http://127.0.0.1:19767": RPC_URL,
        "http://127.0.0.1:19759": HTTP_URL,
        "0xcbfbdd6d88281a0c727e32ab709a2ac188742e188c05db6e514e5c0f0685f977":
            marker["marker_transaction_hash"],
        "marker_block_number: '742'":
            "marker_block_number: '" + marker["marker_block_number"] + "'",
        "0x2da511a24c05b58a2a22210c4931c92c182b14e7896585243fa908039a3b0e1e":
            marker["marker_block_hash"],
        "marker_amount_atomic: '1010'": "marker_amount_atomic: '1014'",
    }
    for original, replacement in replacements.items():
        if source.count(original) != 1:
            raise ValueError("pinned MPP010 chain identity source changed")
        source = source.replace(original, replacement)
    return source.encode()


def prepare_overlay(output: Path, marker_path: Path) -> dict:
    """Create one isolated copy; never modify the archived MPP010 helpers."""
    marker = validate_marker(marker_path)
    output = Path(output)
    overlay = output / "native-overlay/protocols/mpp"
    overlay.mkdir(parents=True, exist_ok=False)
    original = ROOT / "protocols/mpp"
    changes = {}
    for name in HELPERS:
        before = (original / name).read_bytes()
        after = adapted_chain_identity(marker) if name == HELPERS[0] else before
        (overlay / name).write_bytes(after)
        changes[name] = {"original_sha256": sha256(before).hexdigest(),
                         "exploratory_sha256": sha256(after).hexdigest(),
                         "changed": after != before}
    (overlay / "node_modules").symlink_to(original / "node_modules", target_is_directory=True)
    marker_copy = output / "chain-marker.json"
    marker_copy.write_bytes(Path(marker_path).read_bytes())
    report = {"chain_marker": marker, "source_marker_sha256": sha(marker_copy),
              "original_helper_root": str(original),
              "exploratory_helper_root": str(overlay), "helper_hashes": changes,
              "only_change": "isolated chain RPC/HTTP ports and first transfer marker"}
    (output / "protocol-overlay.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if [name for name, row in changes.items() if row["changed"]] != [HELPERS[0]]:
        raise ValueError("exploratory helper overlay changed more than chain identity")
    return report


def verify_overlay(output: Path) -> dict:
    output = Path(output)
    report = json.loads((output / "protocol-overlay.json").read_bytes())
    marker_copy = output / "chain-marker.json"
    marker = validate_marker(marker_copy)
    if report.get("chain_marker") != marker or report.get("source_marker_sha256") != sha(marker_copy):
        raise ValueError("exploratory chain marker or overlay report changed")
    overlay = output / "native-overlay/protocols/mpp"
    original = ROOT / "protocols/mpp"
    changes = report.get("helper_hashes")
    for name in HELPERS:
        before = (original / name).read_bytes()
        expected = adapted_chain_identity(marker) if name == HELPERS[0] else before
        if (not isinstance(changes, dict) or changes.get(name) != {
                "original_sha256": sha256(before).hexdigest(),
                "exploratory_sha256": sha256(expected).hexdigest(),
                "changed": expected != before} or (overlay / name).read_bytes() != expected):
            raise ValueError("exploratory helper source or pins changed")
    modules = overlay / "node_modules"
    if not modules.is_symlink() or modules.resolve() != (original / "node_modules").resolve():
        raise ValueError("MPP SDK dependency path changed")
    if [name for name, item in changes.items() if item["changed"]] != [HELPERS[0]]:
        raise ValueError("only the isolated chain identity may change")
    return report


@dataclass(frozen=True)
class IsolatedOrbitNativeService(NativeMeetingService):
    """Pinned MPP signer/verifier with a separate fresh-chain overlay."""

    rpc_url: str = RPC_URL
    http_url: str = HTTP_URL
    overlay_dir: Path = Path(".")

    def __post_init__(self) -> None:
        if (self.rpc_url != RPC_URL or self.http_url != HTTP_URL
                or not self.evidence_dir.is_absolute() or not self.overlay_dir.is_absolute()
                or self.row not in tuple(assigned_row(arm) for arm in ARMS)):
            raise ValueError("free native ORBIT service row or isolated chain differs")

    async def _command(self, *arguments):
        originals = ROOT / "protocols/mpp"
        mapped = []
        for item in arguments:
            path = Path(item)
            if path.parent == originals and path.name in HELPERS:
                path = self.overlay_dir / path.name
            mapped.append(str(path))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "MPP_TEMPO_RPC_URL": self.rpc_url,
               "MPP_SERVICE_HTTP_URL": self.http_url, "MPP_HTTP_URL": self.http_url}
        process = await asyncio.create_subprocess_exec("node", *mapped,
            cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise ToolError("exploratory native operation timed out; preserve possible debit") from None
        if process.returncode or len(stdout) > 65536 or len(stderr) > 65536:
            raise ToolError("exploratory native helper or receipt verifier failed")
        result = json.loads(stdout)
        if result.get("status") != "PASS":
            raise ToolError("exploratory native helper did not certify success")
        return result
