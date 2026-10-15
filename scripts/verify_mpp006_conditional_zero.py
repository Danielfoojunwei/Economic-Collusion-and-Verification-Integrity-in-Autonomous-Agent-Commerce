#!/usr/bin/env python3
"""Read-only, offline MPP006 billing reconciliation. Never settles a ledger.

The conclusion is deliberately conditional: the exports do not contain a
per-request invoice for the stopped HTTP 400 request.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
from html.parser import HTMLParser
import json
from decimal import Decimal
from pathlib import Path
import sys

from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.remote_budget import read_ledger  # noqa: E402
from verify_mpp006_provider_export import verify as verify_provider_export  # noqa: E402

BASE = ROOT / "artifacts/budget/provider-reconciliation-mpp006-001"
EVIDENCE = BASE / "conditional-zero-asof-001"
GATE = ROOT / "artifacts/gates/MPP006"
EPISODE_ID = "mpp006-bc092a2baae1584874c4f308"
RUN_ID = "mpp006-0e11d0595056-" + EPISODE_ID
EXPECTED = {
    "assignment_manifest.json": "0e11d0595056d5d43037a666be1767c3ddc394b2a7914d4ab9cb7e3a97362d9f",
    "STOPPED.json": "afe3648e287db7cc3f05a87417ea6852969ae222dd043b26493854b983746745",
    "inspect.eval": "d401ec9e8f4901679949d01a8e68a667072992f3d159cad838720927c8505a86",
    "collection-mixed-001-after-first-stop.json": "e6a323ac4c49382c96860693e43c954a6ddd251d4421db75496eeca561670f52",
    "prestate-openrouter-ledger.jsonl": "e5067415a2abfd589cfa9c3073e8dedcc0cbc25ce2af4635978fea7c3486b440",
    "prestate-openrouter-ledger.jsonl.anchor": "c77675a2510594e4c9eac42becd5abc6c01e135cfad2f313e39969f0aa1067b7",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned(path: Path, label: str) -> bytes:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED[label]:
        raise ValueError(f"archived {label} bytes differ from the pinned SHA-256")
    return raw


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skipped = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer"}:
            self.skipped += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer"} and self.skipped:
            self.skipped -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipped:
            self.parts.append(data)


def official_docs() -> dict:
    metadata = json.loads((EVIDENCE / "official-docs.json").read_text())
    required = {
        "errors-and-debugging": ("Pre-stream errors", "before any tokens are sent"),
        "zero-completion-insurance": (
            "zero completion insurance", "you will not be charged for the model’s token usage",
            "does not cover charges for auxiliary services",
        ),
        "activity-export": ("aggregated usage data", "sub-grouped by minute, hour, day, and month"),
    }
    if set(metadata) != set(required):
        raise ValueError("official source list differs")
    for name, terms in required.items():
        item = metadata[name]
        if item["http_status"] != 200 or item["url"].split("/")[2] != "openrouter.ai":
            raise ValueError(f"official source HTTP/domain differs: {name}")
        compressed = (EVIDENCE / item["archive_file"]).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != item["archive_sha256"]:
            raise ValueError(f"archived source gzip differs: {name}")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != item["page_sha256"]:
            raise ValueError(f"archived source page differs: {name}")
        visible = _VisibleText()
        visible.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(visible.parts).split()).lower()
        if any(term.lower() not in text for term in terms):
            raise ValueError(f"official source passage absent: {name}")
    return {name: {"url": item["url"], "http_status": 200,
                   "retrieved_at_utc": item["retrieved_at_utc"],
                   "page_sha256": item["page_sha256"]}
            for name, item in metadata.items()}


def serialized_request(error_message: str) -> dict:
    if not error_message.startswith("ModelGenerateError("):
        raise ValueError("Inspect has a different error envelope")
    content = ast.literal_eval(error_message[len("ModelGenerateError("):-1])
    marker = "Request:\n"
    if marker not in content:
        raise ValueError("Inspect has no serialized request")
    obj, _ = json.JSONDecoder().raw_decode(content[content.index(marker) + len(marker):])
    if not all(s in content for s in (
        "Error code: 400", "invalid_function_parameters", "market_propose", "Missing",
    )):
        raise ValueError("the saved failure is not the archived tool-schema HTTP 400")
    return obj


def verify() -> dict:
    provider = verify_provider_export()
    if provider["result"] != "INCONCLUSIVE_FOR_EXACT_CHARGE":
        raise ValueError("provider-export interpretation changed")
    if (provider["provider_13h_request_count"] != 46 or
            provider["provider_13h_total_usd"] != "0.269499" or
            provider["stopped_episode"]["session_absent_from_provider_csv"] is not True):
        raise ValueError("13:00 UTC reconciliation changed")

    manifest_raw = pinned(GATE / "assignment-mixed-001/assignment_manifest.json", "assignment_manifest.json")
    manifest = json.loads(manifest_raw)
    pricing = manifest["public_pricing_snapshots"]["openai/gpt-5.6-sol"]
    if (pricing["request_usd"] != "0" or
            pricing["catalog_model_sha256"] != "71e95fa7cf157390232d6e13a44bf61ea6b9b6a7961ced6c8f37a684b51b499a" or
            pricing["source_url"] != "https://openrouter.ai/api/v1/models"):
        raise ValueError("public per-request pricing snapshot changed")

    episode = GATE / "runs-mixed-001/episodes" / EPISODE_ID
    stopped = json.loads(pinned(episode / "STOPPED.json", "STOPPED.json"))
    pinned(episode / "inspect.eval", "inspect.eval")
    log = read_eval_log(str(episode / "inspect.eval"))
    if len(log.samples or []) != 1:
        raise ValueError("saved failed Inspect log has unexpected samples")
    sample = log.samples[0]
    request = serialized_request(log.error.message)
    tools = [item["function"]["name"] for item in request["tools"]]
    if (sample.model_usage or any(m.role == "assistant" for m in sample.messages)
            or request["model"] != "openai/gpt-5.6-sol"
            or sorted(tools) != ["market_accept", "market_propose", "market_view", "select_mpp_flow"]
            or request.get("extra_body", {}).get("reasoning", {}).get("effort") != "high"
            or stopped["model_calls_attempted"] != 1
            or stopped["budget_state"] != "UNKNOWN"
            or stopped["ledger_run_id"] != RUN_ID
            or stopped["complete_payment_claim"] is not False):
        raise ValueError("stopped sample, request, or payment status changed")
    collection = json.loads(pinned(GATE / "collection-mixed-001-after-first-stop.json",
                                   "collection-mixed-001-after-first-stop.json"))
    statuses = [row["status"] for row in collection["rows"]]
    if (statuses.count("COMPLETE"), statuses.count("STOPPED"), statuses.count("PENDING")) != (1, 1, 6):
        raise ValueError("frozen denominator changed")

    ledger_path = EVIDENCE / "prestate-openrouter-ledger.jsonl"
    pinned(ledger_path, "prestate-openrouter-ledger.jsonl")
    pinned(EVIDENCE / "prestate-openrouter-ledger.jsonl.anchor",
           "prestate-openrouter-ledger.jsonl.anchor")
    ledger = read_ledger(ledger_path)
    run = ledger["runs"][RUN_ID]
    if (ledger["seq"] != 132 or ledger["cap_usd"] != "50" or
            ledger["blocked"] is not True or
            ledger["unknown_run_ids"] != [RUN_ID] or
            run["status"] != "UNKNOWN" or
            run["reserved_usd"] != "6.30784"):
        raise ValueError("archived prestate ledger differs")

    docs = official_docs()
    account = provider["account_usage_observation"]
    if Decimal(account["aggregate_above_csv_usd_rounded_7dp"]) != Decimal("0.0000342"):
        raise ValueError("read-only key aggregate residual changed")
    if Decimal(account["usage_usd"]) != Decimal("2.1870442"):
        raise ValueError("read-only key aggregate changed")

    return {
        "schema": "mpp006-conditional-zero-asof-export-v1",
        "result": "CONDITIONAL_ZERO_MODEL_INFERENCE_AS_OF_OBSERVATION_NOT_INVOICED",
        "conditions": [
            "The owner exports cover this API key and the 13:00 UTC hour without omitted billable sessions.",
            "OpenRouter's published zero-completion insurance applies to this HTTP 400 schema failure.",
            "No delayed or auxiliary charge for this failed request is later posted.",
        ],
        "owner_csv_sha256": {
            "session": provider["provider_csv_sha256"],
            "model_count": provider["provider_model_count_csv_sha256"],
            "model_usage": provider["provider_model_usage_csv_sha256"],
        },
        "recorded_13h_requests": 46,
        "recorded_13h_spend_usd": "0.269499",
        "stopped_sample_uuid": sample.uuid,
        "stopped_http_status": 400,
        "stopped_provider_error_code": "invalid_function_parameters",
        "stopped_sample_has_model_usage": False,
        "stopped_sample_has_model_response": False,
        "serialized_request_model": request["model"],
        "serialized_request_tool_names": tools,
        "serialized_request_has_auxiliary_web_or_file_service": False,
        "stopped_session_in_provider_export": False,
        "public_pricing_request_usd": pricing["request_usd"],
        "public_pricing_assignment_manifest_sha256": EXPECTED["assignment_manifest.json"],
        "public_pricing_fetched_utc": pricing["fetched_utc"],
        "public_catalog_model_sha256": pricing["catalog_model_sha256"],
        "key_aggregate_usd": account["usage_usd"],
        "key_aggregate_observed_after_utc": account["observed_after_utc"],
        "session_csv_total_usd": provider["provider_csv_total_usd_rounded_6dp"],
        "unattributed_key_above_csv_usd": account["aggregate_above_csv_usd_rounded_7dp"],
        "per_request_invoice_available": False,
        "actual_final_total_failed_request_usd": None,
        "conditional_model_inference_charge_usd": "0",
        "contingent_budget_exposure_usd": run["reserved_usd"],
        "ledger_prestate": {
            "seq": ledger["seq"], "blocked": ledger["blocked"],
            "cap_usd": ledger["cap_usd"],
            "settled_spent_usd": ledger["settled_spent_usd"],
            "reserved_usd": ledger["reserved_usd"],
            "unknown_run_ids": ledger["unknown_run_ids"],
            "ledger_sha256": EXPECTED["prestate-openrouter-ledger.jsonl"],
            "anchor_sha256": EXPECTED["prestate-openrouter-ledger.jsonl.anchor"],
        },
        "frozen_collection_sha256": EXPECTED["collection-mixed-001-after-first-stop.json"],
        "frozen_collection_status_counts": {"COMPLETE": 1, "STOPPED": 1, "PENDING": 6},
        "official_docs": docs,
        "ledger_mutations": 0,
        "paid_model_calls": 0,
        "settlement_requires_independent_review": True,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True, indent=2))
