"""One-shot zero-price execution of the frozen x402 A-to-B text assignment.

The x402 receipt is archived local evidence for paid access to report A. Model
calls here neither buy another report nor execute buyer checks or settlement.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping

from . import free_collusion_probe as free
from . import x402_free_handoff_study as study


ASSIGNMENT_PATH = (study.ROOT / "artifacts/prospective/X402_FREE_HANDOFF_A_TO_B/"
                   "assignment-001/assignment_manifest.json")
ASSIGNMENT_SHA256 = "53b08f9f22de7cb1ac7d1f445969e9e4c72140dc3bceddf54f0176d2a3022128"
SOURCE_SHA256 = "e18fe2ca95837a26d03bc69a22bcbf9465a9ef0f72dd656f20ddc85fe6d73405"
ZERO_LINK = "0" * 64


class HandoffExecutionError(RuntimeError):
    """A price, billing, HTTP, assignment, or evidence boundary failed."""


class RowIncomplete(HandoffExecutionError):
    """An assigned model context gave no complete terminal decision."""


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise HandoffExecutionError("required source file is absent or linked")
    return sha256(path.read_bytes()).hexdigest()


def _source_paths() -> dict[str, Path]:
    return {"x402_study": Path(study.__file__),
            "execution_runner": Path(__file__),
            "zero_price_transport": Path(free.__file__)}


def _source_hashes() -> dict[str, str]:
    return {name: _sha(path) for name, path in _source_paths().items()}


def _read_assignment(path: Path = ASSIGNMENT_PATH) -> tuple[bytes, dict[str, Any]]:
    path = Path(path)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != ASSIGNMENT_SHA256:
        raise HandoffExecutionError("assignment bytes differ from prospectively frozen manifest")
    if _sha(Path(study.__file__)) != SOURCE_SHA256:
        raise HandoffExecutionError("frozen x402 prompt source changed")
    try:
        value = json.loads(raw)
        proof = study.verify_manifest(path)
    except Exception as exc:
        raise HandoffExecutionError("frozen assignment or archived receipt replay failed") from exc
    if (proof["manifest_sha256"] != ASSIGNMENT_SHA256
        or value.get("source_code_sha256") != SOURCE_SHA256
        or value.get("schema") != "x402-free-handoff-source-v1"
        or value.get("planned_rows") != 60
        or value.get("rows_per_arm") != {"CONTACT": 30, "NO_CONTACT": 30}
        or value.get("max_retries") != 0
        or value.get("reasoning_effort_requested") != "high"
        or value.get("max_tokens_per_model_call") != 4096):
        raise HandoffExecutionError("frozen assignment geometry or prompt settings differ")
    return raw, value


def dry_run(path: Path = ASSIGNMENT_PATH) -> dict[str, Any]:
    raw, assignment = _read_assignment(path)
    seal = study.sealed_evidence()
    row = assignment["rows"][0]
    provider = study.provider_request(row, seal)
    auditor = study.auditor_initial_request(
        row, seal, "PROVIDER_MESSAGE_PLACEHOLDER" if row["arm"] == "CONTACT" else None)
    return {"status": "READY_FOR_ZERO_PRICE_EXECUTION_NO_CALLS",
            "assignment_sha256": sha256(raw).hexdigest(),
            "planned_pairs": len(assignment["rows"]),
            "rows_per_arm": assignment["rows_per_arm"],
            "provider_model": provider["model"], "auditor_model": auditor["model"],
            "reasoning_effort": provider["reasoning"]["effort"],
            "max_tokens": provider["max_tokens"],
            "new_native_payments": 0, "model_calls": 0}


def _write_once(path: Path, value: Any) -> str:
    data = free.canonical(value) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    return sha256(data).hexdigest()


def _write_bytes_once(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _append_index(path: Path, entry: Mapping[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, free.canonical(entry) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def _selected_model(catalog: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    data = catalog.get("data")
    if not isinstance(data, list):
        raise HandoffExecutionError("catalog data is absent")
    matches = [model for model in data if isinstance(model, Mapping)
               and model.get("id") == model_id]
    if len(matches) != 1:
        raise HandoffExecutionError("catalog has no unique exact model")
    return json.loads(free.canonical(matches[0]))


def _assert_request_guard(request: Mapping[str, Any]) -> None:
    if (request.get("model") not in {study.PROVIDER_MODEL, study.AUDITOR_MODEL}
        or request.get("reasoning") != {"effort": "high"}
        or request.get("max_tokens") != 4096
        or request.get("stream") is not False
        or request.get("provider") != {"allow_fallbacks": False,
                                       "max_price": {"prompt": 0, "completion": 0, "request": 0}}
        or len(free.canonical(request)) > free.MAX_REQUEST_BYTES):
        raise HandoffExecutionError("prepared request violates zero-price execution guard")


def _call(transport: Any, request: Mapping[str, Any], calls: list[dict[str, Any]],
          last_usage: list[Any]) -> str:
    """One POST maximum, with fresh exact public quote and account checks."""
    _assert_request_guard(request)
    call: dict[str, Any] = {"requested_utc": free.utc_now(), "request": request,
                            "request_sha256": sha256(free.canonical(request)).hexdigest(),
                            "model_id": request["model"]}
    calls.append(call)
    try:
        catalog = transport.catalog()
        call["catalog_fetched_utc"] = free.utc_now()
        call["price_proof"] = free.assert_zero_price(catalog, request["model"])
        call["selected_catalog_model"] = _selected_model(catalog, request["model"])
        before = transport.usage()
        call["account_usage_before_usd"] = str(before)
        if last_usage[0] is not None and before != last_usage[0]:
            call["preflight_failure"] = "INTER_CALL_ACCOUNT_DELTA"
            raise HandoffExecutionError("account usage changed between assigned calls")
    except Exception as exc:
        call["preflight_error_type"] = type(exc).__name__
        raise HandoffExecutionError("fresh zero-price or usage preflight failed") from None
    try:
        raw = transport.chat(request)
    except Exception as exc:
        call["post_error_type"] = type(exc).__name__
        try:
            after_failure = transport.usage()
            call["account_usage_after_usd"] = str(after_failure)
            call["account_usage_delta_usd"] = str(after_failure - before)
        except Exception as usage_exc:
            call["account_usage_after_error_type"] = type(usage_exc).__name__
        raise HandoffExecutionError("model POST failed; billing may be unknown") from None
    call["completed_utc"] = free.utc_now()
    try:
        response = free.sanitize_response(raw, request["model"])
        call["response"] = response
    except Exception as exc:
        call["response_parse_error_type"] = type(exc).__name__
        try:
            after_parse_failure = transport.usage()
            call["account_usage_after_usd"] = str(after_parse_failure)
            call["account_usage_delta_usd"] = str(after_parse_failure - before)
        except Exception as usage_exc:
            call["account_usage_after_error_type"] = type(usage_exc).__name__
        raise HandoffExecutionError("response cannot establish zero cost") from None
    try:
        after = transport.usage()
        cost = free._money(response["usage"]["cost"], "response cost")
    except Exception as exc:
        call["billing_check_error_type"] = type(exc).__name__
        raise HandoffExecutionError("account or response billing is unknown") from None
    call["account_usage_after_usd"] = str(after)
    call["account_usage_delta_usd"] = str(after - before)
    if cost != free.ZERO or after != before:
        raise HandoffExecutionError("positive or ambiguous model billing")
    last_usage[0] = after
    call["catalog_response_and_account_zero_price"] = True
    if response["finish_reason"] != "stop":
        raise RowIncomplete("model response did not finish normally")
    if not response["text"].strip():
        raise RowIncomplete("model response has no visible final text")
    return response["text"]


def _semantic_replay(row: Mapping[str, Any], seal: study.EvidenceSeal,
                     calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct actual role contexts, model choice, and offline handoff."""
    if not 2 <= len(calls) <= 3:
        raise HandoffExecutionError("complete pair must have two or three calls")
    expected_provider = study.provider_request(row, seal)
    if calls[0].get("request") != expected_provider:
        raise HandoffExecutionError("provider request differs from frozen prompt")
    provider_text = calls[0]["response"]["text"]
    expected_initial = study.auditor_initial_request(
        row, seal, provider_text if row["arm"] == "CONTACT" else None)
    if calls[1].get("request") != expected_initial:
        raise HandoffExecutionError("auditor exposure or frozen prompt differs")
    initial_text = calls[1]["response"]["text"]
    check = study._line(initial_text, "CHECK", {"BUY", "SKIP"})
    initial_verdict = study._line(initial_text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
    followup = None
    final_text = None
    if check == "BUY" and initial_verdict == "HOLD":
        if len(calls) != 3:
            raise HandoffExecutionError("BUY/HOLD has no authoritative check continuation")
        followup = study.auditor_after_check_request(row, seal, expected_initial, initial_text)
        if calls[2].get("request") != followup:
            raise HandoffExecutionError("buyer check continuation differs from frozen prompt")
        final_text = calls[2]["response"]["text"]
    elif check == "SKIP" and initial_verdict in {"ACCEPT", "REJECT"}:
        if len(calls) != 2:
            raise HandoffExecutionError("SKIP row has an extra model call")
    else:
        raise HandoffExecutionError("ambiguous action was marked complete")
    labels = study.classify_text_decision(
        row, provider_text, expected_initial, initial_text, seal=seal,
        followup_request=followup, final_response=final_text)
    verdict = labels["auditor_verdict"]
    if verdict not in {"ACCEPT", "REJECT"}:
        raise HandoffExecutionError("complete row lacks a terminal verdict")
    replay = study.offline_adapter_replay(seal, verdict)
    return {"classification": labels, "offline_handoff_replay": replay}


def _expected_incomplete_reason(calls: list[dict[str, Any]]) -> str:
    """Recompute whether the last zero-price call genuinely lacks a scored end."""
    if not calls:
        raise HandoffExecutionError("incomplete row has no assigned model attempt")
    response = calls[-1].get("response")
    if not isinstance(response, Mapping):
        raise HandoffExecutionError("incomplete row has no billed model response")
    if response.get("finish_reason") != "stop":
        return "model response did not finish normally"
    text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        return "model response has no visible final text"
    if len(calls) == 2:
        check = study._line(text, "CHECK", {"BUY", "SKIP"})
        verdict = study._line(text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
        if (check, verdict) not in {("BUY", "HOLD"), ("SKIP", "ACCEPT"),
                                    ("SKIP", "REJECT")}:
            return "auditor action or provisional verdict is ambiguous"
    elif len(calls) == 3:
        if study._line(text, "VERDICT", {"ACCEPT", "REJECT"}) not in {"ACCEPT", "REJECT"}:
            return "auditor final verdict after BUY is ambiguous"
    raise HandoffExecutionError("incomplete row contains a scoreable decision")


def _validate_live_environment() -> str:
    if os.environ.get("ALLOW_X402_FREE_HANDOFF_CALLS", "false").lower() != "true":
        raise HandoffExecutionError("ALLOW_X402_FREE_HANDOFF_CALLS must be true")
    return free._validate_live_environment()


def execute(output_dir: Path, *, assignment_path: Path = ASSIGNMENT_PATH,
            transport: Any | None = None) -> dict[str, Any]:
    """Attempt each frozen pair once; row-level ambiguity never changes assignment."""
    raw, assignment = _read_assignment(assignment_path)
    seal = study.sealed_evidence()
    test_double = transport is not None and getattr(transport, "offline_test_double", False) is True
    if not test_double:
        key = _validate_live_environment()
        if transport is None:
            transport = free.OpenRouterTransport(key)
    sources = _source_hashes()
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_bytes_once(output_dir / "assignment_manifest.json", raw)
    manifest = {
        "schema": "x402-free-handoff-execution-v1", "created_utc": free.utc_now(),
        "assignment_sha256": ASSIGNMENT_SHA256, "source_hashes": sources,
        "planned_rows": 60, "rows_per_arm": {"CONTACT": 30, "NO_CONTACT": 30},
        "model_execution_tier": "SCRIPTED_TEST_DOUBLE" if test_double else "REAL_REMOTE_ZERO_PRICE_IF_COMPLETED",
        "payment_execution_tier": "ARCHIVED_X402_A_ONLY_NO_NEW_NATIVE_PAYMENTS",
        "execution_tier": "SCRIPTED_SIMULATION",
        "execution_tier_detail": ("SCRIPTED_TEST_DOUBLE_WITH_ARCHIVED_X402_A" if test_double else
                                  "REMOTE_ZERO_PRICE_TEXT_WITH_ARCHIVED_X402_A"),
        "max_retries": 0,
        "stop_rule": "Global stop on pricing, HTTP, cost, account, or evidence failure. Nonterminal or ambiguous model text leaves the assigned row incomplete without retry or replacement.",
        "billing_evidence_limit": "Public zero-price catalog and per-response zero cost are checked at each POST. Immediate account counters can lag; reconcile later provider billing separately.",
        "shared_case_limit": "All 60 fresh contexts reuse one archived A receipt and one BAD B invoice.",
    }
    manifest_hash = _write_once(output_dir / "run_manifest.json", manifest)
    previous = ZERO_LINK
    completed = incomplete = 0
    last_usage: list[Any] = [None]
    for row in assignment["rows"]:
        record: dict[str, Any] = {"row": row, "assignment_sha256": ASSIGNMENT_SHA256,
                                  "run_manifest_sha256": manifest_hash,
                                  "execution_tier": manifest["execution_tier"],
                                  "execution_tier_detail": manifest["execution_tier_detail"],
                                  "model_execution_tier": manifest["model_execution_tier"],
                                  "transaction_execution_tier": manifest["payment_execution_tier"],
                                  "started_utc": free.utc_now(), "status": "RUNNING", "calls": []}
        try:
            if _source_hashes() != sources or _sha(Path(study.__file__)) != SOURCE_SHA256:
                raise HandoffExecutionError("source changed during frozen assignment")
            if _sha(Path(assignment_path)) != ASSIGNMENT_SHA256:
                raise HandoffExecutionError("assignment changed during frozen run")
            provider_text = _call(transport, study.provider_request(row, seal),
                                  record["calls"], last_usage)
            initial_request = study.auditor_initial_request(
                row, seal, provider_text if row["arm"] == "CONTACT" else None)
            initial_text = _call(transport, initial_request, record["calls"], last_usage)
            check = study._line(initial_text, "CHECK", {"BUY", "SKIP"})
            verdict = study._line(initial_text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
            if check == "BUY" and verdict == "HOLD":
                followup = study.auditor_after_check_request(row, seal,
                                                               initial_request, initial_text)
                final_text = _call(transport, followup, record["calls"], last_usage)
                if study._line(final_text, "VERDICT", {"ACCEPT", "REJECT"}) not in {"ACCEPT", "REJECT"}:
                    raise RowIncomplete("auditor final verdict after BUY is ambiguous")
            elif check != "SKIP" or verdict not in {"ACCEPT", "REJECT"}:
                raise RowIncomplete("auditor action or provisional verdict is ambiguous")
            record.update(_semantic_replay(row, seal, record["calls"]))
            record["status"] = "COMPLETE"
            completed += 1
        except RowIncomplete as exc:
            record["status"] = "INCOMPLETE"
            record["incomplete_reason"] = str(exc)
            incomplete += 1
        except Exception as exc:
            record["status"] = "STOPPED"
            record["stop_error_type"] = type(exc).__name__
        record["ended_utc"] = free.utc_now()
        filename = row["episode_id"] + ".json"
        row_hash = _write_once(output_dir / filename, record)
        entry = {"episode_id": row["episode_id"], "row_file": filename,
                 "row_sha256": row_hash, "assignment_sha256": ASSIGNMENT_SHA256,
                 "run_manifest_sha256": manifest_hash,
                 "prev_entry_sha256": previous}
        entry["entry_sha256"] = sha256(free.canonical(entry)).hexdigest()
        _append_index(output_dir / "index.jsonl", entry)
        previous = entry["entry_sha256"]
        if record["status"] == "STOPPED":
            stopped = {"status": "STOPPED", "stopped_episode_id": row["episode_id"],
                       "stop_error_type": record["stop_error_type"],
                       "completed_rows": completed, "incomplete_rows": incomplete,
                       "planned_rows": 60, "remaining_rows_not_run": 60 - completed - incomplete - 1,
                       "last_entry_sha256": previous,
                       "run_manifest_sha256": manifest_hash}
            _write_once(output_dir / "STOPPED.json", stopped)
            return stopped
    summary = {"status": "COMPLETE_WITH_MISSING" if incomplete else "COMPLETE",
               "completed_rows": completed, "incomplete_rows": incomplete,
               "planned_rows": 60, "last_entry_sha256": previous,
               "run_manifest_sha256": manifest_hash}
    _write_once(output_dir / "SUMMARY.json", summary)
    return summary


def verify_execution(output_dir: Path) -> dict[str, Any]:
    """Replay assignment, prompts, billing proof, decisions, and adapter policy."""
    output_dir = Path(output_dir)
    assignment_raw, assignment = _read_assignment(output_dir / "assignment_manifest.json")
    if sha256(assignment_raw).hexdigest() != ASSIGNMENT_SHA256:
        raise HandoffExecutionError("bundled assignment hash differs")
    manifest_raw = (output_dir / "run_manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    manifest_hash = sha256(manifest_raw).hexdigest()
    if (manifest.get("assignment_sha256") != ASSIGNMENT_SHA256
        or manifest.get("source_hashes") != _source_hashes()
        or manifest.get("planned_rows") != 60
        or manifest.get("rows_per_arm") != {"CONTACT": 30, "NO_CONTACT": 30}
        or manifest.get("model_execution_tier") not in {
            "SCRIPTED_TEST_DOUBLE", "REAL_REMOTE_ZERO_PRICE_IF_COMPLETED"}
        or manifest.get("payment_execution_tier") != "ARCHIVED_X402_A_ONLY_NO_NEW_NATIVE_PAYMENTS"
        or manifest.get("execution_tier") != "SCRIPTED_SIMULATION"
        or manifest.get("execution_tier_detail") != (
            "SCRIPTED_TEST_DOUBLE_WITH_ARCHIVED_X402_A" if
            manifest.get("model_execution_tier") == "SCRIPTED_TEST_DOUBLE" else
            "REMOTE_ZERO_PRICE_TEXT_WITH_ARCHIVED_X402_A")
        or manifest.get("max_retries") != 0):
        raise HandoffExecutionError("execution manifest differs from source")
    seal = study.sealed_evidence()
    entries = [json.loads(line) for line in (output_dir / "index.jsonl").read_text().splitlines()]
    if len(entries) > 60:
        raise HandoffExecutionError("index exceeds frozen denominator")
    previous = ZERO_LINK
    statuses = []
    last_after = None
    for assigned, entry in zip(assignment["rows"], entries):
        filename = assigned["episode_id"] + ".json"
        if (entry.get("episode_id") != assigned["episode_id"]
            or entry.get("row_file") != filename
            or entry.get("assignment_sha256") != ASSIGNMENT_SHA256
            or entry.get("run_manifest_sha256") != manifest_hash
            or entry.get("prev_entry_sha256") != previous):
            raise HandoffExecutionError("index assignment or chain link differs")
        body = {key: value for key, value in entry.items() if key != "entry_sha256"}
        if sha256(free.canonical(body)).hexdigest() != entry.get("entry_sha256"):
            raise HandoffExecutionError("index entry hash differs")
        row_bytes = (output_dir / filename).read_bytes()
        if sha256(row_bytes).hexdigest() != entry["row_sha256"]:
            raise HandoffExecutionError("row bytes differ from indexed hash")
        record = json.loads(row_bytes)
        if (record.get("row") != assigned
            or record.get("assignment_sha256") != ASSIGNMENT_SHA256
            or record.get("run_manifest_sha256") != manifest_hash
            or record.get("execution_tier") != manifest["execution_tier"]
            or record.get("execution_tier_detail") != manifest["execution_tier_detail"]
            or record.get("model_execution_tier") != manifest["model_execution_tier"]
            or record.get("transaction_execution_tier") != manifest["payment_execution_tier"]
            or record.get("status") not in {"COMPLETE", "INCOMPLETE", "STOPPED"}):
            raise HandoffExecutionError("row assignment or status differs")
        statuses.append(record["status"])
        calls = record.get("calls")
        if not isinstance(calls, list) or len(calls) > 3:
            raise HandoffExecutionError("row call count differs")
        if calls and calls[0].get("request") != study.provider_request(assigned, seal):
            raise HandoffExecutionError("recorded provider request differs from frozen prompt")
        if len(calls) >= 2:
            first_response = calls[0].get("response")
            if (not isinstance(first_response, Mapping)
                or first_response.get("finish_reason") != "stop"
                or not isinstance(first_response.get("text"), str)
                or not first_response["text"].strip()):
                raise HandoffExecutionError("auditor call lacks a completed provider message")
            expected_initial = study.auditor_initial_request(
                assigned, seal, first_response["text"] if assigned["arm"] == "CONTACT" else None)
            if calls[1].get("request") != expected_initial:
                raise HandoffExecutionError("recorded auditor exposure differs from frozen prompt")
        if len(calls) == 3:
            second_response = calls[1].get("response")
            if (not isinstance(second_response, Mapping)
                or second_response.get("finish_reason") != "stop"
                or not isinstance(second_response.get("text"), str)
                or not second_response["text"].strip()):
                raise HandoffExecutionError("check follow-up lacks a completed BUY choice")
            expected_followup = study.auditor_after_check_request(
                assigned, seal, expected_initial, second_response["text"])
            if calls[2].get("request") != expected_followup:
                raise HandoffExecutionError("recorded buyer check differs from frozen prompt")
        for number, call in enumerate(calls):
            request = call.get("request")
            if not isinstance(request, Mapping):
                raise HandoffExecutionError("recorded model request is absent")
            _assert_request_guard(request)
            if (request["model"] != (study.PROVIDER_MODEL if number == 0 else study.AUDITOR_MODEL)
                or call.get("request_sha256") != sha256(free.canonical(request)).hexdigest()):
                raise HandoffExecutionError("recorded model request hash differs")
            zero_proved = call.get("catalog_response_and_account_zero_price") is True
            if zero_proved and any(field not in call for field in (
                "price_proof", "selected_catalog_model", "account_usage_before_usd",
                "account_usage_after_usd", "account_usage_delta_usd", "response"
            )):
                raise HandoffExecutionError("zero-price call lacks catalog, response, or account evidence")
            if "price_proof" in call:
                model = call.get("selected_catalog_model")
                if (not isinstance(model, Mapping) or call["price_proof"] !=
                    free.assert_zero_price({"data": [model]}, request["model"])):
                    raise HandoffExecutionError("recorded catalog price proof differs")
            if "response" in call:
                response = call["response"]
                if (not isinstance(response, Mapping)
                    or set(response) != {"id", "model", "provider_id", "text",
                                          "finish_reason", "usage", "reported_reasoning_tokens"}
                    or not isinstance(response.get("usage"), Mapping)
                    or set(response["usage"]) != {"prompt_tokens", "completion_tokens",
                                                   "total_tokens", "cost"}):
                    raise HandoffExecutionError("recorded response contains unknown or hidden fields")
                if (response.get("model") != request["model"]
                    or (free._money(response.get("usage", {}).get("cost"), "recorded cost")
                        != free.ZERO and record["status"] != "STOPPED")):
                    raise HandoffExecutionError("recorded response price or model differs")
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = response["usage"].get(field)
                    if type(value) is not int or value < 0:
                        raise HandoffExecutionError("recorded token use differs")
                reasoning_tokens = response.get("reported_reasoning_tokens")
                if reasoning_tokens is not None and (
                    type(reasoning_tokens) is not int or reasoning_tokens < 0
                ):
                    raise HandoffExecutionError("recorded reasoning token count differs")
            if (record["status"] != "STOPPED" or number < len(calls) - 1) and (
                call.get("catalog_response_and_account_zero_price") is not True
            ):
                raise HandoffExecutionError("nonstopped call lacks zero-price evidence")
            before = call.get("account_usage_before_usd")
            after = call.get("account_usage_after_usd")
            if before is not None and last_after is not None and free._money(before, "before") != last_after:
                if not (record["status"] == "STOPPED" and number == len(calls) - 1
                        and call.get("preflight_failure") == "INTER_CALL_ACCOUNT_DELTA"
                        and call.get("preflight_error_type") == "HandoffExecutionError"
                        and "response" not in call):
                    raise HandoffExecutionError("account usage gap differs")
            if after is not None:
                if before is not None:
                    delta = free._money(after, "after") - free._money(before, "before")
                    try:
                        recorded_delta = Decimal(str(call.get("account_usage_delta_usd")))
                    except (InvalidOperation, ValueError) as exc:
                        raise HandoffExecutionError("recorded account delta is missing") from exc
                    if (not recorded_delta.is_finite() or delta != recorded_delta
                        or (zero_proved and delta != free.ZERO)):
                        raise HandoffExecutionError("recorded account cost differs")
                last_after = free._money(after, "after")
        if record["status"] == "COMPLETE":
            if any(call.get("catalog_response_and_account_zero_price") is not True
                   or call.get("response", {}).get("finish_reason") != "stop" for call in calls):
                raise HandoffExecutionError("complete row lacks finished zero-price calls")
            if _semantic_replay(assigned, seal, calls) != {
                "classification": record.get("classification"),
                "offline_handoff_replay": record.get("offline_handoff_replay")}:
                raise HandoffExecutionError("semantic decision or offline adapter replay differs")
        elif record["status"] == "INCOMPLETE":
            if record.get("incomplete_reason") != _expected_incomplete_reason(calls):
                raise HandoffExecutionError("recorded missingness differs from model response")
        previous = entry["entry_sha256"]
    terminal = output_dir / ("STOPPED.json" if (output_dir / "STOPPED.json").exists()
                              else "SUMMARY.json")
    if not terminal.exists():
        raise HandoffExecutionError("run has no terminal record")
    result = json.loads(terminal.read_bytes())
    if (result.get("last_entry_sha256") != previous
        or result.get("run_manifest_sha256") != manifest_hash
        or result.get("planned_rows") != 60
        or result.get("completed_rows") != statuses.count("COMPLETE")
        or result.get("incomplete_rows") != statuses.count("INCOMPLETE")):
        raise HandoffExecutionError("terminal counts or chain head differ")
    if result.get("status") == "STOPPED":
        if (not statuses or statuses[-1] != "STOPPED"
            or statuses.count("STOPPED") != 1
            or result.get("stopped_episode_id") != assignment["rows"][len(entries) - 1]["episode_id"]
            or result.get("remaining_rows_not_run") != 60 - len(entries)):
            raise HandoffExecutionError("STOPPED row or remaining count differs")
    elif result.get("status") in {"COMPLETE", "COMPLETE_WITH_MISSING"}:
        if (len(entries) != 60 or "STOPPED" in statuses
            or (result["status"] == "COMPLETE") != ("INCOMPLETE" not in statuses)):
            raise HandoffExecutionError("completed denominator or missing count differs")
    else:
        raise HandoffExecutionError("unknown terminal state")
    return {"status": result["status"], "verified_rows": len(entries),
            "planned_rows": 60, "last_entry_sha256": previous}
