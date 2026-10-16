"""One-attempt zero-price execution of a sealed AP2 audit-purchase assignment.

Signed AP2 scope is verified through the official local SDK before any model
call. Agent responses and the application settlement comparison are text and
scripted counterfactual evidence only; there is no PSP or new chain transfer.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping

from . import ap2_free_mandate_study as study
from . import free_collusion_probe as free


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_PATH = (ROOT / "artifacts/prospective/AP2_FREE_SCOPED_MANDATE/"
                   "assignment-002/assignment_manifest.json")
ZERO_LINK = "0" * 64


class AP2ExecutionError(RuntimeError):
    """A cost, AP2 scope, frozen prompt, or evidence check failed."""


class RowIncomplete(AP2ExecutionError):
    """A model call completed without a usable terminal decision."""


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise AP2ExecutionError("required source or assignment is absent or linked")
    return sha256(path.read_bytes()).hexdigest()


def _source_hashes() -> dict[str, str]:
    return {"ap2_study_sha256": _sha(Path(study.__file__)),
            "ap2_execution_sha256": _sha(Path(__file__)),
            "zero_price_transport_sha256": _sha(Path(free.__file__))}


def _read_assignment(path: Path, *, current: bool) -> tuple[bytes, dict[str, Any], str]:
    raw = Path(path).read_bytes()
    digest = sha256(raw).hexdigest()
    try:
        proof = study.verify_assignment(path, current=current)
    except Exception as exc:
        raise AP2ExecutionError("sealed AP2 assignment or signed scope failed") from exc
    if proof["assignment_sha256"] != digest:
        raise AP2ExecutionError("AP2 assignment bytes differ from verifier")
    return raw, json.loads(raw), digest


def dry_run(path: Path = ASSIGNMENT_PATH) -> dict[str, Any]:
    raw, assignment, digest = _read_assignment(path, current=False)
    del raw
    row = assignment["rows"][0]
    mandate = assignment["mandates"][row["row_id"]]
    records = assignment["buyer_records"][row["row_id"]]
    provider = study.build_request(row, mandate, records, "provider")
    auditor = study.build_request(row, mandate, records, "auditor_initial",
                                  "SUPPLIER_MESSAGE_PLACEHOLDER" if
                                  row["arm"].startswith("CONTACT") else None)
    return {"status": "READY_NO_MODEL_CALLS", "assignment_sha256": digest,
            "planned_pairs": len(assignment["rows"]),
            "bad_per_arm": study.BAD_PER_ARM, "good_per_arm": study.GOOD_PER_ARM,
            "provider_model": provider["model"], "auditor_model": auditor["model"],
            "reasoning_effort_requested": "high", "max_tokens": 4096,
            "ap2_signed_mandates_verified": len(assignment["rows"]),
            "new_ap2_payments": 0, "new_model_calls": 0}


def _write_bytes_once(path: Path, data: bytes) -> str:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    return sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    return _write_bytes_once(path, free.canonical(value) + b"\n")


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
        raise AP2ExecutionError("catalog data is missing")
    matches = [model for model in data if isinstance(model, Mapping)
               and model.get("id") == model_id]
    if len(matches) != 1:
        raise AP2ExecutionError("catalog exact model route is not unique")
    return json.loads(free.canonical(matches[0]))


def _assert_request(request: Mapping[str, Any]) -> None:
    if (request.get("model") not in free.MODELS
        or request.get("reasoning") != {"effort": "high"}
        or request.get("max_tokens") != 4096
        or request.get("stream") is not False
        or request.get("provider") != {"allow_fallbacks": False,
                                       "max_price": {"prompt": 0, "completion": 0,
                                                     "request": 0}}
        or len(free.canonical(request)) > free.MAX_REQUEST_BYTES):
        raise AP2ExecutionError("model request violates exact zero-price guard")


def _mask_content_only_defect(raw: Any, model_id: str) -> tuple[Any, bool]:
    """Defer a content defect until the exact-route and billing checks finish."""
    if not isinstance(raw, Mapping) or raw.get("model") != model_id:
        return raw, False
    choices = raw.get("choices")
    if (not isinstance(choices, list) or len(choices) != 1
        or not isinstance(choices[0], Mapping)):
        return raw, False
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return raw, False
    try:
        text = free._content(message.get("content"))
    except free.ProbeError:
        text = ""
    if text.strip():
        return raw, False
    # Save only a generic reason. Raw nontext content and hidden reasoning
    # cannot enter the evidence record through this path.
    clean = dict(raw)
    choice = dict(choices[0])
    choice["message"] = dict(message, content="")
    clean["choices"] = [choice]
    return clean, True


def _call(transport: Any, request: Mapping[str, Any], calls: list[dict[str, Any]],
          last_usage: list[Decimal | None]) -> str:
    """One POST maximum; fresh catalog, model, and account proof each time."""
    _assert_request(request)
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
            raise AP2ExecutionError("account usage changed between assigned calls")
    except Exception as exc:
        call["preflight_error_type"] = type(exc).__name__
        raise AP2ExecutionError("zero-price or billing preflight failed") from None
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
        raise AP2ExecutionError("model POST failed; billing may be unknown") from None
    call["completed_utc"] = free.utc_now()
    try:
        clean_raw, content_failure = _mask_content_only_defect(raw, request["model"])
        response = free.sanitize_response(clean_raw, request["model"])
        call["response"] = response
    except Exception as exc:
        call["response_parse_error_type"] = type(exc).__name__
        try:
            after_parse_failure = transport.usage()
            call["account_usage_after_usd"] = str(after_parse_failure)
            call["account_usage_delta_usd"] = str(after_parse_failure - before)
        except Exception as usage_exc:
            call["account_usage_after_error_type"] = type(usage_exc).__name__
        raise AP2ExecutionError("response cannot establish zero cost") from None
    try:
        after = transport.usage()
        cost = free._money(response["usage"]["cost"], "response cost")
    except Exception as exc:
        call["billing_check_error_type"] = type(exc).__name__
        raise AP2ExecutionError("account or response billing is unknown") from None
    call["account_usage_after_usd"] = str(after)
    call["account_usage_delta_usd"] = str(after - before)
    if cost != free.ZERO or after != before:
        raise AP2ExecutionError("positive or ambiguous model billing")
    last_usage[0] = after
    call["catalog_response_and_account_zero_price"] = True
    if content_failure:
        call["response_content_failure_reason"] = "MISSING_EMPTY_OR_NON_TEXT_CONTENT"
    if response["finish_reason"] != "stop":
        raise RowIncomplete("model response did not finish normally")
    if call.get("response_content_failure_reason"):
        raise RowIncomplete("model response has missing, empty, or non-text content")
    if not response["text"].strip():
        raise RowIncomplete("model response has no visible final text")
    return response["text"]


def _replay(row: Mapping[str, Any], mandate: Mapping[str, Any],
            buyer_records: Mapping[str, Any],
            calls: list[dict[str, Any]]) -> dict[str, Any]:
    if len(calls) not in {2, 3}:
        raise AP2ExecutionError("complete pair must have two or three calls")
    provider_request = study.build_request(row, mandate, buyer_records, "provider")
    if calls[0].get("request") != provider_request:
        raise AP2ExecutionError("provider exposure differs from frozen prompt")
    provider_text = calls[0]["response"]["text"]
    initial_request = study.build_request(
        row, mandate, buyer_records, "auditor_initial", provider_text if
        row["arm"].startswith("CONTACT") else None)
    if calls[1].get("request") != initial_request:
        raise AP2ExecutionError("auditor exposure differs from frozen prompt")
    initial_text = calls[1]["response"]["text"]
    check = study._field(initial_text, "CHECK", {"BUY", "SKIP"})
    initial = study._field(initial_text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
    final_text = None
    if check == "BUY" and initial == "HOLD":
        if len(calls) != 3:
            raise AP2ExecutionError("BUY/HOLD lacks authoritative buyer check")
        followup = study.build_request(
            row, mandate, buyer_records, "auditor_final", provider_text if
            row["arm"].startswith("CONTACT") else None, initial_text)
        if calls[2].get("request") != followup:
            raise AP2ExecutionError("buyer check continuation differs")
        final_text = calls[2]["response"]["text"]
    elif check == "SKIP" and initial in {"ACCEPT", "REJECT"}:
        if len(calls) != 2:
            raise AP2ExecutionError("SKIP decision has an extra model call")
    else:
        raise AP2ExecutionError("ambiguous auditor choice marked complete")
    labels = study.classify(row, buyer_records, provider_text, initial_text, final_text)
    verdict = labels["final_verdict_text"]
    if verdict not in {"ACCEPT", "REJECT"}:
        raise AP2ExecutionError("complete row lacks terminal verdict")
    return {"classification": labels,
            "offline_application_guard_replay": study.offline_guard_replay(
                row, buyer_records, verdict)}


def _incomplete_reason(calls: list[dict[str, Any]]) -> str:
    if not calls or not isinstance(calls[-1].get("response"), Mapping):
        raise AP2ExecutionError("incomplete row lacks model response")
    response = calls[-1]["response"]
    if response.get("finish_reason") != "stop":
        return "model response did not finish normally"
    if calls[-1].get("response_content_failure_reason"):
        return "model response has missing, empty, or non-text content"
    text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        return "model response has no visible final text"
    if len(calls) == 2:
        check = study._field(text, "CHECK", {"BUY", "SKIP"})
        verdict = study._field(text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
        if (check, verdict) not in {("BUY", "HOLD"), ("SKIP", "ACCEPT"),
                                    ("SKIP", "REJECT")}:
            return "initial check or verdict is ambiguous"
    if len(calls) == 3 and study._field(text, "VERDICT", {
        "ACCEPT", "REJECT"}) not in {"ACCEPT", "REJECT"}:
        return "auditor final verdict is ambiguous"
    raise AP2ExecutionError("incomplete row contains a scoreable decision")


def _live_key() -> str:
    if os.environ.get("ALLOW_AP2_FREE_MANDATE_CALLS", "false").lower() != "true":
        raise AP2ExecutionError("ALLOW_AP2_FREE_MANDATE_CALLS must be true")
    return free._validate_live_environment()


def execute(output_dir: Path, *, assignment_path: Path = ASSIGNMENT_PATH,
            transport: Any | None = None) -> dict[str, Any]:
    """Attempt assigned pairs once; a cost or technical failure stops globally."""
    raw, assignment, digest = _read_assignment(assignment_path, current=True)
    test_double = transport is not None and getattr(transport, "offline_test_double", False) is True
    if not test_double:
        key = _live_key()
        if transport is None:
            transport = free.OpenRouterTransport(key)
    sources = _source_hashes()
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_bytes_once(output_dir / "assignment_manifest.json", raw)
    manifest = {
        "schema": "ap2-free-scoped-mandate-run-v1", "created_utc": free.utc_now(),
        "assignment_sha256": digest, "source_hashes": sources,
        "planned_rows": len(assignment["rows"]),
        "bad_per_arm": study.BAD_PER_ARM, "good_per_arm": study.GOOD_PER_ARM,
        "model_execution_tier": ("SCRIPTED_TEST_DOUBLE" if test_double else
                                 "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED"),
        "transaction_execution_tier": "AP2_LOCAL_SIGNATURE_ONLY_NO_PSP_OR_TRANSFER",
        "max_retries": 0,
        "stop_rule": "First price, HTTP, response-cost, account, AP2 scope, or evidence failure stops remaining assignments. Missing, empty, non-text, truncated, or ambiguous content marks only that assigned row INCOMPLETE after zero-cost proof; no retry or replacement.",
        "billing_limit": "Immediate public catalog, reported response cost, and account usage are checked before and after each model call; delayed billing still needs later reconciliation.",
    }
    manifest_hash = _write_json(output_dir / "run_manifest.json", manifest)
    previous = ZERO_LINK
    completed = incomplete = 0
    last_usage: list[Decimal | None] = [None]
    for row in assignment["rows"]:
        mandate = assignment["mandates"][row["row_id"]]
        buyer_records = assignment["buyer_records"][row["row_id"]]
        record: dict[str, Any] = {
            "row": row, "assignment_sha256": digest,
            "run_manifest_sha256": manifest_hash,
            "model_execution_tier": manifest["model_execution_tier"],
            "transaction_execution_tier": manifest["transaction_execution_tier"],
            "started_utc": free.utc_now(), "status": "RUNNING", "calls": []}
        try:
            if _source_hashes() != sources or _sha(Path(assignment_path)) != digest:
                raise AP2ExecutionError("source or assignment changed during frozen run")
            # Verify the exact currently time-valid mandate immediately before
            # every pair, without treating it as an audit result or a payment.
            record["ap2_scope_check"] = study._verify_mandate(row, mandate, current=True)
            provider_text = _call(transport, study.build_request(
                row, mandate, buyer_records, "provider"), record["calls"], last_usage)
            exposed = provider_text if row["arm"].startswith("CONTACT") else None
            initial_text = _call(transport, study.build_request(
                row, mandate, buyer_records, "auditor_initial", exposed),
                record["calls"], last_usage)
            check = study._field(initial_text, "CHECK", {"BUY", "SKIP"})
            verdict = study._field(initial_text, "VERDICT", {"HOLD", "ACCEPT", "REJECT"})
            if check == "BUY" and verdict == "HOLD":
                final_text = _call(transport, study.build_request(
                    row, mandate, buyer_records, "auditor_final", exposed, initial_text),
                    record["calls"], last_usage)
                if study._field(final_text, "VERDICT", {"ACCEPT", "REJECT"}) not in {
                    "ACCEPT", "REJECT"}:
                    raise RowIncomplete("auditor final verdict is ambiguous")
            elif (check, verdict) not in {("SKIP", "ACCEPT"), ("SKIP", "REJECT")}:
                raise RowIncomplete("initial check or verdict is ambiguous")
            record.update(_replay(row, mandate, buyer_records, record["calls"]))
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
        filename = row["row_id"] + ".json"
        row_hash = _write_json(output_dir / filename, record)
        entry = {"row_id": row["row_id"], "row_file": filename,
                 "row_sha256": row_hash, "assignment_sha256": digest,
                 "run_manifest_sha256": manifest_hash,
                 "prev_entry_sha256": previous}
        entry["entry_sha256"] = sha256(free.canonical(entry)).hexdigest()
        _append_index(output_dir / "index.jsonl", entry)
        previous = entry["entry_sha256"]
        if record["status"] == "STOPPED":
            result = {"status": "STOPPED", "stopped_row_id": row["row_id"],
                      "stop_error_type": record["stop_error_type"],
                      "completed_rows": completed, "incomplete_rows": incomplete,
                      "planned_rows": len(assignment["rows"]),
                      "remaining_rows_not_run": len(assignment["rows"]) - completed - incomplete - 1,
                      "last_entry_sha256": previous,
                      "run_manifest_sha256": manifest_hash}
            _write_json(output_dir / "STOPPED.json", result)
            return result
    result = {"status": "COMPLETE_WITH_MISSING" if incomplete else "COMPLETE",
              "completed_rows": completed, "incomplete_rows": incomplete,
              "planned_rows": len(assignment["rows"]),
              "last_entry_sha256": previous, "run_manifest_sha256": manifest_hash}
    _write_json(output_dir / "SUMMARY.json", result)
    return result


def verify_execution(output_dir: Path) -> dict[str, Any]:
    """Replay assignment, exact exposure, reported zero cost, and hash chain."""
    output_dir = Path(output_dir)
    raw, assignment, digest = _read_assignment(
        output_dir / "assignment_manifest.json", current=False)
    del raw
    manifest_raw = (output_dir / "run_manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    manifest_hash = sha256(manifest_raw).hexdigest()
    if (manifest.get("schema") != "ap2-free-scoped-mandate-run-v1"
        or manifest.get("assignment_sha256") != digest
        or manifest.get("source_hashes") != _source_hashes()
        or manifest.get("planned_rows") != len(assignment["rows"])
        or manifest.get("bad_per_arm") != study.BAD_PER_ARM
        or manifest.get("good_per_arm") != study.GOOD_PER_ARM
        or manifest.get("model_execution_tier") not in {
            "SCRIPTED_TEST_DOUBLE", "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED"}
        or manifest.get("transaction_execution_tier") !=
           "AP2_LOCAL_SIGNATURE_ONLY_NO_PSP_OR_TRANSFER"
        or manifest.get("max_retries") != 0):
        raise AP2ExecutionError("run manifest differs from frozen study")
    entries = [json.loads(line) for line in
               (output_dir / "index.jsonl").read_text().splitlines()]
    if len(entries) > len(assignment["rows"]):
        raise AP2ExecutionError("index exceeds frozen denominator")
    previous = ZERO_LINK
    statuses = Counter()
    last_after = None
    for assigned, entry in zip(assignment["rows"], entries):
        filename = assigned["row_id"] + ".json"
        if (entry.get("row_id") != assigned["row_id"]
            or entry.get("row_file") != filename
            or entry.get("assignment_sha256") != digest
            or entry.get("run_manifest_sha256") != manifest_hash
            or entry.get("prev_entry_sha256") != previous):
            raise AP2ExecutionError("index row or link differs")
        body = {k: v for k, v in entry.items() if k != "entry_sha256"}
        if sha256(free.canonical(body)).hexdigest() != entry.get("entry_sha256"):
            raise AP2ExecutionError("index entry hash differs")
        row_bytes = (output_dir / filename).read_bytes()
        if sha256(row_bytes).hexdigest() != entry.get("row_sha256"):
            raise AP2ExecutionError("row bytes differ from indexed digest")
        record = json.loads(row_bytes)
        if (record.get("row") != assigned
            or record.get("assignment_sha256") != digest
            or record.get("run_manifest_sha256") != manifest_hash
            or record.get("model_execution_tier") != manifest["model_execution_tier"]
            or record.get("transaction_execution_tier") != manifest["transaction_execution_tier"]
            or record.get("status") not in {"COMPLETE", "INCOMPLETE", "STOPPED"}):
            raise AP2ExecutionError("row assignment or terminal status differs")
        statuses[record["status"]] += 1
        mandate = assignment["mandates"][assigned["row_id"]]
        buyer_records = assignment["buyer_records"][assigned["row_id"]]
        calls = record.get("calls")
        if calls and record.get("ap2_scope_check") is None:
            raise AP2ExecutionError("model call lacks prior AP2 signed-scope check")
        if record.get("ap2_scope_check") is not None and record["ap2_scope_check"] != (
            study._verify_mandate(assigned, mandate, current=False)):
            raise AP2ExecutionError("recorded AP2 scope result differs")
        if not isinstance(calls, list) or len(calls) > 3:
            raise AP2ExecutionError("row call count differs")
        if calls and calls[0].get("request") != study.build_request(
            assigned, mandate, buyer_records, "provider"):
            raise AP2ExecutionError("provider prompt differs")
        if len(calls) >= 2:
            first_response = calls[0].get("response")
            if not isinstance(first_response, Mapping) or (
                first_response.get("finish_reason") != "stop"
            ) or not isinstance(first_response.get("text"), str) or not first_response["text"].strip():
                raise AP2ExecutionError("auditor call lacks complete supplier text")
            expected_initial = study.build_request(
                assigned, mandate, buyer_records, "auditor_initial", first_response["text"] if
                assigned["arm"].startswith("CONTACT") else None)
            if calls[1].get("request") != expected_initial:
                raise AP2ExecutionError("auditor exposure differs")
        if len(calls) == 3:
            second_response = calls[1].get("response")
            if not isinstance(second_response, Mapping) or (
                second_response.get("finish_reason") != "stop"
            ) or not isinstance(second_response.get("text"), str) or not second_response["text"].strip():
                raise AP2ExecutionError("BUY continuation lacks complete choice")
            followup = study.build_request(
                assigned, mandate, buyer_records, "auditor_final", first_response["text"] if
                assigned["arm"].startswith("CONTACT") else None, second_response["text"])
            if calls[2].get("request") != followup:
                raise AP2ExecutionError("authoritative check continuation differs")
        for number, call in enumerate(calls):
            request = call.get("request")
            if not isinstance(request, Mapping):
                raise AP2ExecutionError("model request is absent")
            _assert_request(request)
            if (request["model"] != (study.base.PROVIDER_MODEL if number == 0 else
                                      study.base.AUDITOR_MODEL)
                or call.get("request_sha256") != sha256(free.canonical(request)).hexdigest()):
                raise AP2ExecutionError("model route or request digest differs")
            if "price_proof" in call:
                model = call.get("selected_catalog_model")
                if not isinstance(model, Mapping) or call["price_proof"] != (
                    free.assert_zero_price({"data": [model]}, request["model"])):
                    raise AP2ExecutionError("catalog zero-price proof differs")
            if "response" in call:
                response = call["response"]
                if (not isinstance(response, Mapping)
                    or set(response) != {"id", "model", "provider_id", "text",
                                             "finish_reason", "usage", "reported_reasoning_tokens"}
                    or response.get("model") != request["model"]
                    or not isinstance(response.get("usage"), Mapping)
                    or set(response["usage"]) != {"prompt_tokens", "completion_tokens",
                                                   "total_tokens", "cost"}):
                    raise AP2ExecutionError("recorded response schema differs")
                cost = free._money(response["usage"]["cost"], "recorded cost")
                if cost != free.ZERO and record["status"] != "STOPPED":
                    raise AP2ExecutionError("nonstopped response has positive cost")
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if type(response["usage"][field]) is not int or response["usage"][field] < 0:
                        raise AP2ExecutionError("recorded token count differs")
                reasoning = response["reported_reasoning_tokens"]
                if reasoning is not None and (type(reasoning) is not int or reasoning < 0):
                    raise AP2ExecutionError("reported reasoning count differs")
            proved = call.get("catalog_response_and_account_zero_price") is True
            content_failure = call.get("response_content_failure_reason")
            if content_failure is not None and (
                content_failure != "MISSING_EMPTY_OR_NON_TEXT_CONTENT"
                or not isinstance(call.get("response"), Mapping)
                or call["response"].get("text") != ""
                or not proved):
                raise AP2ExecutionError("content-only failure lacks zero-cost proof")
            if (record["status"] != "STOPPED" or number < len(calls) - 1) and not proved:
                raise AP2ExecutionError("nonstopped call lacks zero-cost proof")
            if proved and any(field not in call for field in (
                "price_proof", "selected_catalog_model", "response",
                "account_usage_before_usd", "account_usage_after_usd",
                "account_usage_delta_usd")):
                raise AP2ExecutionError("zero-cost proof lacks billing fields")
            before = call.get("account_usage_before_usd")
            after = call.get("account_usage_after_usd")
            if before is not None and last_after is not None and (
                free._money(before, "before") != last_after):
                if not (record["status"] == "STOPPED" and number == len(calls) - 1
                        and call.get("preflight_failure") == "INTER_CALL_ACCOUNT_DELTA"
                        and "response" not in call):
                    raise AP2ExecutionError("inter-call account usage gap differs")
            if after is not None:
                if before is not None:
                    delta = free._money(after, "after") - free._money(before, "before")
                    try:
                        stored_delta = Decimal(str(call.get("account_usage_delta_usd")))
                    except (InvalidOperation, ValueError) as exc:
                        raise AP2ExecutionError("recorded billing delta absent") from exc
                    if not stored_delta.is_finite() or stored_delta != delta or (
                        proved and delta != free.ZERO):
                        raise AP2ExecutionError("recorded account delta differs")
                last_after = free._money(after, "after")
        if record["status"] == "COMPLETE":
            if any(call.get("catalog_response_and_account_zero_price") is not True or
                   call.get("response", {}).get("finish_reason") != "stop" or
                   call.get("response_content_failure_reason") for call in calls):
                raise AP2ExecutionError("complete row lacks finished free calls")
            if _replay(assigned, mandate, buyer_records, calls) != {
                "classification": record.get("classification"),
                "offline_application_guard_replay": record.get("offline_application_guard_replay")
            }:
                raise AP2ExecutionError("semantic classification or guard replay differs")
        elif record["status"] == "INCOMPLETE":
            if record.get("incomplete_reason") != _incomplete_reason(calls):
                raise AP2ExecutionError("incomplete reason differs from saved model text")
        previous = entry["entry_sha256"]
    terminal = output_dir / ("STOPPED.json" if (output_dir / "STOPPED.json").exists()
                              else "SUMMARY.json")
    if not terminal.is_file():
        raise AP2ExecutionError("run has no terminal record")
    result = json.loads(terminal.read_bytes())
    if (result.get("last_entry_sha256") != previous
        or result.get("run_manifest_sha256") != manifest_hash
        or result.get("planned_rows") != len(assignment["rows"])
        or result.get("completed_rows") != statuses["COMPLETE"]
        or result.get("incomplete_rows") != statuses["INCOMPLETE"]):
        raise AP2ExecutionError("terminal counts or chain head differ")
    if result["status"] == "STOPPED":
        if (not entries or statuses["STOPPED"] != 1
            or json.loads((output_dir / entries[-1]["row_file"]).read_bytes())["status"] !=
               "STOPPED"
            or result.get("stopped_row_id") != assignment["rows"][len(entries)-1]["row_id"]
            or result.get("remaining_rows_not_run") != len(assignment["rows"]) - len(entries)):
            raise AP2ExecutionError("STOPPED placement or denominator differs")
    elif result["status"] in {"COMPLETE", "COMPLETE_WITH_MISSING"}:
        if (len(entries) != len(assignment["rows"]) or statuses["STOPPED"]
            or (result["status"] == "COMPLETE") != (statuses["INCOMPLETE"] == 0)):
            raise AP2ExecutionError("completed denominator or missingness differs")
    else:
        raise AP2ExecutionError("terminal status is unknown")
    return {"status": result["status"], "verified_rows": len(entries),
            "planned_rows": len(assignment["rows"]), "last_entry_sha256": previous,
            "assignment_sha256": digest}
