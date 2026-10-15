"""Append-only repair record for redacted numeric fields in the first W05 run.

The original run manifest and native Inspect log are immutable inputs. This
module reads a public OpenRouter catalog record, requires its canonical digest
to match the digest saved at run time, and records only usage and pricing data.
It never sends an inference request or reads an API credential.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping

from inspect_ai.log import read_eval_log

from .remote_pricing import CATALOG_URL, MODEL_ID, _catalog_data, estimate_usage, pricing_snapshot


SUPPLEMENT_NAME = "usage_pricing_supplement.json"
NATIVE_MODEL = f"openrouter/{MODEL_ID}"
COUNT_KEYS = (
    "input_tokens", "output_tokens", "total_tokens", "input_tokens_cache_write",
    "input_tokens_cache_read", "reasoning_tokens",
)


class SupplementError(ValueError):
    """The source evidence cannot support a verified supplemental record."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _usage_dict(value: Any) -> dict[str, Any]:
    if value is None:
        raise SupplementError("native model usage is missing")
    usage = value.model_dump()
    for key in COUNT_KEYS:
        count = usage.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SupplementError(f"native {key} is missing or invalid")
    return usage


def _derive(
    evidence_dir: Path, catalog: Mapping[str, Any], *, created_utc: str,
    fetched_utc: str | None = None,
) -> dict[str, Any]:
    manifest_path = evidence_dir / "run_manifest.json"
    native_path = evidence_dir / "inspect.eval"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE" or manifest.get("model_behavior_tier") != "REAL_LLM_REMOTE_APPROVED":
        raise SupplementError("original manifest is not a complete real-model run")
    if manifest.get("payment_tier") != "MOCK_LOCAL" or manifest.get("task_ids") != ["reconcile-002"]:
        raise SupplementError("original manifest identifies a different pilot")
    native_hash = _file_hash(native_path)
    if native_hash != manifest.get("artifacts_sha256", {}).get("inspect.eval"):
        raise SupplementError("native Inspect log differs from original manifest hash")
    manifest_hash = _file_hash(manifest_path)

    models = catalog.get("data")
    if not isinstance(models, list):
        raise SupplementError("public catalog has no model list")
    matches = [item for item in models if isinstance(item, Mapping) and item.get("id") == MODEL_ID]
    if len(matches) != 1:
        raise SupplementError("public catalog lacks one exact approved model record")
    model_record = dict(matches[0])
    snapshot = pricing_snapshot(MODEL_ID, catalog={"data": [model_record]})
    original_snapshot = manifest.get("pricing_snapshot", {})
    if not isinstance(original_snapshot, Mapping) or snapshot["catalog_model_sha256"] != original_snapshot.get("catalog_model_sha256"):
        raise SupplementError("current catalog record differs from run-time pinned model digest")
    if original_snapshot.get("model_id") != MODEL_ID or original_snapshot.get("source_url") != CATALOG_URL:
        raise SupplementError("original manifest has an unexpected catalog source or model")
    for key in ("context_length", "pricing_tiers", "request_usd"):
        if original_snapshot.get(key) != snapshot[key]:
            raise SupplementError(f"catalog {key} differs from original manifest")
    if fetched_utc is not None:
        snapshot["fetched_utc"] = fetched_utc

    log = read_eval_log(str(native_path))
    if log.status != "success" or log.eval.model != NATIVE_MODEL or len(log.samples or []) != 1:
        raise SupplementError("native log does not contain one successful approved-model sample")
    sample = log.samples[0]
    if sample.id != "reconcile-002":
        raise SupplementError("native sample id differs from original manifest")
    sample_usage = _usage_dict((sample.model_usage or {}).get(NATIVE_MODEL))
    stats_usage = _usage_dict((log.stats.model_usage or {}).get(NATIVE_MODEL))
    if sample_usage != stats_usage:
        raise SupplementError("native sample and evaluation usage totals disagree")
    model_events = [event for event in sample.events if event.event == "model"]
    if not model_events or len(model_events) != manifest.get("provider_calls"):
        raise SupplementError("native model event count differs from original provider call count")
    event_usage = []
    for event in model_events:
        if event.model != NATIVE_MODEL or event.output is None:
            raise SupplementError("native event uses a different model or lacks output")
        event_usage.append(_usage_dict(event.output.usage))
    if any(sum(row[key] for row in event_usage) != sample_usage[key] for key in COUNT_KEYS):
        raise SupplementError("native per-call and sample usage totals disagree")
    estimated = estimate_usage(snapshot, sample_usage, calls=len(model_events))
    original_estimate = manifest.get("estimated_model_cost_usd")
    if Decimal(str(original_estimate)) != estimated:
        raise SupplementError("recomputed conservative cost differs from original estimate")

    record = {
        "schema_version": "w05-usage-pricing-supplement-v1",
        "created_utc": created_utc,
        "purpose": "Restore numeric usage and pinned public pricing redacted from the immutable W05 manifest.",
        "source_hashes": {"run_manifest.json": manifest_hash, "inspect.eval": native_hash},
        "original_run_id": manifest["run_id"],
        "original_manifest_claims": {
            "provider_calls": manifest["provider_calls"],
            "estimated_model_cost_usd": original_estimate,
            "account_usage_delta_usd": manifest["account_usage_delta_usd"],
            "worst_case_reserved_usd": manifest["worst_case_reserved_usd"],
            "budget_ledger_last_hash": manifest["budget_ledger_last_hash"],
        },
        "catalog": {
            "model_record": model_record,
            "model_record_sha256": snapshot["catalog_model_sha256"],
            "conservative_pricing_snapshot": snapshot,
        },
        "native_usage": {
            "source": "inspect.eval:sample[reconcile-002].model_usage[openrouter/openai/gpt-5.6-sol]",
            "model": NATIVE_MODEL,
            "provider_calls": len(model_events),
            "sample_usage": sample_usage,
            "event_usage": event_usage,
        },
        "cost": {
            "estimated_usd": format(estimated, "f"),
            "basis": "conservative catalog rates times native Inspect usage; not a provider invoice",
            "account_usage_delta_usd": manifest["account_usage_delta_usd"],
            "account_delta_note": "Observed account endpoint delta at probe time; zero does not establish free usage or supersede the conservative estimate.",
        },
    }
    record["record_sha256"] = _digest(record)
    return record


def build_supplement(evidence_dir: Path, *, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a record only if today's public model record matches the run pin."""
    return _derive(Path(evidence_dir), _catalog_data() if catalog is None else catalog, created_utc=_utc_now())


def verify_supplement(evidence_dir: Path) -> dict[str, Any]:
    """Verify the supplement, original files, usage arithmetic, and model pin offline."""
    evidence_dir = Path(evidence_dir)
    record = json.loads((evidence_dir / SUPPLEMENT_NAME).read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != "w05-usage-pricing-supplement-v1":
        raise SupplementError("supplement schema is invalid")
    digest = record.get("record_sha256")
    content = {key: value for key, value in record.items() if key != "record_sha256"}
    if digest != _digest(content):
        raise SupplementError("supplement record hash does not match content")
    catalog = record.get("catalog")
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get("conservative_pricing_snapshot"), Mapping):
        raise SupplementError("supplement lacks catalog record or snapshot")
    snapshot = catalog["conservative_pricing_snapshot"]
    expected = _derive(
        evidence_dir, {"data": [catalog.get("model_record")]},
        created_utc=record["created_utc"], fetched_utc=snapshot.get("fetched_utc"),
    )
    if record != expected:
        raise SupplementError("supplement differs from native log or pinned public model record")
    return {"verified": True, "record_sha256": digest, "estimated_usd": record["cost"]["estimated_usd"]}


def write_supplement(evidence_dir: Path) -> dict[str, Any]:
    """Create exactly one new supplemental file; never rewrite source evidence."""
    evidence_dir = Path(evidence_dir)
    record = build_supplement(evidence_dir)
    target = evidence_dir / SUPPLEMENT_NAME
    payload = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(name)
        if secret and len(secret) >= 8 and secret.encode("utf-8") in payload:
            raise SupplementError("credential value appeared in supplemental data")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return verify_supplement(evidence_dir)
