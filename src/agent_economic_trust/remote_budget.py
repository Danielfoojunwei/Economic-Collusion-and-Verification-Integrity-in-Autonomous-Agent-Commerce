"""Project-wide, fail-closed USD accounting for optional paid model calls.

This is a local spending guard, not a provider billing receipt.  Callers must
reserve *before* a remote request and settle from provider billing evidence.
The JSONL ledger is hash chained and its separate anchor detects truncation of
the final record.  Neither file is authenticated against an attacker who can
rewrite both; keep them in a trusted workspace and retain provider invoices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Mapping


_ZERO_HASH = "0" * 64
_INITIAL_AUTHORIZED_USD = Decimal("20")
MAX_AUTHORIZED_USD = Decimal("50")
_SENSITIVE_KEY = re.compile(
    r"secret|password|passphrase|credential|token|api[_-]?key|private[_-]?key|"
    r"authorization|cookie|mnemonic|seed[_-]?phrase",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}\b|"
    r"\b(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
    re.IGNORECASE,
)
_REASON_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,99}\Z")
_EVIDENCE_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FINAL_PROVIDER_BILLING = re.compile(r"provider-billing:sha256:[0-9a-f]{64}\Z")


class BudgetError(Exception):
    """Base class for a denied budget operation."""


class BudgetMissingError(BudgetError, FileNotFoundError):
    """The ledger or its anchor has not been explicitly created."""


class BudgetIntegrityError(BudgetError):
    """Ledger and anchor did not validate; no further spending is allowed."""


class BudgetExceeded(BudgetError):
    """A reservation would exceed the currently authorized project cap."""


class BudgetStateError(BudgetError):
    """A run is duplicated, unknown, or otherwise in the wrong state."""


def _usd(value: str | int | Decimal, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise TypeError(f"{name} must be a decimal string, integer, or Decimal")
    if isinstance(value, str) and (not value or len(value) > 64):
        raise ValueError(f"{name} is not a valid USD amount")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} is not a valid USD amount") from exc
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    if amount.adjusted() > 12:
        raise ValueError(f"{name} is outside the supported USD range")
    if amount.as_tuple().exponent < -12:
        raise ValueError(f"{name} supports at most 12 decimal places")
    return amount


def _format_usd(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _safe_text(value: str, name: str, *, limit: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or _SENSITIVE_TEXT.search(value):
        raise ValueError(f"{name} must be a non-secret, nonempty string of at most {limit} characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} contains a control character")
    return value


def _safe_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")

    def check(item: Any, depth: int) -> Any:
        if depth > 5:
            raise ValueError("metadata nesting is too deep")
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str) or _SENSITIVE_KEY.search(key):
                    raise ValueError("metadata contains a sensitive or invalid key")
                result[_safe_text(key, "metadata key", limit=100)] = check(child, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [check(child, depth + 1) for child in item]
        if isinstance(item, str):
            return _safe_text(item, "metadata value")
        if item is None or isinstance(item, (bool, int)):
            return item
        raise TypeError("metadata supports only JSON strings, integers, booleans, and null")

    cleaned = check(value, 0)
    if len(_canonical(cleaned)) > 4096:
        raise ValueError("metadata exceeds 4096 bytes")
    return cleaned


def _safe_reason(value: str) -> str:
    """Keep error messages out of the ledger while still marking charge unknown."""
    if not isinstance(value, str):
        raise TypeError("reason must be a string")
    if not _REASON_CODE.fullmatch(value) or _SENSITIVE_TEXT.search(value):
        return "unspecified_or_sensitive_error"
    return value


def _contingent_evidence(value: str) -> str:
    if not isinstance(value, str) or not _EVIDENCE_SHA256.fullmatch(value):
        raise ValueError("contingent evidence_ref must be sha256:<64 lowercase hex>")
    return value


def _final_billing_evidence(value: str) -> str:
    if not isinstance(value, str) or not _FINAL_PROVIDER_BILLING.fullmatch(value):
        raise ValueError("contingent run settlement requires provider-billing:sha256:<64 lowercase hex>")
    return value


def _anchor_path(path: Path) -> Path:
    return path.with_name(path.name + ".anchor")


def _open_regular(path: Path, flags: int) -> int:
    try:
        fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise BudgetMissingError("budget ledger or anchor is missing") from exc
    except OSError as exc:
        raise BudgetIntegrityError("budget ledger cannot be opened safely") from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise BudgetIntegrityError("budget ledger must be a regular file")
    return fd


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("budget ledger write did not make progress")
        view = view[written:]


def _record(seq: int, prev_hash: str, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "v": 1,
        "seq": seq,
        "prev_hash": prev_hash,
        "kind": kind,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "payload": dict(payload),
    }
    return {**body, "hash": sha256(_canonical(body)).hexdigest()}


def _write_anchor(path: Path, *, seq: int, digest: str, size: int, initial: bool = False) -> None:
    anchor = _anchor_path(path)
    contents = _canonical({"v": 1, "seq": seq, "hash": digest, "size": size}) + b"\n"
    if initial:
        fd = os.open(anchor, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            _write_all(fd, contents)
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        fd, temporary = tempfile.mkstemp(prefix=anchor.name + ".tmp-", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, contents)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, anchor)
        finally:
            if fd != -1:
                os.close(fd)
            if os.path.exists(temporary):
                os.unlink(temporary)
    _sync_directory(path.parent)


def create_ledger(
    path: str | Path, cap_usd: str | int | Decimal, opening_spent_usd: str | int | Decimal = "0"
) -> BudgetLedger:
    """Explicitly create a ledger once; existing files are never reset or overwritten."""
    ledger_path = Path(path)
    cap = _usd(cap_usd, "cap_usd", positive=True)
    if cap > _INITIAL_AUTHORIZED_USD:
        raise BudgetExceeded("new ledger cap exceeds the original USD 20 authorization")
    opening = _usd(opening_spent_usd, "opening_spent_usd")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if _anchor_path(ledger_path).exists():
        raise FileExistsError("budget anchor already exists")
    fd = os.open(
        ledger_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        entry = _record(0, _ZERO_HASH, "create", {
            "cap_usd": _format_usd(cap), "opening_spent_usd": _format_usd(opening),
        })
        data = _canonical(entry) + b"\n"
        _write_all(fd, data)
        os.fsync(fd)
        _write_anchor(ledger_path, seq=0, digest=entry["hash"], size=len(data), initial=True)
    finally:
        os.close(fd)
    return BudgetLedger(ledger_path)


class BudgetLedger:
    """Open, verify, and mutate one project-wide ledger under an OS file lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load_locked(self, fd: int) -> tuple[dict[str, Any], int, str, int]:
        anchor_fd = _open_regular(_anchor_path(self.path), os.O_RDONLY)
        try:
            with os.fdopen(os.dup(anchor_fd), "rb") as stream:
                raw_anchor = stream.read()
        finally:
            os.close(anchor_fd)
        try:
            anchor = json.loads(raw_anchor)
            if (
                set(anchor) != {"v", "seq", "hash", "size"}
                or type(anchor["v"]) is not int or anchor["v"] != 1
                or type(anchor["seq"]) is not int or anchor["seq"] < 0
                or type(anchor["size"]) is not int or anchor["size"] <= 0
                or not isinstance(anchor["hash"], str)
                or _canonical(anchor) + b"\n" != raw_anchor
            ):
                raise ValueError("invalid anchor")
            os.lseek(fd, 0, os.SEEK_SET)
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read()
            if len(data) != anchor["size"] or not data.endswith(b"\n"):
                raise ValueError("ledger length or final newline differs from anchor")
            lines = data.splitlines(keepends=True)
            if not lines:
                raise ValueError("empty ledger")
            runs: dict[str, dict[str, Any]] = {}
            cap = Decimal(0)
            opening = Decimal(0)
            settled = Decimal(0)
            reserved = Decimal(0)
            prev = _ZERO_HASH
            for seq, raw in enumerate(lines):
                event = json.loads(raw)
                if not isinstance(event, dict) or set(event) != {
                    "v", "seq", "prev_hash", "kind", "timestamp_utc", "payload", "hash"
                }:
                    raise ValueError("invalid event fields")
                if type(event["v"]) is not int or event["v"] != 1 or type(event["seq"]) is not int or event["seq"] != seq:
                    raise ValueError("invalid event version or sequence")
                if event["prev_hash"] != prev or not isinstance(event["hash"], str):
                    raise ValueError("broken hash chain")
                if _canonical(event) + b"\n" != raw:
                    raise ValueError("noncanonical event")
                body = {key: value for key, value in event.items() if key != "hash"}
                if not hmac.compare_digest(event["hash"], sha256(_canonical(body)).hexdigest()):
                    raise ValueError("event hash mismatch")
                payload = event["payload"]
                if not isinstance(payload, dict):
                    raise ValueError("invalid payload")
                kind = event["kind"]
                if seq == 0:
                    if kind != "create" or set(payload) != {"cap_usd", "opening_spent_usd"}:
                        raise ValueError("invalid genesis")
                    cap = self._stored_usd(payload["cap_usd"], "cap_usd", positive=True)
                    if cap > _INITIAL_AUTHORIZED_USD:
                        raise ValueError("genesis cap exceeds original authorization")
                    opening = self._stored_usd(payload["opening_spent_usd"], "opening_spent_usd")
                    settled = opening
                elif kind == "reserve":
                    if set(payload) != {"run_id", "amount_usd", "metadata", "cap_usd"}:
                        raise ValueError("invalid reservation")
                    run_id = _safe_text(payload["run_id"], "run_id", limit=200)
                    if run_id in runs or payload["cap_usd"] != _format_usd(cap):
                        raise ValueError("duplicate run or changed cap")
                    amount = self._stored_usd(payload["amount_usd"], "amount_usd", positive=True)
                    if _safe_metadata(payload["metadata"]) != payload["metadata"]:
                        raise ValueError("invalid stored metadata")
                    runs[run_id] = {
                        "status": "RESERVED", "reserved_usd": _format_usd(amount),
                        "metadata": payload["metadata"],
                    }
                    reserved += amount
                    if settled + reserved > cap:
                        raise ValueError("reservation exceeds project cap")
                elif kind == "cap_raise":
                    if set(payload) != {"prior_cap_usd", "new_cap_usd", "authorization_ref"}:
                        raise ValueError("invalid cap raise")
                    prior = self._stored_usd(payload["prior_cap_usd"], "prior_cap_usd", positive=True)
                    raised = self._stored_usd(payload["new_cap_usd"], "new_cap_usd", positive=True)
                    _safe_text(payload["authorization_ref"], "authorization_ref")
                    if prior != cap or raised <= cap or raised > MAX_AUTHORIZED_USD:
                        raise ValueError("cap raise exceeds or lacks owner authorization")
                    cap = raised
                elif kind == "settle":
                    if set(payload) != {"run_id", "actual_usd", "evidence_ref"}:
                        raise ValueError("invalid settlement")
                    run_id = _safe_text(payload["run_id"], "run_id", limit=200)
                    if run_id not in runs or runs[run_id]["status"] == "SETTLED":
                        raise ValueError("settlement has no open reservation")
                    actual = self._stored_usd(payload["actual_usd"], "actual_usd")
                    _safe_text(payload["evidence_ref"], "evidence_ref")
                    if "contingent_evidence_ref" in runs[run_id]:
                        _final_billing_evidence(payload["evidence_ref"])
                    runs[run_id].update({
                        "status": "SETTLED", "actual_usd": _format_usd(actual),
                        "evidence_ref": payload["evidence_ref"],
                    })
                    reserved -= Decimal(runs[run_id]["reserved_usd"])
                    settled += actual
                elif kind == "unknown":
                    if set(payload) != {"run_id", "reason"}:
                        raise ValueError("invalid unknown charge")
                    run_id = _safe_text(payload["run_id"], "run_id", limit=200)
                    if run_id not in runs or runs[run_id]["status"] not in {"RESERVED", "CONTINGENT"}:
                        raise ValueError("unknown charge has no open reservation")
                    if _safe_reason(payload["reason"]) != payload["reason"]:
                        raise ValueError("invalid stored unknown reason")
                    if runs[run_id]["status"] == "CONTINGENT":
                        runs[run_id].pop("evidence_ref")
                    runs[run_id].update({"status": "UNKNOWN", "unknown_reason": payload["reason"]})
                elif kind == "contingent":
                    if set(payload) != {"run_id", "evidence_ref"}:
                        raise ValueError("invalid contingent charge")
                    run_id = _safe_text(payload["run_id"], "run_id", limit=200)
                    if (run_id not in runs or runs[run_id]["status"] != "UNKNOWN"
                            or "contingent_evidence_ref" in runs[run_id]):
                        raise ValueError("contingent charge has no eligible unknown reservation")
                    evidence_ref = _contingent_evidence(payload["evidence_ref"])
                    prior_reason = runs[run_id].pop("unknown_reason")
                    runs[run_id].update({
                        "status": "CONTINGENT",
                        "evidence_ref": evidence_ref,
                        "contingent_evidence_ref": evidence_ref,
                        "prior_unknown_reason": prior_reason,
                    })
                else:
                    raise ValueError("invalid event kind")
                prev = event["hash"]
            if anchor["seq"] != len(lines) - 1 or anchor["hash"] != prev:
                raise ValueError("anchor differs from ledger head")
            committed = settled + reserved
            unknown_ids = sorted(run_id for run_id, run in runs.items() if run["status"] == "UNKNOWN")
            contingent_ids = sorted(run_id for run_id, run in runs.items() if run["status"] == "CONTINGENT")
            snapshot = {
                "cap_usd": _format_usd(cap),
                "opening_spent_usd": _format_usd(opening),
                "settled_spent_usd": _format_usd(settled),
                "reserved_usd": _format_usd(reserved),
                "committed_usd": _format_usd(committed),
                "available_usd": _format_usd(cap - committed),
                "over_cap": committed > cap,
                "blocked": bool(unknown_ids) or committed >= cap,
                "unknown_run_ids": unknown_ids,
                "contingent_run_ids": contingent_ids,
                "runs": runs,
                "seq": len(lines) - 1,
                "last_hash": prev,
            }
            return snapshot, len(lines) - 1, prev, len(data)
        except (TypeError, ValueError, KeyError, UnicodeError, InvalidOperation) as exc:
            raise BudgetIntegrityError("budget ledger or anchor failed validation") from exc

    @staticmethod
    def _stored_usd(value: Any, name: str, *, positive: bool = False) -> Decimal:
        if not isinstance(value, str):
            raise ValueError("stored USD amount must be a string")
        amount = _usd(value, name, positive=positive)
        if value != _format_usd(amount):
            raise ValueError("stored USD amount is noncanonical")
        return amount

    def snapshot(self) -> dict[str, Any]:
        fd = _open_regular(self.path, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            snapshot, _, _, _ = self._load_locked(fd)
            return snapshot
        finally:
            os.close(fd)

    read = snapshot

    def _mutate(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        fd = _open_regular(self.path, os.O_RDWR | os.O_APPEND)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            snapshot, seq, prev, size = self._load_locked(fd)
            if kind == "cap_raise":
                prior = Decimal(snapshot["cap_usd"])
                raised = Decimal(payload["new_cap_usd"])
                if payload["prior_cap_usd"] != snapshot["cap_usd"]:
                    raise BudgetStateError("cap raise does not match current ledger cap")
                if raised <= prior or raised > MAX_AUTHORIZED_USD:
                    raise BudgetExceeded("cap raise exceeds owner's USD 50 authorization")
            else:
                run_id = payload["run_id"]
                current = snapshot["runs"].get(run_id)
            if kind == "reserve":
                if current is not None:
                    raise BudgetStateError("run_id already has a reservation")
                if snapshot["unknown_run_ids"]:
                    raise BudgetStateError("unsettled unknown charge blocks new reservations")
                if payload["cap_usd"] != snapshot["cap_usd"]:
                    raise BudgetStateError("reserve cap does not match current ledger cap")
                if Decimal(snapshot["committed_usd"]) + Decimal(payload["amount_usd"]) > Decimal(snapshot["cap_usd"]):
                    raise BudgetExceeded("reservation exceeds project-wide USD cap")
            elif kind == "settle":
                if current is None:
                    raise BudgetStateError("run_id has no reservation")
                if current["status"] == "SETTLED":
                    if (current["actual_usd"], current["evidence_ref"]) == (payload["actual_usd"], payload["evidence_ref"]):
                        return snapshot
                    raise BudgetStateError("run_id was settled with different evidence or amount")
                if "contingent_evidence_ref" in current:
                    try:
                        _final_billing_evidence(payload["evidence_ref"])
                    except ValueError as exc:
                        raise BudgetStateError("contingent run requires attributable final provider billing") from exc
            elif kind == "contingent":
                if current is None or current["status"] != "UNKNOWN" or "contingent_evidence_ref" in current:
                    raise BudgetStateError("run_id has no eligible unknown reservation")
            elif kind == "unknown":
                if current is None or current["status"] == "SETTLED":
                    raise BudgetStateError("run_id has no open reservation")
                if current["status"] == "UNKNOWN":
                    if current["unknown_reason"] == payload["reason"]:
                        return snapshot
                    raise BudgetStateError("run_id already has a different unknown reason")
            event = _record(seq + 1, prev, kind, payload)
            data = _canonical(event) + b"\n"
            _write_all(fd, data)
            os.fsync(fd)
            _write_anchor(self.path, seq=seq + 1, digest=event["hash"], size=size + len(data))
            updated, _, _, _ = self._load_locked(fd)
            return updated
        finally:
            os.close(fd)

    def reserve(
        self,
        run_id: str,
        amount_usd: str | int | Decimal,
        cap_usd: str | int | Decimal,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically reserve budget before any external request."""
        return self._mutate("reserve", {
            "run_id": _safe_text(run_id, "run_id", limit=200),
            "amount_usd": _format_usd(_usd(amount_usd, "amount_usd", positive=True)),
            "cap_usd": _format_usd(_usd(cap_usd, "cap_usd", positive=True)),
            "metadata": _safe_metadata(metadata),
        })

    def raise_cap(self, new_cap_usd: str | int | Decimal, authorization_ref: str) -> dict[str, Any]:
        """Append an owner-authorized prospective cap increase to this ledger."""
        current = self.snapshot()["cap_usd"]
        return self._mutate("cap_raise", {
            "prior_cap_usd": current,
            "new_cap_usd": _format_usd(_usd(new_cap_usd, "new_cap_usd", positive=True)),
            "authorization_ref": _safe_text(authorization_ref, "authorization_ref"),
        })

    def settle(
        self, run_id: str, actual_usd: str | int | Decimal, evidence_ref: str
    ) -> dict[str, Any]:
        """Reconcile a reservation using an external billing evidence reference.

        For a run previously marked CONTINGENT, evidence_ref must be
        provider-billing:sha256:<digest> of attributable final provider billing.
        The caller must independently verify those bytes and attribution; this
        ledger validates only the reference syntax. An actual charge above its
        estimate is recorded even if it exceeds the cap, so later reservations
        fail closed instead of hiding debt.
        """
        return self._mutate("settle", {
            "run_id": _safe_text(run_id, "run_id", limit=200),
            "actual_usd": _format_usd(_usd(actual_usd, "actual_usd")),
            "evidence_ref": _safe_text(evidence_ref, "evidence_ref"),
        })

    def mark_unknown(self, run_id: str, reason: str) -> dict[str, Any]:
        """Block future calls, including reblocking discredited CONTINGENT evidence."""
        return self._mutate("unknown", {
            "run_id": _safe_text(run_id, "run_id", limit=200),
            "reason": _safe_reason(reason),
        })

    def mark_contingent(self, run_id: str, evidence_ref: str) -> dict[str, Any]:
        """Unblock an UNKNOWN run while retaining its full cap reservation.

        The evidence is a content-addressed provisional billing assessment, not
        an actual charge or a final invoice. This transition is allowed once.
        """
        return self._mutate("contingent", {
            "run_id": _safe_text(run_id, "run_id", limit=200),
            "evidence_ref": _contingent_evidence(evidence_ref),
        })


def read_ledger(path: str | Path) -> dict[str, Any]:
    """Validate the full ledger and return a detached accounting snapshot."""
    return BudgetLedger(path).snapshot()
