"""Offline-only completion export for the stopped W10 good-world pilot.

The original Inspect log and STOPPED record are immutable source evidence. The
new output is explicitly a post-run derived export using the corrected
exporter; it is not a second model run or a new payment transaction.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from inspect_ai.log import read_eval_log

from .evidence import verify_evidence
from .remote_budget import BudgetLedger
from .remote_pricing import CATALOG_URL, MODEL_ID, _catalog_data, estimate_usage, pricing_snapshot
from .w10_remote import FROZEN_ARTIFACT, MAX_CALLS_PER_WORLD, pilot_case
from .w10_reporting import export_protected_log, inspect_protected_log


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "artifacts/gates/W10_PILOT/real-good-001"
DEST_DIR = ROOT / "artifacts/gates/W10_PILOT/real-good-001-derived-complete"
LEDGER_PATH = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
PROVENANCE_NAME = "recovery_provenance.json"
ORIGINAL_RUN_ID = "w10-protected-real-good-001-good"
ORIGINAL_NATIVE_SHA = "139337135e981a39d47d7a42f154d0ae3f800c7be455bca4080416e9a742de77"
ORIGINAL_STOPPED_SHA = "7d773abe497165e259327fab18ee78aefbbcdf737af4cab012447378128950d4"
RESERVE_HASH = "f62d76a6822e41f3c1d3f7b5b4979d63f5bb0cb87b1069be94cc4805bfe2f348"
SETTLE_HASH = "e50a134de23df61293597d926075fb5aa4040fbeac570412425358e9d71bc23b"
CATALOG_MODEL_SHA = "71e95fa7cf157390232d6e13a44bf61ea6b9b6a7961ced6c8f37a684b51b499a"
NATIVE_MODEL = f"openrouter/{MODEL_ID}"
COUNT_KEYS = (
    "input_tokens", "output_tokens", "total_tokens", "input_tokens_cache_write",
    "input_tokens_cache_read", "reasoning_tokens",
)
RUNTIME_SOURCE_HASHES = {
    "protected_receipts.py": "f8d80d62e5f467208b6484c33c04853bbdeb8431af30d3a3462a3e57466c6e7c",
    "w10_remote.py": "5fa754009cd513340274b76e9b7246815e4cf2e1481304145a0e2f84ee77c954",
    "w10_reporting.py": "696e9444c2b8dfdf008405a3d3369e9b61979e612fe74883f8da00bf62395440",
    "remote.py": "f96c57fcd8094dbbd228c69dbcc1c87c6a0476edfb2c8a20cce2afb9cb4e6929",
    "remote_budget.py": "51b0af2d650865d0c91e9d1c2afd02779242b1506b69d36ecfcd76f540e39b80",
    "remote_pricing.py": "3035172c0891c9ac0a96bdaacb10c39de50b1383dc08e8abd84524c8d09755d7",
    "evidence.py": "6b1d516cb2142abcfda6728216edde7e464eb439e915d5a482e24fb9932c8f1f",
}


class RecoveryError(ValueError):
    """Saved inputs do not justify a complete derived export."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _usage_dict(value: Any) -> dict[str, Any]:
    if value is None:
        raise RecoveryError("native Inspect model usage is missing")
    usage = value.model_dump()
    for key in COUNT_KEYS:
        count = usage.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RecoveryError(f"native {key} usage is missing or invalid")
    return usage


def _source_evidence(source_dir: Path) -> tuple[dict[str, Any], Any, Any, int]:
    native = source_dir / "inspect.eval"
    stopped_path = source_dir / "STOPPED.json"
    if _sha(native) != ORIGINAL_NATIVE_SHA or _sha(stopped_path) != ORIGINAL_STOPPED_SHA:
        raise RecoveryError("original W10 native log or STOPPED record hash differs")
    stopped = json.loads(stopped_path.read_text(encoding="utf-8"))
    if stopped != {
        "budget_state": "SETTLED", "complete_outcome_exported": False,
        "error_type": "ProtectedEvidenceError",
        "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
        "native_log_sha256": ORIGINAL_NATIVE_SHA,
        "payment_tier": "NO_PAYMENT", "run_id": ORIGINAL_RUN_ID,
        "status": "PARTIAL", "world": "good",
    }:
        raise RecoveryError("original STOPPED record has unexpected state")
    log = read_eval_log(str(native), resolve_attachments=True)
    if log.status != "success" or log.eval.model != NATIVE_MODEL or len(log.samples or []) != 1:
        raise RecoveryError("original native log is not a successful single sample")
    sample = log.samples[0]
    if sample.id != "delivery-001" or sample.error or sample.limit:
        raise RecoveryError("original native sample is incomplete")
    sample_usage = _usage_dict((sample.model_usage or {}).get(NATIVE_MODEL))
    if sample_usage != _usage_dict((log.stats.model_usage or {}).get(NATIVE_MODEL)):
        raise RecoveryError("native sample and evaluation usage disagree")
    model_events = [event for event in sample.events if event.event == "model"]
    if len(model_events) != MAX_CALLS_PER_WORLD:
        raise RecoveryError("native model call count differs from bounded pilot")
    event_usage = []
    for event in model_events:
        if event.model != NATIVE_MODEL or event.output is None:
            raise RecoveryError("native model event has wrong model or no output")
        event_usage.append(_usage_dict(event.output.usage))
    if any(sum(row[key] for row in event_usage) != sample_usage[key] for key in COUNT_KEYS):
        raise RecoveryError("native per-call and sample usage disagree")
    # Inspect's role, tool, private-oracle, and frozen-artifact checks are the
    # corrected exporter's prerequisite, tested before any output is created.
    inspection = inspect_protected_log(log, pilot_case("good"), FROZEN_ARTIFACT)
    return stopped, log, inspection, len(model_events)


def _ledger_evidence(ledger_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = BudgetLedger(ledger_path).snapshot()  # validates chain and anchor
    run = snapshot["runs"].get(ORIGINAL_RUN_ID)
    if run is None or run.get("status") != "SETTLED":
        raise RecoveryError("original W10 ledger run is not settled")
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    if len(rows) <= 6:
        raise RecoveryError("original W10 reserve and settlement entries are missing")
    reserve, settle = rows[5], rows[6]
    if (
        reserve.get("seq") != 5 or reserve.get("kind") != "reserve"
        or reserve.get("hash") != RESERVE_HASH
        or reserve.get("payload", {}).get("run_id") != ORIGINAL_RUN_ID
        or Decimal(reserve["payload"]["amount_usd"]) != Decimal("3.19488")
        or settle.get("seq") != 6 or settle.get("kind") != "settle"
        or settle.get("hash") != SETTLE_HASH
        or settle.get("payload", {}).get("run_id") != ORIGINAL_RUN_ID
        or Decimal(settle["payload"]["actual_usd"]) != Decimal("0.06689")
        or settle["payload"].get("evidence_ref") != f"sha256:{ORIGINAL_NATIVE_SHA}"
        or run.get("evidence_ref") != f"sha256:{ORIGINAL_NATIVE_SHA}"
        or Decimal(run["actual_usd"]) != Decimal("0.06689")
    ):
        raise RecoveryError("original W10 reserve or settlement differs from pinned record")
    return snapshot, reserve, settle


def _pricing_evidence(catalog: Mapping[str, Any], usage: Any, calls: int) -> tuple[dict[str, Any], dict[str, Any]]:
    models = catalog.get("data")
    if not isinstance(models, list):
        raise RecoveryError("public model catalog data is absent")
    matches = [model for model in models if isinstance(model, Mapping) and model.get("id") == MODEL_ID]
    if len(matches) != 1:
        raise RecoveryError("public model catalog lacks one exact approved model")
    model_record = dict(matches[0])
    pricing = pricing_snapshot(MODEL_ID, catalog={"data": [model_record]})
    if pricing["catalog_model_sha256"] != CATALOG_MODEL_SHA:
        raise RecoveryError("post-run public model catalog differs from the prior pinned record")
    if estimate_usage(pricing, usage, calls=calls) != Decimal("0.066890"):
        raise RecoveryError("native usage estimate differs from settled ledger amount")
    return model_record, pricing


def _runtime_sources() -> dict[str, str]:
    package = Path(__file__).resolve().parent
    current = {name: _sha(package / name) for name in RUNTIME_SOURCE_HASHES}
    for name, pinned in RUNTIME_SOURCE_HASHES.items():
        if name != "w10_reporting.py" and current[name] != pinned:
            raise RecoveryError(f"{name} differs from pinned original runtime source")
    if current["w10_reporting.py"] == RUNTIME_SOURCE_HASHES["w10_reporting.py"]:
        raise RecoveryError("corrected post-run exporter is not installed")
    return current


def _sidecar(
    source_dir: Path, destination: Path, reserve: dict[str, Any], settle: dict[str, Any],
    model_record: dict[str, Any], pricing: dict[str, Any], usage: dict[str, Any],
    inspection: dict[str, Any], current_sources: dict[str, str],
) -> dict[str, Any]:
    record = {
        "schema_version": "w10-good-derived-recovery-v1",
        "classification": "POST_RUN_DERIVED_EXPORT_OF_ORIGINAL_REAL_MODEL_TRACE",
        "original_run_id": ORIGINAL_RUN_ID,
        "derived_run_id": json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))["run_id"],
        "original_source_sha256": {
            "inspect.eval": _sha(source_dir / "inspect.eval"),
            "STOPPED.json": _sha(source_dir / "STOPPED.json"),
        },
        "derived_artifacts_sha256": {
            name: _sha(destination / name)
            for name in ("inspect.eval", "run_manifest.json", "events.jsonl", "episode_outcomes.csv")
        },
        "runtime_source_sha256_at_original_execution": RUNTIME_SOURCE_HASHES,
        "source_sha256_at_derived_export": current_sources,
        "source_provenance": "Original runtime hashes supplied from the first execution record; all unchanged source files rechecked against current workspace. w10_reporting.py was corrected after the original run.",
        "exporter_caveat": "The native Inspect log and budget settlement belong to the original run; events, outcome, and manifest were exported later using corrected w10_reporting.py. No provider calls or payment execution occurred during recovery.",
        "catalog": {
            "source_url": CATALOG_URL,
            "timing_caveat": "Fetched after the W10 run; exact W10 preflight catalog bytes were not saved. The model record digest matches the earlier W05 pinned public catalog record.",
            "model_record": model_record,
            "model_record_sha256": pricing["catalog_model_sha256"],
            "conservative_pricing_snapshot": pricing,
        },
        "native_usage": usage,
        "native_inspection": inspection,
        "ledger": {
            "reserve_event": reserve,
            "settle_event": settle,
            "settled_usd": settle["payload"]["actual_usd"],
            "cost_basis": "Native usage at conservative public catalog rates equals the settled ledger estimate; this is not a provider invoice.",
        },
        "unavailable_observations": {
            "account_usage_delta_usd": None,
            "max_input_bytes_seen": None,
            "reason": "Neither value was persisted when the original exporter stopped. Null values in the derived manifest are unknown, not observed zero.",
        },
        "limits": "One fixed good-world prerequisite, no randomized treatment, no payment, and no economic collusion inference.",
    }
    record["record_sha256"] = sha256(_canonical(record)).hexdigest()
    return record


def verify_recovery(
    destination: Path = DEST_DIR, *, source_dir: Path = SOURCE_DIR,
    ledger_path: Path = LEDGER_PATH,
) -> dict[str, Any]:
    """Check copied native and complete derivative against original sources offline."""
    destination, source_dir, ledger_path = Path(destination), Path(source_dir), Path(ledger_path)
    record = json.loads((destination / PROVENANCE_NAME).read_text(encoding="utf-8"))
    if record.get("schema_version") != "w10-good-derived-recovery-v1":
        raise RecoveryError("derived provenance schema is invalid")
    digest = record.get("record_sha256")
    if digest != sha256(_canonical({key: val for key, val in record.items() if key != "record_sha256"})).hexdigest():
        raise RecoveryError("derived provenance record hash differs")
    _, _, inspection, calls = _source_evidence(source_dir)
    _, reserve, settle = _ledger_evidence(ledger_path)
    if record.get("original_source_sha256") != {
        "inspect.eval": _sha(source_dir / "inspect.eval"),
        "STOPPED.json": _sha(source_dir / "STOPPED.json"),
    }:
        raise RecoveryError("derived provenance does not link original source hashes")
    if _sha(destination / "inspect.eval") != ORIGINAL_NATIVE_SHA:
        raise RecoveryError("derived native copy differs from original")
    if record.get("derived_artifacts_sha256") != {
        name: _sha(destination / name)
        for name in ("inspect.eval", "run_manifest.json", "events.jsonl", "episode_outcomes.csv")
    }:
        raise RecoveryError("derived v1 artifact hashes differ from provenance")
    if record.get("runtime_source_sha256_at_original_execution") != RUNTIME_SOURCE_HASHES:
        raise RecoveryError("original runtime source pin differs")
    if record.get("ledger", {}).get("reserve_event") != reserve or record.get("ledger", {}).get("settle_event") != settle:
        raise RecoveryError("provenance ledger records differ")
    model_record = record.get("catalog", {}).get("model_record")
    pricing = pricing_snapshot(MODEL_ID, catalog={"data": [model_record]})
    saved_pricing = record["catalog"]["conservative_pricing_snapshot"]
    pricing["fetched_utc"] = saved_pricing.get("fetched_utc")
    if pricing != saved_pricing or record["catalog"]["model_record_sha256"] != CATALOG_MODEL_SHA:
        raise RecoveryError("derived catalog snapshot is not the pinned model record")
    log = read_eval_log(str(destination / "inspect.eval"), resolve_attachments=True)
    usage = _usage_dict(log.samples[0].model_usage[NATIVE_MODEL])
    if usage != record.get("native_usage") or estimate_usage(pricing, usage, calls=calls) != Decimal("0.066890"):
        raise RecoveryError("native usage or conservative cost differs")
    manifest = json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "COMPLETE"
        or manifest.get("run_id") != record.get("derived_run_id")
        or manifest.get("model_behavior_tier") != "REAL_LLM_REMOTE_APPROVED"
        or manifest.get("payment_tier") != "NO_PAYMENT"
        or manifest.get("post_run_derivation") is not True
        or manifest.get("account_usage_delta_usd") is not None
        or manifest.get("max_input_bytes_seen") is not None
        or Decimal(manifest.get("estimated_model_cost_usd", "-1")) != Decimal("0.06689")
        or Decimal(manifest.get("worst_case_reserved_usd", "-1")) != Decimal("3.19488")
        or manifest.get("budget_ledger_last_hash") != reserve["hash"]
        or manifest.get("provider_calls") != calls
        or manifest.get("pricing_snapshot") != saved_pricing
        or manifest.get("model_usage") != usage
        or manifest.get("native_inspection") != inspection
        or record.get("native_inspection") != inspection
        or manifest.get("code_sha256") != record.get("source_sha256_at_derived_export")
    ):
        raise RecoveryError("derived manifest has incorrect provenance or unknown-value fields")
    if not verify_evidence(destination):
        raise RecoveryError("derived v1 event and outcome evidence failed verification")
    return {"verified": True, "record_sha256": digest, "native_sha256": ORIGINAL_NATIVE_SHA,
            "settled_estimate_usd": "0.06689"}


def recover_good(
    destination: Path = DEST_DIR, *, source_dir: Path = SOURCE_DIR,
    ledger_path: Path = LEDGER_PATH, catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new derived directory from saved evidence; no inference calls."""
    destination, source_dir, ledger_path = Path(destination), Path(source_dir), Path(ledger_path)
    if destination.exists():
        raise FileExistsError("derived output already exists; original evidence is never overwritten")
    _, log, inspection, calls = _source_evidence(source_dir)
    _, reserve, settle = _ledger_evidence(ledger_path)
    usage = _usage_dict(log.samples[0].model_usage[NATIVE_MODEL])
    model_record, pricing = _pricing_evidence(
        _catalog_data() if catalog is None else catalog, usage, calls,
    )
    current_sources = _runtime_sources()
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(destination, 0o700)
    native_copy = destination / "inspect.eval"
    with (source_dir / "inspect.eval").open("rb") as src, native_copy.open("xb") as out:
        shutil.copyfileobj(src, out)
    os.chmod(native_copy, 0o600)
    if _sha(native_copy) != ORIGINAL_NATIVE_SHA:
        raise RecoveryError("derived native copy differs from original")
    export_protected_log(
        log, destination, case=pilot_case("good"), world="good",
        frozen_artifact=FROZEN_ARTIFACT, pricing=pricing,
        usage=log.samples[0].model_usage[NATIVE_MODEL],
        estimated_cost_usd=Decimal(settle["payload"]["actual_usd"]),
        account_usage_delta_usd=None,
        reservation_usd=Decimal(reserve["payload"]["amount_usd"]),
        reservation_event={"last_hash": reserve["hash"]},
        provider_calls=calls, max_input_bytes_seen=None,
        derived_from_partial=True,
    )
    record = _sidecar(
        source_dir, destination, reserve, settle, model_record, pricing,
        usage, inspection, current_sources,
    )
    payload = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(name)
        if secret and len(secret) >= 8 and secret.encode("utf-8") in payload:
            raise RecoveryError("credential value appeared in derived provenance")
    with (destination / PROVENANCE_NAME).open("xb") as file:
        file.write(payload)
    os.chmod(destination / PROVENANCE_NAME, 0o600)
    return verify_recovery(destination, source_dir=source_dir, ledger_path=ledger_path)
