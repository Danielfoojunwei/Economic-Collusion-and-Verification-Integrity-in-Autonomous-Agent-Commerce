"""Saved Inspect capability smoke for prospective market arms; scripted only."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from inspect_ai.model import ModelOutput, get_model  # noqa: E402

from agent_economic_trust.w11_market_plan import make_market_schedule  # noqa: E402
from agent_economic_trust.w11_market_task import (  # noqa: E402
    AUDITOR_TOOLS, CHANNEL_TOOLS, DIRECT_CHANNEL_ID, WORKER_TOOLS,
    assigned_message, audit_saved_market_log, build_market_task,
)


MODEL_NAME = "mockllm/w11-scripted-capability-control"
ROWS = make_market_schedule("80" * 32)


def model_for(row, *, post_override=None, omit_post=False):
    def outputs(messages, tools, tool_choice, config):
        offered = {tool.name for tool in tools}
        worker = "Role: worker." in "\n".join(message.text for message in messages)
        base = WORKER_TOOLS if worker else AUDITOR_TOOLS
        expected = base | (CHANNEL_TOOLS if row.communication_mode == "DIRECT" else set())
        if offered != expected:
            raise RuntimeError(f"scripted market role tool grants differ: {offered}")
        called = [call.function for message in messages
                  for call in (getattr(message, "tool_calls", None) or [])]
        if worker:
            if "read_provider_receipts" not in called:
                return ModelOutput.for_tool_call(MODEL_NAME, "read_provider_receipts", {})
            if "submit_receipt_artifact" not in called:
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "submit_receipt_artifact",
                    {"accepted_count": 3 if row.fixture_id.startswith("delivery") else 2,
                     "claimed_amount_minor": 300 if row.fixture_id.startswith("delivery") else 350},
                )
            if row.communication_mode == "DIRECT" and "channel_post" not in called:
                if omit_post:
                    return ModelOutput.from_content(MODEL_NAME, "Provider finished without posting.")
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "channel_post",
                    {"channel_id": DIRECT_CHANNEL_ID,
                     "message": assigned_message(row) if post_override is None else post_override},
                )
            return ModelOutput.from_content(MODEL_NAME, "Provider finished.")
        if "view_receipt_submission" not in called:
            return ModelOutput.for_tool_call(MODEL_NAME, "view_receipt_submission", {})
        if row.communication_mode == "DIRECT" and "channel_read" not in called:
            return ModelOutput.for_tool_call(
                MODEL_NAME, "channel_read",
                {"channel_id": DIRECT_CHANNEL_ID, "after_sequence": 0, "limit": 10},
            )
        if "priced_receipt_check" not in called:
            return ModelOutput.for_tool_call(
                MODEL_NAME, "priced_receipt_check", {"request_id": "w11-scripted-check"},
            )
        if "issue_receipt_verdict" not in called:
            replies = [message.text for message in messages
                       if getattr(message, "role", "") == "tool"
                       and getattr(message, "function", "") == "priced_receipt_check"]
            import json
            verdict = "ACCEPT" if json.loads(replies[-1])["status"] == "PASS" else "REJECT"
            return ModelOutput.for_tool_call(
                MODEL_NAME, "issue_receipt_verdict",
                {"verdict": verdict, "request_id": "w11-scripted-verdict"},
            )
        return ModelOutput.from_content(MODEL_NAME, "Auditor finished.")

    model = get_model(MODEL_NAME, custom_outputs=outputs, memoize=False)

    async def count_text_tokens(value):
        return max(1, (len(value) + 3) // 4)

    model.api.count_text_tokens = count_text_tokens
    return model


class MarketTaskTests(unittest.TestCase):
    def test_saved_no_channel_and_direct_delivery(self):
        none = next(row for row in ROWS if row.arm == "FRESH_NONE" and row.round_index == 0)
        direct = next(row for row in ROWS if row.arm == "REPEAT_DIRECT" and row.round_index == 2)
        # This synthetic zero-history row tests the prospective intervention
        # capability only; it is not counted as an assigned market episode.
        from dataclasses import replace
        direct_smoke = replace(direct, provider_visible_prior_episode_ids=(),
                               verifier_visible_prior_episode_ids=())
        with tempfile.TemporaryDirectory(prefix="w11-task-", dir="/workspace") as dirname:
            for row in (none, direct_smoke):
                task = build_market_task(row, entries={}, fee_tier="SCRIPTED_CONTROL")
                [log] = inspect_eval(task, model=model_for(row),
                                     log_dir=str(Path(dirname) / row.communication_mode),
                                     display="none", log_realtime=False, max_retries=0)
                self.assertEqual(log.status, "success", log.error)
                saved = read_eval_log(log.location, resolve_attachments=True)
                audit = audit_saved_market_log(
                    saved, row, expected_message=assigned_message(row),
                    require_delivery=row.communication_mode == "DIRECT",
                )
                self.assertEqual(audit["status"], "PASS")
                self.assertGreater(audit["provider_model_events"], 0)
                self.assertGreater(audit["verifier_model_events"], 0)
                self.assertEqual(audit["channel_posts"], 1 if row.communication_mode == "DIRECT" else 0)
                self.assertEqual(audit["channel_reads"], 1 if row.communication_mode == "DIRECT" else 0)

    def test_assigned_promise_altered_or_omitted_remains_in_denominator(self):
        from dataclasses import replace
        row = next(row for row in ROWS if row.offer_variant == "AUTHORED_UNTRUSTED_PROMISE")
        row = replace(row, provider_visible_prior_episode_ids=(),
                      verifier_visible_prior_episode_ids=())
        self.assertEqual(row.communication_mode, "DIRECT")
        self.assertEqual(row.offer_variant, "AUTHORED_UNTRUSTED_PROMISE")
        with tempfile.TemporaryDirectory(prefix="w11-nonadherence-", dir="/workspace") as dirname:
            for variant, options in (
                ("altered", {"post_override": "Provider says: please review the receipt."}),
                ("omitted", {"omit_post": True}),
            ):
                with self.subTest(variant=variant):
                    task = build_market_task(row, entries={}, fee_tier="SCRIPTED_CONTROL")
                    [log] = inspect_eval(task, model=model_for(row, **options),
                                         log_dir=str(Path(dirname) / variant),
                                         display="none", log_realtime=False, max_retries=0)
                    self.assertEqual(log.status, "success", log.error)
                    saved = read_eval_log(log.location, resolve_attachments=True)
                    audit = audit_saved_market_log(saved, row, require_delivery=False)
                    self.assertEqual(audit["status"], "PASS")
                    self.assertFalse(audit["assigned_message_posted"])
                    self.assertFalse(audit["assigned_message_read"])
                    self.assertEqual(audit["channel_posts"], 1 if variant == "altered" else 0)
                    # Intent-to-treat counts the assigned promise round even when
                    # the assigned text was never exposed to the auditor.
                    assigned_denominator = len({row.episode_id})
                    observed_assigned_offer_exposure = int(audit["assigned_message_read"])
                    self.assertEqual((assigned_denominator, observed_assigned_offer_exposure),
                                     (1, 0))


if __name__ == "__main__":
    unittest.main()
