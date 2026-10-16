"""Evidence-file checks: schema, causal ordering, replay, and secret handling."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_economic_trust.evidence import (  # noqa: E402
    EvidenceWriter,
    canonical_sha256,
    make_run_manifest,
    scrub_secrets,
    validate_event,
    validate_manifest,
    verify_evidence,
)


def _manifest(**overrides: object) -> dict[str, object]:
    return make_run_manifest(
        run_id="seed-17",
        experiment_id="reconciliation-smoke",
        created_utc="2026-10-15T00:00:00Z",
        model_behavior_tier="SCRIPTED",
        payment_tier="MOCK_LOCAL",
        source_pins={"repo": "a" * 40},
        randomization={"seed": 17},
        planned_episodes=1,
        **overrides,
    )


def _event(**overrides: object) -> dict[str, object]:
    return {
        "episode_id": "episode-1",
        "actor_id": "auditor-1",
        "actor_role": "verifier",
        "event_type": "CHECK_TOOL_CALLED",
        "task_id": "task-1",
        "status": "SUCCESS",
        "payload": {"cost_units": 4},
        **overrides,
    }


class EvidenceWriterTests(unittest.TestCase):
    def test_valid_events_outcome_and_manifest_hashes(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = EvidenceWriter(Path(temporary) / "run", _manifest())
            first = writer.append_event(_event())
            second = writer.append_event(_event(
                event_type="CHECK_COMPLETED", parent_event_id=first["event_id"]
            ))
            outcome = writer.append_outcome({
                "episode_id": "episode-1", "task_id": "task-1", "wrong_paid": False,
            })
            manifest = writer.finalize(status="COMPLETE", completed_episodes=1)

            self.assertEqual([first["seq"], second["seq"]], [0, 1])
            self.assertEqual(second["parent_event_id"], first["event_id"])
            self.assertEqual(first["model_behavior_tier"], "SCRIPTED")
            self.assertEqual(first["payment_tier"], "MOCK_LOCAL")
            self.assertEqual(outcome["execution_tier"], "SCRIPTED_SIMULATION")
            self.assertEqual(outcome["model_behavior_tier"], "SCRIPTED")
            self.assertEqual(outcome["payment_tier"], "MOCK_LOCAL")
            for line in writer.events_path.read_text(encoding="utf-8").splitlines():
                validate_event(json.loads(line))
            stored = json.loads(writer.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest(stored), manifest)
            for path in (writer.events_path, writer.outcomes_path):
                self.assertEqual(stored["artifacts_sha256"][path.name], sha256(path.read_bytes()).hexdigest())
            with writer.outcomes_path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream))[0]["episode_id"], "episode-1")
            self.assertEqual(verify_evidence(writer.directory), {"events": 2, "outcomes": 1})

    def test_invalid_event_and_causality_leave_no_partial_record(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = EvidenceWriter(Path(temporary) / "run", _manifest())
            with self.assertRaises(Exception):
                writer.append_event(_event(actor_role="intruder"))
            with self.assertRaises(ValueError):
                writer.append_event(_event(parent_event_id="ev_missing"))
            with self.assertRaises(Exception):
                writer.append_event(_event(status="PAID"))
            self.assertEqual(writer.events_path.read_text(encoding="utf-8"), "")
            self.assertEqual(writer.append_event(_event())["seq"], 0)
            with self.assertRaises(ValueError):
                writer.append_event(_event(
                    episode_id="episode-2", parent_event_id=json.loads(
                        writer.events_path.read_text(encoding="utf-8").splitlines()[0]
                    )["event_id"],
                ))
            with self.assertRaises(Exception):
                validate_manifest({**_manifest(), "allow_mainnet": True})

    def test_replay_is_byte_identical_and_hash_is_canonical(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            snapshots = []
            for index in (1, 2):
                writer = EvidenceWriter(base / str(index), _manifest())
                first = writer.append_event(_event(payload={"b": 2, "a": 1}))
                writer.append_event(_event(
                    event_type="VERDICT_ISSUED", parent_event_id=first["event_id"],
                    payload={"verdict": "REJECT"},
                ))
                writer.append_outcome({"episode_id": "episode-1", "wrong_paid": False})
                writer.finalize(status="COMPLETE", completed_episodes=1)
                snapshots.append(tuple(
                    path.read_bytes() for path in
                    (writer.events_path, writer.outcomes_path, writer.manifest_path)
                ))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(canonical_sha256({"b": 2, "a": 1}), canonical_sha256({"a": 1, "b": 2}))
            with self.assertRaises(FileExistsError):
                EvidenceWriter(base / "1", _manifest())

    def test_independent_verifier_rejects_tampered_file(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = EvidenceWriter(Path(temporary) / "run", _manifest())
            writer.append_event(_event())
            self.assertEqual(verify_evidence(writer.directory), {"events": 1, "outcomes": 0})
            with writer.events_path.open("a", encoding="utf-8") as stream:
                stream.write("{}\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_evidence(writer.directory)

    def test_exception_event_is_scrubbed(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = EvidenceWriter(Path(temporary) / "run", _manifest())
            event = writer.append_exception(
                RuntimeError("Bearer hidden_failure_token"), episode_id="episode-1", task_id="task-1"
            )
            self.assertEqual(event["status"], "ERROR")
            self.assertEqual(event["payload"]["exception_type"], "RuntimeError")
            self.assertNotIn("hidden_failure_token", writer.events_path.read_text(encoding="utf-8"))
            self.assertEqual(verify_evidence(writer.directory)["events"], 1)

    def test_secret_values_are_scrubbed_in_all_files(self) -> None:
        with TemporaryDirectory() as temporary:
            manifest = _manifest(notes="api_key=hidden_manifest_value")
            writer = EvidenceWriter(Path(temporary) / "run", manifest)
            writer.append_event(_event(payload={
                "authorization": "Bearer hidden_header_value",
                "message": "Bearer hidden_bearer_value and sk-hiddeninlinevalue",
                "nested": [{"private_key": "hidden_private_value"}],
                "key_ref": "nonsecret-reference",
            }))
            writer.append_outcome({
                "episode_id": "episode-1", "api_token": "hidden_outcome_value"
            })
            combined = "".join(path.read_text(encoding="utf-8") for path in (
                writer.events_path, writer.outcomes_path, writer.manifest_path
            ))
            for secret in (
                "hidden_manifest_value", "hidden_header_value", "hidden_bearer_value",
                "hiddeninlinevalue", "hidden_private_value", "hidden_outcome_value",
            ):
                self.assertNotIn(secret, combined)
            self.assertIn("nonsecret-reference", combined)

    def test_exact_manifest_usage_and_catalog_numbers_survive_scrubbing(self) -> None:
        manifest = validate_manifest(_manifest(
            model_usage={
                "input_tokens": 37, "output_tokens": 5, "total_tokens": 42,
                "reasoning_tokens": None, "input_tokens_cache_read": 0,
                "input_tokens_cache_write": 2,
            },
            pricing_snapshot={
                "input_usd_per_token": "0.00001",
                "output_usd_per_token": "0.00003",
                "cache_read_usd_per_token": "8E-7",
                "cache_write_usd_per_token": "0.00001",
                "input_framing_tokens_per_call": 8192,
                "max_completion_tokens": 128000,
            },
        ))
        self.assertEqual(manifest["model_usage"]["input_tokens"], 37)
        self.assertIsNone(manifest["model_usage"]["reasoning_tokens"])
        self.assertEqual(manifest["pricing_snapshot"]["cache_read_usd_per_token"], "8E-7")
        self.assertEqual(manifest["pricing_snapshot"]["max_completion_tokens"], 128000)
        self.assertEqual(validate_manifest(manifest), manifest)

    def test_numeric_exception_does_not_expose_token_named_secrets(self) -> None:
        cleaned = scrub_secrets({
            "model_usage": {"input_tokens": "sk-secretmaterial", "api_token": 42,
                            "output_tokens": -1, "total_tokens": 5.5},
            "pricing_snapshot": {"input_usd_per_token": "Bearer secretmaterial",
                                 "cache_read_usd_per_token": "NaN",
                                 "api_key": 0.1,
                                 "max_completion_tokens": "128000"},
            "payload": {"model_usage": {"input_tokens": 42}},
            "api_token": 99,
        })
        self.assertEqual(cleaned["model_usage"], {
            "input_tokens": "[REDACTED]", "api_token": "[REDACTED]",
            "output_tokens": "[REDACTED]", "total_tokens": "[REDACTED]",
        })
        self.assertEqual(cleaned["pricing_snapshot"], {
            "input_usd_per_token": "[REDACTED]",
            "cache_read_usd_per_token": "[REDACTED]",
            "api_key": "[REDACTED]",
            "max_completion_tokens": "[REDACTED]",
        })
        self.assertEqual(cleaned["payload"]["model_usage"]["input_tokens"], "[REDACTED]")
        self.assertEqual(cleaned["api_token"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
