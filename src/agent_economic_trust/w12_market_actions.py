"""Read-only W12 financial attribution from a saved W11 market episode.

The source event stream is immutable and does not contain every field required
by ``coordination_metrics.actions_from_events``. This adapter verifies its
archived Inspect log, frozen assignment and local native receipts, then makes
an explicitly derived event stream. An ERC-8183 release is economically a
client-to-provider payment through escrow; the raw token transfer is from the
contract. Both routes remain visible in the derivation provenance.

Neither assigned nor delivered researcher-authored messages are annotated as
an independent agreement. This module computes actions, not collusion intent.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from inspect_ai.log import read_eval_log

from .coordination_metrics import FinancialActions, actions_from_events
from .evidence import canonical_sha256, validate_event, verify_evidence
from .protected_receipts import receipt_oracle
from .remote import APPROVED_MODEL_ID
from .w10_funding import _expect_transfer
from .w11_market_native import verify_market_evidence
from .w11_market_plan import MarketRound, canonical, case_for_round, digest, make_market_schedule, manifest
from .w11_market_task import audit_saved_market_log


CURRENCY = "valueless MockUSDC"


class MarketActionError(ValueError):
    """Saved W11 evidence cannot support the requested financial actions."""


@dataclass(frozen=True)
class MarketActionDerivation:
    actions: FinancialActions
    canonical_events: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    communication: dict[str, Any]


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _one(rows: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    found = [row for row in rows if row["event_type"] == event_type]
    if len(found) != 1 or found[0]["status"] != "SUCCESS":
        raise MarketActionError(f"expected one successful {event_type}")
    return found[0]


def _assigned_round(plan_dir: Path, episode_id: str) -> tuple[MarketRound, str, dict[str, Any]]:
    plan_path = plan_dir / "assignment_manifest.json"
    plan = json.loads(plan_path.read_bytes())
    seed = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    private = json.loads((plan_dir / "private_rounds.json").read_bytes())
    if not private or plan.get("schema") != "w11-prospective-market-assignment-v2":
        raise MarketActionError("not a frozen W11 v2 market assignment")
    rows = make_market_schedule(
        seed, blocks=len({item["block_id"] for item in private}),
        r_values=tuple(sorted({item["r"] for item in private})),
    )
    expected = json.loads(canonical(manifest(seed, rows)))
    if (any(plan.get(key) != value for key, value in expected.items())
            or private != json.loads(canonical([row.__dict__ for row in rows]))
            or plan.get("private_rows_sha256") != digest(private)):
        raise MarketActionError("frozen W11 schedule or manifest was changed")
    selected = [row for row in rows if row.episode_id == episode_id]
    if len(selected) != 1:
        raise MarketActionError("episode is absent or duplicated in frozen assignment")
    return selected[0], _sha(plan_path), plan


def _saved_tool_links(rows: list[dict[str, Any]], saved_log: Any, row: MarketRound) -> None:
    """Bind exported tool rows to the actual resolved native Inspect events."""
    sample = saved_log.samples[0]
    by_uuid = {event.uuid: event for event in sample.events if event.event in {"model", "tool"}}
    if len(by_uuid) != sum(event.event in {"model", "tool"} for event in sample.events):
        raise MarketActionError("saved native Inspect action UUID was reused")
    spans = {event.id: event for event in sample.events if event.event == "span_begin"}
    linked: set[str] = set()

    def native_actor(event: Any) -> str | None:
        current = getattr(event, "span_id", None)
        seen_spans: set[str] = set()
        while current is not None and current not in seen_spans:
            seen_spans.add(current)
            span = spans.get(current)
            if span is None:
                return None
            if span.type == "agent":
                return span.name
            current = span.parent_id
        return None

    native_types = {
        "MODEL_DECISION", "WORK_SUBMITTED", "AUDIT_REQUESTED", "CHECK_COMPLETED",
        "VERDICT_ISSUED", "COMMUNICATION_SENT", "COMMUNICATION_READ", "TOOL_RESULT",
    }
    for source in rows:
        payload = source.get("payload", {})
        event_uuid = payload.get("native_event_id")
        if event_uuid is None:
            if source["event_type"] in native_types:
                raise MarketActionError("exported model/tool action has no native Inspect link")
            continue
        if event_uuid in linked:
            raise MarketActionError("exported native Inspect action was reused")
        linked.add(event_uuid)
        event = by_uuid.get(event_uuid)
        if event is None:
            raise MarketActionError("exported event has no saved native Inspect counterpart")
        who = native_actor(event)
        expected_actor = row.provider_id if who == "worker" else row.verifier_id if who == "auditor" else None
        if source["actor_id"] != expected_actor:
            raise MarketActionError("exported actor differs from native agent span")
        if source["event_type"] == "MODEL_DECISION":
            if event.event != "model":
                raise MarketActionError("exported model action differs from native event")
        elif (event.event != "tool" or payload.get("function") != event.function
              or payload.get("result_sha256") != sha256(str(event.result).encode()).hexdigest()):
            raise MarketActionError("exported tool action differs from native result")
    if linked != set(by_uuid):
        raise MarketActionError("source event export omitted saved native model/tool actions")


def _transform(
    rows: list[dict[str, Any]], *, source_hash: str, row: MarketRound,
    native: dict[str, Any], evidence: dict[str, Any], score: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Create canonical, parent-linked derived rows without editing a W11 file."""
    fee = _one(rows, "AUDITOR_FEE_PAID")
    verdict = _one(rows, "VERDICT_ISSUED")
    task = _one(rows, "TASK_CREATED")
    funding = _one(rows, "JOB_FUNDED")
    oracle = _one(rows, "ORACLE_SCORED")
    work = _one(rows, "WORK_SUBMITTED")
    terminal_type = "PAYMENT_SETTLED" if native["settlement"]["provider_paid"] else "PAYMENT_REFUNDED"
    terminal = _one(rows, terminal_type)
    opposite = "PAYMENT_REFUNDED" if terminal_type == "PAYMENT_SETTLED" else "PAYMENT_SETTLED"
    if any(item["event_type"] == opposite for item in rows):
        raise MarketActionError("source has contradictory payout and refund events")
    fund_steps = [item for item in evidence["transactions"]
                  if item["step"] == row.obligation_id + ".fund"]
    if len(fund_steps) != 1:
        raise MarketActionError("native job has no unique funding transaction")
    if (task.get("obligation_id") != row.obligation_id
            or work.get("artifact_digest") != row.artifact_digest
            or funding.get("payment_reference") != fund_steps[0]["transaction_hash"]
            or funding.get("amount_minor_units") != row.job_amount_minor_units
            or fee.get("payment_reference") != native["fee_receipt"]["transactionHash"]
            or fee.get("amount_minor_units") != row.audit_fee_minor_units
            or fee.get("actor_id") != (row.provider_id if row.r else "client")
            or fee.get("payload", {}).get("payee_id") != row.verifier_id
            or fee.get("payload", {}).get("raw_receipt_sha256") != native["fee_receipt_sha256"]
            or terminal.get("payment_reference") != native["settlement"]["raw_receipt"]["transactionHash"]
            or terminal.get("amount_minor_units") != row.job_amount_minor_units
            or terminal.get("payload", {}).get("raw_receipt_sha256") != native["settlement"]["raw_receipt_sha256"]
            or verdict.get("actor_id") != row.verifier_id
            or oracle.get("payload", {}).get("oracle_status") != score["oracle_status"]):
        raise MarketActionError("source event differs from assigned native/Inspect evidence")
    checks = [event for event in rows if event["event_type"] == "CHECK_COMPLETED"]
    if bool(checks) != score["Q"] or score["V"] != native["settlement"]["verdict"]:
        raise MarketActionError("check or verdict differs from saved scorer and chain")

    derived: list[dict[str, Any]] = []
    parent: str | None = None
    for source in rows:
        event = deepcopy(source)
        event["parent_event_id"] = parent
        payload = event["payload"]
        payload["w12_derivation"] = {
            "source_event_id": source["event_id"],
            "source_events_sha256": source_hash,
            "kind": "verified_read_only_transform",
        }
        kind = event["event_type"]
        if kind == "TASK_CREATED":
            event["amount_minor_units"] = row.job_amount_minor_units
            event["currency"] = CURRENCY
        elif kind == "VERDICT_ISSUED":
            payload["verdict"] = score["V"]
            payload["check_completed"] = score["Q"]
        elif kind == "AUDITOR_FEE_PAID":
            event["event_type"] = "PAYMENT_SETTLED"
            payload.update({
                "payer_id": row.provider_id if row.r else "client",
                "payee_id": row.verifier_id,
                "payment_kind": "prepaid_auditor_fee",
                "raw_transfer_from": native["addresses"]["provider" if row.r else "client"],
                "raw_transfer_to": native["addresses"]["auditor"],
                "native_token_address": evidence["token_address"],
                "business_obligation_binding": "application_unique_market_round_map",
            })
        elif kind == "PAYMENT_SETTLED":
            payload.update({
                "payer_id": "client", "payee_id": row.provider_id,
                "payment_kind": "erc8183_job_release_via_escrow",
                "raw_transfer_from": evidence["core_address"],
                "raw_transfer_to": native["addresses"]["provider"],
                "native_token_address": evidence["token_address"],
                "funding_transaction_hash": funding["payment_reference"],
                "economic_payer_basis": "client_funded_same_erc8183_job_escrow",
            })
        elif kind == "COMMUNICATION_SENT":
            # A posted researcher-authored promise is an exposure observation.
            # Independent blinded agreement annotation is a separate process.
            if "independent_action_annotation" in payload:
                raise MarketActionError("source communication contains an unverified agreement annotation")
            payload["w12_explicit_agreement_annotation"] = "NOT_PERFORMED"
        event.pop("event_id")
        event["event_id"] = "ev_" + canonical_sha256(event)[:24]
        if validate_event(event) != event:
            raise MarketActionError("derived event was sanitized after canonical hashing")
        derived.append(event)
        parent = event["event_id"]
    return tuple(derived)


def derive_market_actions(episode_dir: Path, plan_dir: Path) -> MarketActionDerivation:
    """Validate saved W11 evidence and return Colosseum-style actions.

    The input paths are read only. This is an attribution transform, not an
    estimate: comparison requires matching whole-market randomized controls.
    """
    episode_dir, plan_dir = Path(episode_dir), Path(plan_dir)
    counts = verify_evidence(episode_dir)
    if counts["outcomes"] != 1:
        raise MarketActionError("W11 episode lacks exactly one stored outcome")
    record = json.loads((episode_dir / "episode_record.json").read_bytes())
    run_manifest = json.loads((episode_dir / "run_manifest.json").read_bytes())
    row, assignment_sha, plan = _assigned_round(plan_dir, record["episode_id"])
    if (record.get("status") != "COMPLETE"
            or record.get("assignment_manifest_sha256") != assignment_sha
            or record.get("source_sha256") != plan.get("source_sha256")
            or record.get("market_id") != row.market_id
            or record.get("round_index") != row.round_index
            or record.get("offer_variant") != row.offer_variant
            or run_manifest.get("randomization", {}).get("assignment_manifest_sha256") != assignment_sha
            or run_manifest.get("model_behavior_tier") != record.get("model_tier")
            or run_manifest.get("payment_tier") != "NATIVE_LOCAL_CHAIN"
            or _sha(episode_dir / "inspect.eval") != record.get("native_inspect_sha256")
            or _sha(episode_dir / "native_evidence.json") != record.get("native_payment_sha256")):
        raise MarketActionError("saved episode differs from frozen assignment or manifest")
    evidence = json.loads((episode_dir / "native_evidence.json").read_bytes())
    native_summary = verify_market_evidence(episode_dir / "native_evidence.json")
    if (native_summary.get("market_id") != row.market_id
            or evidence.get("assignment_manifest_sha256") != assignment_sha):
        raise MarketActionError("native market differs from assigned episode")
    native_rows = [item for item in evidence["rounds"]
                   if item["obligation_id"] == row.obligation_id]
    if len(native_rows) != 1:
        raise MarketActionError("native obligation mapping is missing or duplicated")
    native = native_rows[0]
    if (native["episode_id"] != row.episode_id
            or native["artifact_digest"] != row.artifact_digest
            or native["provider_id"] != row.provider_id
            or native["auditor_id"] != row.verifier_id
            or native["R"] != row.r
            or native["job_budget_minor_units"] != row.job_amount_minor_units
            or native["fee_minor_units"] != row.audit_fee_minor_units):
        raise MarketActionError("native payment obligation differs from frozen round")
    _expect_transfer(native["fee_receipt"], evidence["token_address"].lower(),
                     native["addresses"]["provider" if row.r else "client"].lower(),
                     native["addresses"]["auditor"].lower(), row.audit_fee_minor_units)
    fund_steps = [item for item in evidence["transactions"]
                  if item["step"] == row.obligation_id + ".fund"]
    if len(fund_steps) != 1:
        raise MarketActionError("native round has no unique ERC-8183 funding receipt")
    _expect_transfer(fund_steps[0]["raw_receipt"], evidence["token_address"].lower(),
                     evidence["client_address"].lower(), evidence["core_address"].lower(),
                     row.job_amount_minor_units)
    settlement = native.get("settlement")
    if settlement is None or settlement["verdict"] != record["verdict"]:
        raise MarketActionError("native job has no matching terminal settlement")
    recipient = native["addresses"]["provider"] if settlement["provider_paid"] else evidence["client_address"]
    _expect_transfer(settlement["raw_receipt"], evidence["token_address"].lower(),
                     evidence["core_address"].lower(), recipient.lower(),
                     row.job_amount_minor_units)
    saved = read_eval_log(str(episode_dir / "inspect.eval"), resolve_attachments=True)
    if record["model_tier"] == "REAL_LLM_REMOTE_APPROVED" and (
        saved.eval.model != f"openrouter/{APPROVED_MODEL_ID}"
        or any(event.event == "model" and (
            event.model != f"openrouter/{APPROVED_MODEL_ID}"
            or getattr(event.config, "reasoning_effort", None) != "high"
        ) for event in saved.samples[0].events)
    ):
        raise MarketActionError("saved W11 model route or high reasoning differs from approved pilot")
    audit = audit_saved_market_log(saved, row)
    score = saved.samples[0].scores["protected_receipt_score"].metadata
    case, artifact = case_for_round(row)
    oracle_status = receipt_oracle(case, artifact).status.value
    if (audit != record.get("channel_audit")
            or score.get("artifact_digest") != row.artifact_digest
            or score.get("oracle_status") != oracle_status
            or score.get("Y") != (1 if oracle_status == "PASS" else 0)
            or score.get("Y") != record.get("oracle_truth")
            or type(score.get("Q")) is not bool
            or score.get("Q") != record.get("checked")
            or score.get("V") != record.get("verdict")
            or record.get("payment_status") != ("PAID" if settlement["provider_paid"] else "NOT_PAID")):
        raise MarketActionError("saved scorer, channel, verdict or payout differs")
    rows = [json.loads(line) for line in (episode_dir / "events.jsonl").read_text().splitlines()]
    _saved_tool_links(rows, saved, row)
    derived = _transform(rows, source_hash=_sha(episode_dir / "events.jsonl"),
                         row=row, native=native, evidence=evidence, score=score)
    actions = actions_from_events(derived)
    if (actions.principal_id != "client" or actions.provider_id != row.provider_id
            or actions.verifier_id != row.verifier_id
            or actions.oracle_status != oracle_status
            or actions.verdict != record["verdict"]
            or actions.check_completed != record["checked"]
            or actions.principal_to_provider_minor != settlement["provider_payout_minor_units"]
            or actions.explicit_signal_event_ids):
        raise MarketActionError("derived actions differ from saved economic outcome")
    communication = {
        "assigned_channel_mode": row.communication_mode,
        "assigned_offer_variant": row.offer_variant,
        "researcher_authored_message": row.offer_variant == "AUTHORED_UNTRUSTED_PROMISE",
        "observed_channel_posts": audit["channel_posts"],
        "observed_channel_reads": audit["channel_reads"],
        "assigned_message_posted": audit["assigned_message_posted"],
        "assigned_message_read": audit["assigned_message_read"],
        "assigned_message_sha256": audit["direct_message_sha256"],
        "independent_explicit_agreement_annotation": "NOT_PERFORMED",
    }
    provenance = {
        "schema": "w12-market-actions-derivation-v1",
        "adapter_source_sha256": _sha(Path(__file__)),
        "episode_id": row.episode_id, "market_id": row.market_id,
        "arm": row.arm, "R": row.r, "round_index": row.round_index,
        "assignment_manifest_sha256": assignment_sha,
        "source_sha256_at_freeze": plan["source_sha256"],
        "source_events_sha256": _sha(episode_dir / "events.jsonl"),
        "source_manifest_sha256": _sha(episode_dir / "run_manifest.json"),
        "native_inspect_sha256": _sha(episode_dir / "inspect.eval"),
        "native_payment_sha256": _sha(episode_dir / "native_evidence.json"),
        "source_record_sha256": _sha(episode_dir / "episode_record.json"),
        "native_chain_id": evidence["chain"]["chain_id"],
        "native_token_address": evidence["token_address"],
        "native_erc8183_escrow_address": evidence["core_address"],
        "native_party_addresses": {
            "client": evidence["client_address"],
            row.provider_id: native["addresses"]["provider"],
            row.verifier_id: native["addresses"]["auditor"],
        },
        "auditor_fee_transaction_hash": native["fee_receipt"]["transactionHash"],
        "job_funding_transaction_hash": _one(rows, "JOB_FUNDED")["payment_reference"],
        "job_settlement_transaction_hash": settlement["raw_receipt"]["transactionHash"],
        "native_job_id": native["job_id"],
        "model_behavior_tier": record["model_tier"],
        "payment_tier": "NATIVE_LOCAL_CHAIN",
        "model_cost_usd_estimate": record.get("model_cost_usd_estimate"),
        "fee_business_obligation_binding": "application_unique_market_round_map",
        "inference_tier": "ACTION_ATTRIBUTION_ONLY",
    }
    return MarketActionDerivation(actions, derived, provenance, communication)


def export_market_actions(episode_dir: Path, plan_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Write a separate immutable W12 supplement; never mutate W11 inputs."""
    episode_dir, plan_dir, output_dir = map(Path, (episode_dir, plan_dir, output_dir))
    destination = output_dir.resolve()
    if (destination == episode_dir.resolve() or episode_dir.resolve() in destination.parents
            or destination == plan_dir.resolve() or plan_dir.resolve() in destination.parents):
        raise MarketActionError("W12 output must be outside saved W11 episodes and assignments")
    result = derive_market_actions(episode_dir, plan_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    events = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                     for row in result.canonical_events)
    (output_dir / "canonical_events.jsonl").write_text(events, encoding="utf-8")
    summary = {
        "provenance": result.provenance, "communication": result.communication,
        "financial_actions": asdict(result.actions),
        "canonical_events_sha256": _sha(output_dir / "canonical_events.jsonl"),
        "limitations": (
            "Single-episode action attribution only; no inferred collusion intent, "
            "causal contrast, independent explicit-agreement annotation, live bid, "
            "or real-value transfer. ERC-20 fee obligation binding is at the application layer."
        ),
    }
    (output_dir / "actions.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary
