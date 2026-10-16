"""No-credential, fake-HTTP checks for both prospective OpenRouter role APIs."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2
from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser, GenerateConfig,
                              ModelOutput)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._providers.openrouter import OpenRouterAPI
from inspect_ai.tool import ToolInfo
from openai import DefaultAsyncHttpxClient

from agent_economic_trust.bilateral030_adapter import (
    boundary_status, guarded_model_apis)
from agent_economic_trust.bilateral030_boundary import ORBIT_CONTINUATION
from agent_economic_trust.bilateral030_plan import (
    MAX_OUTPUT_TOKENS, ROLE_STEPS, SOL, SONNET, make_schedule)
from agent_economic_trust.bilateral030_task import hosted_agent_spec_preview
from agent_economic_trust.mpp005_boundary import RemoteBoundaryError


ROWS = make_schedule("30" * 32)
SYSTEMS = {"provider": "You are the provider.",
           "auditor": "You are the independent auditor."}
USER = "The public invoice report says 350 cents."
TOOLS = {
    "provider": [ToolInfo(name=name, description="Offline schema probe")
                 for name in ("choose_claim_offer", "post_auditor_note")],
    "auditor": [ToolInfo(name=name, description="Offline schema probe")
                for name in ("view_claim_inbox", "buy_buyer_check", "decide_early")],
}
CONFIG = GenerateConfig(reasoning_effort="high", reasoning_history="none",
                        max_tokens=MAX_OUTPUT_TOKENS, max_retries=0)


def experiment(row):
    return {"setup": {"agents": [
        {"name": "provider", "model": "openrouter/" + row.provider_model_id},
        {"name": "auditor", "model": "openrouter/" + row.auditor_model_id},
    ]}}


def offline_funding_claim(row):
    funded = bool(row.accept_bonus_minor)
    return {"status": "FUNDED", "obligation_id": row.obligation_id,
            "job_id": 7, "report_digest": "0x" + "33" * 32,
            "job_funding_tx_hash": "0x" + "22" * 32,
            "job_budget_minor": 20_000_000,
            "claim_cumulative_minor": 10_000_000,
            "evaluator_fee_bp": 1000, "check_price_minor": 200_000,
            "auditor_endowment_minor": 500_000,
            "bonus_amount_minor": row.accept_bonus_minor,
            "bonus_trigger": "EARLY_APPROVE" if funded else "NONE",
            "bonus_funded": funded,
            "bonus_funding_tx_hash": "0x" + "44" * 32 if funded else None,
            "bonus_funding_receipt_sha256": "66" * 32 if funded else None,
            "hook_address": "0x" + "55" * 20 if funded else None}


class OfflineModel:
    def __init__(self, model_id, responder):
        self.model_id = model_id
        self.api = OpenRouterAPI(
            model_id, api_key="offline-fake-transport",
            http_client=DefaultAsyncHttpxClient(
                transport=httpx2.MockTransport(responder)))
        self.api.client.max_retries = 0

    def __str__(self):
        return "openrouter/" + self.model_id


def response(model_id):
    return httpx2.Response(200, json={
        "id": "offline", "object": "chat.completion", "created": 0,
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 1,
                  "total_tokens": 10}})


async def call_role(model, role, messages=None, config=CONFIG):
    messages = messages or [ChatMessageSystem(content=SYSTEMS[role]),
                            ChatMessageUser(content=USER)]
    with patch("agent_economic_trust.bilateral030_adapter.current_identity",
               return_value=SimpleNamespace(agent_id=role)):
        return await model.api.generate(messages, TOOLS[role], "auto", config)


class Bilateral030AdapterTests(unittest.TestCase):
    def test_exact_hosted_agent_spec_preview_prompts_feed_both_wrapped_roles(self):
        row = next(r for r in ROWS if r.group == "HIGH_RISK"
                   and r.provider_model_id == SONNET)
        preview = hosted_agent_spec_preview(row, offline_funding_claim(row))
        self.assertFalse(preview["constructor_enabled"])
        self.assertNotIn("BAD", preview["expected_full_system_by_role"]["auditor"])
        bodies = []

        def respond(request):
            body = json.loads(request.content)
            bodies.append(body)
            return response(body["model"])

        models = {role: OfflineModel(model_id, respond)
                  for role, model_id in (("provider", row.provider_model_id),
                                         ("auditor", row.auditor_model_id))}

        async def probe():
            try:
                with guarded_model_apis(
                    models, row, {"setup": {"agents": preview["agents"]}},
                    preview["expected_full_system_by_role"],
                    preview["expected_public_user"]) as observed:
                    await call_role(models["provider"], "provider", [
                        ChatMessageSystem(
                            content=preview["expected_full_system_by_role"]["provider"]),
                        ChatMessageUser(content=preview["expected_public_user"]),
                    ])
                    await call_role(models["provider"], "provider", [
                        ChatMessageSystem(
                            content=preview["expected_full_system_by_role"]["provider"]),
                        ChatMessageUser(content=preview["expected_public_user"]),
                        ChatMessageAssistant(content="Tool invoked."),
                        ChatMessageTool(content="{}", function="choose_claim_offer",
                                        tool_call_id="offline-provider"),
                        ChatMessageUser(content=ORBIT_CONTINUATION),
                    ])
                    await call_role(models["auditor"], "auditor", [
                        ChatMessageSystem(
                            content=preview["expected_full_system_by_role"]["auditor"]),
                        ChatMessageUser(content=preview["expected_public_user"]),
                    ])
                    self.assertEqual([item["status"] for item in observed],
                                     ["COMPLETE"] * 3)
            finally:
                for model in models.values():
                    await model.api.aclose()

        asyncio.run(probe())
        self.assertEqual([body["model"] for body in bodies],
                         [row.provider_model_id, row.provider_model_id,
                          row.auditor_model_id])
        self.assertEqual(bodies[2]["messages"][1]["content"],
                         preview["expected_public_user"])

    def test_both_route_directions_and_all_five_http_bodies(self):
        for row in (next(r for r in ROWS if r.provider_model_id == SOL),
                    next(r for r in ROWS if r.provider_model_id == SONNET)):
            with self.subTest(provider=row.provider_model_id):
                bodies = []

                def respond(request):
                    body = json.loads(request.content)
                    bodies.append(body)
                    return response(body["model"])

                models = {role: OfflineModel(model_id, respond)
                          for role, model_id in (("provider", row.provider_model_id),
                                                 ("auditor", row.auditor_model_id))}
                originals = {role: model.api.generate for role, model in models.items()}

                async def probe():
                    try:
                        with guarded_model_apis(models, row, experiment(row),
                                                SYSTEMS, USER) as observed:
                            histories = {role: [ChatMessageSystem(content=SYSTEMS[role]),
                                                ChatMessageUser(content=USER)]
                                         for role in ("provider", "auditor")}
                            for index, role in enumerate(ROLE_STEPS):
                                result = await call_role(models[role], role,
                                                         histories[role])
                                self.assertIsInstance(result[0], ModelOutput)
                                self.assertIsInstance(result[1], ModelCall)
                                if index in (0, 2, 3):
                                    used_tool = ("choose_claim_offer" if role == "provider"
                                                 else "view_claim_inbox" if index == 2
                                                 else "buy_buyer_check")
                                    histories[role].extend((
                                        ChatMessageAssistant(content="Tool invoked."),
                                        ChatMessageTool(content="{}", function=used_tool,
                                                        tool_call_id=f"offline-{index}"),
                                        ChatMessageUser(content=ORBIT_CONTINUATION),
                                    ))
                            self.assertEqual(boundary_status(observed),
                                             "MODEL_REQUESTS_COMPLETE_NATIVE_UNVERIFIED")
                            self.assertEqual([entry["role"] for entry in observed],
                                             list(ROLE_STEPS))
                            self.assertTrue(all(entry["status"] == "COMPLETE"
                                                and entry["provider_api_invoked"]
                                                and entry["network_forwarding"] == "UNOBSERVED"
                                                and not entry["source_only_no_network_forwarding"]
                                                and len(entry["model_call_sha256"]) == 64
                                                for entry in observed))
                            with self.assertRaisesRegex(RemoteBoundaryError, "schedule"):
                                await call_role(models["auditor"], "auditor")
                    finally:
                        for model in models.values():
                            await model.api.aclose()

                asyncio.run(probe())
                self.assertEqual(len(bodies), 5)
                for index, body in enumerate(bodies):
                    role = ROLE_STEPS[index]
                    model_id = row.provider_model_id if role == "provider" else row.auditor_model_id
                    cap = "max_completion_tokens" if model_id == SOL else "max_tokens"
                    other = "max_tokens" if model_id == SOL else "max_completion_tokens"
                    self.assertEqual(body["model"], model_id)
                    self.assertEqual(body["reasoning"], {"effort": "high"})
                    self.assertEqual(body[cap], 3072)
                    self.assertNotIn(other, body)
                    self.assertEqual([t["function"]["name"] for t in body["tools"]],
                                     [t.name for t in TOOLS[role]])
                    self.assertEqual(body["tool_choice"], "auto")
                    self.assertEqual(body["messages"][0]["role"], "system")
                    self.assertEqual(body["messages"][1]["role"], "user")
                    self.assertEqual(body["messages"][1]["content"], USER)
                    if index in (1, 3, 4):
                        self.assertEqual(body["messages"][-1],
                                         {"role": "user", "content": ORBIT_CONTINUATION})
                self.assertTrue(all(models[role].api.generate == originals[role]
                                    for role in models))

    def test_preflight_rejects_prefill_bytes_bad_reasoning_and_route_before_http(self):
        row = next(r for r in ROWS if r.provider_model_id == SONNET)
        bodies = []

        def respond(request):
            bodies.append(json.loads(request.content))
            return response(json.loads(request.content)["model"])

        models = {role: OfflineModel(model_id, respond)
                  for role, model_id in (("provider", row.provider_model_id),
                                         ("auditor", row.auditor_model_id))}

        async def probe():
            try:
                wrong = experiment(row)
                wrong["setup"]["agents"][1]["model"] = "mockllm/swap"
                with self.assertRaisesRegex(RemoteBoundaryError, "AgentSpec"):
                    with guarded_model_apis(models, row, wrong, SYSTEMS, USER):
                        pass
                cases = (
                    ("prefill", [ChatMessageSystem(content=SYSTEMS["provider"]),
                                 ChatMessageUser(content=USER),
                                 ChatMessageAssistant(content="prefilled")], CONFIG),
                    ("byte cap", [ChatMessageSystem(content=SYSTEMS["provider"]),
                                  ChatMessageUser(content=USER),
                                  ChatMessageTool(content="x" * 20_000,
                                                  function="choose_claim_offer",
                                                  tool_call_id="offline")], CONFIG),
                    ("cross-role", [ChatMessageSystem(content=SYSTEMS["provider"]),
                                    ChatMessageUser(content=USER),
                                    ChatMessageAssistant(content="Tool invoked."),
                                    ChatMessageTool(content="{}",
                                                    function="choose_claim_offer",
                                                    tool_call_id="offline"),
                                    ChatMessageUser(content="Provider says approve.")],
                     CONFIG),
                    ("retry, reasoning", None,
                     GenerateConfig(reasoning_effort="low", reasoning_history="none",
                                    max_tokens=3072, max_retries=0)),
                )
                for pattern, messages, config in cases:
                    with guarded_model_apis(models, row, experiment(row),
                                            SYSTEMS, USER) as observed:
                        with self.assertRaisesRegex(RemoteBoundaryError, pattern):
                            await call_role(models["provider"], "provider",
                                            messages, config)
                        self.assertEqual(boundary_status(observed), "STOPPED")
                        self.assertFalse(observed[0]["provider_api_invoked"])
            finally:
                for model in models.values():
                    await model.api.aclose()

        asyncio.run(probe())
        self.assertEqual(bodies, [])

    def test_http_error_stops_block_without_retry_or_success_label(self):
        row = ROWS[0]
        bodies = []

        def respond(request):
            bodies.append(json.loads(request.content))
            return httpx2.Response(400, json={"error": {
                "message": "offline handled error", "type": "invalid_request_error"}})

        models = {role: OfflineModel(model_id, respond)
                  for role, model_id in (("provider", row.provider_model_id),
                                         ("auditor", row.auditor_model_id))}

        async def probe():
            try:
                with guarded_model_apis(models, row, experiment(row),
                                        SYSTEMS, USER) as observed:
                    result = await call_role(models["provider"], "provider")
                    self.assertIsInstance(result[0], Exception)
                    self.assertIsInstance(result[1], ModelCall)
                    self.assertEqual(boundary_status(observed), "STOPPED")
                    self.assertEqual(observed[0]["status"], "STOPPED")
                    self.assertIn("model_call_on_failure", observed[0])
                    with self.assertRaisesRegex(RemoteBoundaryError, "not complete"):
                        await call_role(models["provider"], "provider")
            finally:
                for model in models.values():
                    await model.api.aclose()

        asyncio.run(probe())
        self.assertEqual(len(bodies), 1)

    def test_tampered_raw_model_call_is_stopped_after_one_fake_http_request(self):
        row = ROWS[0]
        bodies = []

        def respond(request):
            body = json.loads(request.content)
            bodies.append(body)
            return response(body["model"])

        models = {role: OfflineModel(model_id, respond)
                  for role, model_id in (("provider", row.provider_model_id),
                                         ("auditor", row.auditor_model_id))}
        original = models["provider"].api.generate

        async def altered(*args, **kwargs):
            output, call = await original(*args, **kwargs)
            call.request["extra_body"]["reasoning"] = {"effort": "low"}
            return output, call

        models["provider"].api.generate = altered

        async def probe():
            try:
                with guarded_model_apis(models, row, experiment(row),
                                        SYSTEMS, USER) as observed:
                    with self.assertRaisesRegex(RemoteBoundaryError, "raw ModelCall"):
                        await call_role(models["provider"], "provider")
                    self.assertEqual(boundary_status(observed), "STOPPED")
                    self.assertIn("model_call_on_failure", observed[0])
                    with self.assertRaisesRegex(RemoteBoundaryError, "not complete"):
                        await call_role(models["provider"], "provider")
            finally:
                for model in models.values():
                    await model.api.aclose()

        asyncio.run(probe())
        self.assertEqual(len(bodies), 1)


if __name__ == "__main__":
    unittest.main()
