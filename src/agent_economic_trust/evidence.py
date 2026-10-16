"""Schema-checked, local evidence files for a single experiment run.

This is provenance plumbing, not a payment receipt or a cryptographic signature.
Callers supply observed actions and outcomes; this module does not infer them from
agent claims. A fresh directory is required so prior evidence cannot be erased.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
_SENSITIVE_KEY = re.compile(
    r"(?:secret|password|passphrase|credential|token|api[_-]?key|private[_-]?key|"
    r"authorization|cookie|mnemonic|seed[_-]?phrase)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_ASSIGNMENT = re.compile(
    r"\b((?:[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)|api[_-]?key)\s*[=:]\s*)\S+",
    re.IGNORECASE,
)
_USAGE_COUNT_FIELDS = frozenset({
    "input_tokens", "output_tokens", "total_tokens", "reasoning_tokens",
    "input_tokens_cache_read", "input_tokens_cache_write",
})
_PRICING_COUNT_FIELDS = frozenset({
    "input_framing_tokens_per_call", "max_completion_tokens",
})
_PRICING_RATE_FIELDS = frozenset({
    "input_usd_per_token", "output_usd_per_token",
    "cache_read_usd_per_token", "cache_write_usd_per_token",
})
_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_sha256(value: Any) -> str:
    """Hash JSON values independent of mapping insertion order (not a signature)."""
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def scrub_secrets(value: Any) -> Any:
    """Remove common credential fields and inline tokens from JSON-compatible data.

    Producers must still avoid recording raw signing or replayable authorization
    material: no heuristic scrubber can recognize every secret format.
    """
    def numeric_research_field(path: tuple[str, ...], item: Any) -> bool:
        # These are the exact top-level manifest subtrees emitted by the W05
        # exporter. A field named api_token elsewhere must still be redacted.
        if len(path) != 2:
            return False
        group, key = path
        if group == "model_usage" and key in _USAGE_COUNT_FIELDS:
            return item is None or (type(item) is int and item >= 0)
        if group == "pricing_snapshot" and key in _PRICING_COUNT_FIELDS:
            return type(item) is int and item >= 0
        if group == "pricing_snapshot" and key in _PRICING_RATE_FIELDS:
            if not isinstance(item, str) or not _DECIMAL_TEXT.fullmatch(item):
                return False
            try:
                rate = Decimal(item)
            except InvalidOperation:
                return False
            return rate.is_finite() and rate >= 0
        return False

    def walk(item: Any, path: tuple[str, ...]) -> Any:
        if isinstance(item, Mapping):
            cleaned: dict[str, Any] = {}
            for key, child in item.items():
                name = str(key)
                child_path = (*path, name)
                if (
                    _SENSITIVE_KEY.search(name)
                    and not name.lower().endswith(("_ref", "_id", "_address"))
                    and not numeric_research_field(child_path, child)
                ):
                    cleaned[name] = "[REDACTED]"
                else:
                    cleaned[name] = walk(child, child_path)
            return cleaned
        if isinstance(item, (list, tuple)):
            return [walk(child, path) for child in item]
        if isinstance(item, str):
            item = _BEARER.sub("Bearer [REDACTED]", item)
            item = _SK_TOKEN.sub("[REDACTED]", item)
            return _ASSIGNMENT.sub(r"\1[REDACTED]", item)
        return item

    return walk(value, ())


def _validator(name: str, schema_dir: Path) -> Draft202012Validator:
    schema = json.loads((schema_dir / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _validate(value: Mapping[str, Any], schema_name: str, schema_dir: Path) -> dict[str, Any]:
    cleaned = scrub_secrets(value)
    if not isinstance(cleaned, dict):
        raise TypeError("evidence must be a JSON object")
    _validator(schema_name, schema_dir).validate(cleaned)
    timestamp_field = "timestamp_utc" if schema_name == "event.schema.json" else "created_utc"
    _utc(cleaned[timestamp_field])
    _canonical_json(cleaned)  # reject non-JSON values and nonfinite numbers before writing
    return cleaned


def validate_event(event: Mapping[str, Any], *, schema_dir: Path | None = None) -> dict[str, Any]:
    """Return a scrubbed event after validating the v1 schema and UTC time."""
    return _validate(event, "event.schema.json", Path(schema_dir or _SCHEMA_DIR))


def validate_manifest(manifest: Mapping[str, Any], *, schema_dir: Path | None = None) -> dict[str, Any]:
    """Return a scrubbed manifest after validating the v1 schema and UTC time."""
    return _validate(manifest, "run_manifest.schema.json", Path(schema_dir or _SCHEMA_DIR))


def make_run_manifest(
    *,
    run_id: str,
    experiment_id: str,
    created_utc: str,
    model_behavior_tier: str,
    payment_tier: str,
    source_pins: Mapping[str, Any],
    randomization: Mapping[str, Any],
    planned_episodes: int,
    **extra: Any,
) -> dict[str, Any]:
    """Construct a valid partial manifest; the caller supplies real source pins."""
    manifest = {
        "schema_version": "1",
        "run_id": run_id,
        "created_utc": created_utc,
        "experiment_id": experiment_id,
        "status": "PARTIAL",
        "model_behavior_tier": model_behavior_tier,
        "payment_tier": payment_tier,
        "allow_mainnet": False,
        "source_pins": dict(source_pins),
        "randomization": dict(randomization),
        "planned_episodes": planned_episodes,
        "completed_episodes": 0,
        **extra,
    }
    return validate_manifest(manifest)


def _execution_tier(model_tier: str, payment_tier: str) -> str:
    if payment_tier == "NATIVE_TESTNET_APPROVED":
        return "NATIVE_TESTNET"
    if payment_tier in ("NATIVE_LOCAL_CHAIN", "NATIVE_LOCAL_FACILITATOR"):
        return "NATIVE_LOCAL_PROTOCOL"
    if model_tier == "REAL_LLM_LOCAL":
        return "REAL_LLM_LOCAL"
    if model_tier == "REAL_LLM_REMOTE_APPROVED":
        # Keep this explicit rather than falsely calling remote behavior local.
        return "REAL_LLM_REMOTE_APPROVED"
    return "SCRIPTED_SIMULATION"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvidenceWriter:
    """Write one run's JSONL events, CSV outcomes, and hashed manifest.

    The caller should create a new directory for each run. Event IDs are hashes
    of the scrubbed event content including its global sequence number and UTC
    timestamp. Supply a fixed ``created_utc`` to obtain byte-identical replays.
    """

    def __init__(
        self,
        directory: str | Path,
        manifest: Mapping[str, Any],
        *,
        schema_dir: Path | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.schema_dir = Path(schema_dir or _SCHEMA_DIR)
        self.manifest = validate_manifest(manifest, schema_dir=self.schema_dir)
        self.events_path = self.directory / "events.jsonl"
        self.outcomes_path = self.directory / "episode_outcomes.csv"
        self.manifest_path = self.directory / "run_manifest.json"
        self._seen: dict[str, tuple[str, int]] = {}
        self._next_seq = 0
        self._outcome_fields: list[str] | None = None
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in (self.events_path, self.outcomes_path, self.manifest_path):
            if path.exists():
                raise FileExistsError(f"refusing to overwrite evidence: {path}")
        self.events_path.touch(exist_ok=False)
        self.outcomes_path.touch(exist_ok=False)
        self._hashes = {"events.jsonl": sha256(), "episode_outcomes.csv": sha256()}
        self._write_manifest()

    def _write_manifest(self) -> None:
        self.manifest["artifacts_sha256"] = {
            **self.manifest.get("artifacts_sha256", {}),
            **{name: digest.hexdigest() for name, digest in self._hashes.items()},
        }
        validated = validate_manifest(self.manifest, schema_dir=self.schema_dir)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        if temporary.exists():
            raise FileExistsError(f"refusing to replace temporary evidence: {temporary}")
        try:
            temporary.write_text(_canonical_json(validated) + "\n", encoding="utf-8")
            temporary.replace(self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    def append_event(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and append an observed event; return its persisted fields."""
        if "seq" in fields or "event_id" in fields:
            raise ValueError("seq and event_id are assigned by EvidenceWriter")
        for name in ("schema_version", "run_id", "experiment_id", "model_behavior_tier", "payment_tier"):
            if name in fields and fields[name] != self.manifest[name]:
                raise ValueError(f"event {name} conflicts with run manifest")
        event = dict(fields)
        event.update({
            name: self.manifest[name]
            for name in ("schema_version", "run_id", "experiment_id", "model_behavior_tier", "payment_tier")
        })
        event["seq"] = self._next_seq
        event.setdefault(
            "timestamp_utc",
            (_utc(self.manifest["created_utc"]) + timedelta(microseconds=self._next_seq))
            .isoformat(timespec="microseconds").replace("+00:00", "Z"),
        )
        event.setdefault("parent_event_id", None)
        event = scrub_secrets(event)
        parent = event["parent_event_id"]
        if parent is not None:
            if parent not in self._seen:
                raise ValueError("parent_event_id must reference an earlier event in this run")
            if self._seen[parent][0] != event.get("episode_id"):
                raise ValueError("parent_event_id must reference the same episode")
        event["event_id"] = "ev_" + canonical_sha256(event)[:24]
        event = validate_event(event, schema_dir=self.schema_dir)
        line = (_canonical_json(event) + "\n").encode("utf-8")
        with self.events_path.open("ab") as stream:
            stream.write(line)
        self._hashes["events.jsonl"].update(line)
        self._seen[event["event_id"]] = (event["episode_id"], self._next_seq)
        self._next_seq += 1
        self._write_manifest()
        return event

    def append_exception(
        self,
        error: BaseException,
        *,
        episode_id: str,
        task_id: str,
        actor_id: str = "system",
        actor_role: str = "system",
        parent_event_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a caught failure as an ERROR event with a scrubbed message."""
        return self.append_event({
            "episode_id": episode_id,
            "task_id": task_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "event_type": "ERROR",
            "status": "ERROR",
            "parent_event_id": parent_event_id,
            "payload": {
                "exception_type": type(error).__name__,
                "message": str(error),
            },
        })

    def append_outcome(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Append an episode outcome with both evidence axes and legacy tier."""
        row = scrub_secrets(row)
        if not isinstance(row, dict):
            raise TypeError("outcome must be a JSON object")
        for name in ("run_id", "experiment_id", "model_behavior_tier", "payment_tier", "execution_tier"):
            expected = (
                _execution_tier(self.manifest["model_behavior_tier"], self.manifest["payment_tier"])
                if name == "execution_tier" else self.manifest[name]
            )
            if name in row and row[name] != expected:
                raise ValueError(f"outcome {name} conflicts with run manifest")
            row[name] = expected
        if not isinstance(row.get("episode_id"), str) or not row["episode_id"]:
            raise ValueError("outcome episode_id must be a nonempty string")
        _canonical_json(row)
        fields = sorted(row)
        if self._outcome_fields is not None and fields != self._outcome_fields:
            raise ValueError("all outcome rows must have the same fields")
        first = self._outcome_fields is None
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        if first:
            writer.writeheader()
        writer.writerow({key: _canonical_json(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})
        content = stream.getvalue().encode("utf-8")
        with self.outcomes_path.open("ab") as output:
            output.write(content)
        self._hashes["episode_outcomes.csv"].update(content)
        self._outcome_fields = fields
        self._write_manifest()
        return row

    def finalize(self, *, status: str, **updates: Any) -> dict[str, Any]:
        """Set final status/counts and refresh file hashes without changing run identity."""
        allowed = {"completed_episodes", "failed_episodes", "skipped_episodes", "numeric_cost_minor_units", "notes"}
        if set(updates) - allowed:
            raise ValueError("finalize may update only counts, cost, and notes")
        candidate = {**self.manifest, **updates, "status": status}
        self.manifest = validate_manifest(candidate, schema_dir=self.schema_dir)
        self._write_manifest()
        return dict(self.manifest)


def verify_evidence(directory: str | Path, *, schema_dir: Path | None = None) -> dict[str, int]:
    """Independently check stored hashes, schemas, event IDs and causal links."""
    directory = Path(directory)
    raw_manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    manifest = validate_manifest(raw_manifest, schema_dir=schema_dir)
    if manifest != raw_manifest:
        raise ValueError("manifest contains unsanitized material")
    hashes = manifest.get("artifacts_sha256", {})
    for required in ("events.jsonl", "episode_outcomes.csv"):
        if required not in hashes:
            raise ValueError(f"missing required artifact hash: {required}")
    for name, expected in hashes.items():
        if Path(name).name != name:
            raise ValueError("artifact hash names must be local basenames")
        if _file_sha256(directory / name) != expected:
            raise ValueError(f"{name} does not match run manifest hash")
    seen: dict[str, str] = {}
    events = 0
    with (directory / "events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            raw_event = json.loads(line)
            event = validate_event(raw_event, schema_dir=schema_dir)
            if event != raw_event:
                raise ValueError("event contains unsanitized material")
            if event["seq"] != events:
                raise ValueError("event sequence is not contiguous")
            for field in ("schema_version", "run_id", "experiment_id", "model_behavior_tier", "payment_tier"):
                if event[field] != manifest[field]:
                    raise ValueError(f"event {field} conflicts with run manifest")
            event_without_id = {key: value for key, value in event.items() if key != "event_id"}
            if event["event_id"] != "ev_" + canonical_sha256(event_without_id)[:24]:
                raise ValueError("event ID does not match canonical event content")
            parent = event.get("parent_event_id")
            if parent is not None and seen.get(parent) != event["episode_id"]:
                raise ValueError("event parent must precede it in the same episode")
            seen[event["event_id"]] = event["episode_id"]
            events += 1
    outcomes = 0
    with (directory / "episode_outcomes.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if not row.get("episode_id"):
                raise ValueError("outcome is missing episode_id")
            for field in ("run_id", "experiment_id", "model_behavior_tier", "payment_tier"):
                if row.get(field) != manifest[field]:
                    raise ValueError(f"outcome {field} conflicts with run manifest")
            if row.get("execution_tier") != _execution_tier(manifest["model_behavior_tier"], manifest["payment_tier"]):
                raise ValueError("outcome execution_tier conflicts with run manifest")
            outcomes += 1
    return {"events": events, "outcomes": outcomes}
