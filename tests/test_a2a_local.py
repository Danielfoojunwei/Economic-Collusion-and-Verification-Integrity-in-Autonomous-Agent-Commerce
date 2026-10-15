"""A2A v1.0 SDK transport probe over an in-process ASGI server."""

import asyncio
import importlib.util
import unittest
from unittest.mock import AsyncMock


@unittest.skipUnless(
    all(importlib.util.find_spec(name) is not None for name in ("a2a", "starlette", "sse_starlette")),
    "pinned A2A Python SDK with HTTP server extras not installed",
)
class A2ALocalTests(unittest.TestCase):
    def test_rest_task_messages_and_application_auth(self):
        asyncio.run(self._scenario())

    async def _scenario(self):
        import httpx
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse

        from a2a.client import ClientConfig
        from a2a.client.client_factory import ClientFactory
        from a2a.server.request_handlers import RequestHandler
        from a2a.server.routes import create_rest_routes
        from a2a.types.a2a_pb2 import (
            AgentCapabilities, AgentCard, AgentInterface, CancelTaskRequest,
            Message, Part, Role, SendMessageRequest, Task, TaskState, TaskStatus,
        )
        from a2a.utils.constants import TransportProtocol

        handler = AsyncMock(spec=RequestHandler)
        tasks: dict[str, Task] = {}

        async def on_send(request, _context):
            message_id = request.message.message_id
            state = TaskState.TASK_STATE_WORKING if message_id == "msg-audit" else TaskState.TASK_STATE_COMPLETED
            task = Task(id=f"task-{message_id}", context_id="ctx-audit", status=TaskStatus(state=state))
            tasks[task.id] = task
            return task

        async def on_cancel(request, _context):
            task = tasks[request.id]
            if task.status.state != TaskState.TASK_STATE_WORKING:
                raise ValueError("only working tasks can be canceled in this local handler")
            task.status.state = TaskState.TASK_STATE_CANCELED
            return task

        handler.on_message_send.side_effect = on_send
        handler.on_cancel_task.side_effect = on_cancel
        app = Starlette(routes=create_rest_routes(handler))
        observed_auth: list[bool] = []

        async def guarded(scope, receive, send):
            if scope["type"] == "http":
                authorized = dict(scope["headers"]).get(b"authorization") == b"Bearer local-test-role"
                observed_auth.append(authorized)
                if not authorized:
                    await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
                    return
            await app(scope, receive, send)

        transport = httpx.ASGITransport(app=guarded)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as denied:
            response = await denied.post("/message:send", json={})
            self.assertEqual(response.status_code, 401)
        card = AgentCard(
            name="Local Auditor", version="1.0.0", capabilities=AgentCapabilities(streaming=False),
            supported_interfaces=[AgentInterface(protocol_binding=TransportProtocol.HTTP_JSON, url="http://testserver")],
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", headers={"Authorization": "Bearer local-test-role"}
        ) as http:
            client = ClientFactory(config=ClientConfig(httpx_client=http, supported_protocol_bindings=[TransportProtocol.HTTP_JSON], streaming=False)).create(card)
            request = SendMessageRequest(message=Message(
                role=Role.ROLE_USER, message_id="msg-audit", parts=[Part(text="Audit submitted work")]
            ))
            events = [event async for event in client.send_message(request=request)]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].task.id, "task-msg-audit")
            self.assertEqual(events[0].task.status.state, TaskState.TASK_STATE_WORKING)
            result = await client.cancel_task(request=CancelTaskRequest(id="task-msg-audit"))
            self.assertEqual(result.status.state, TaskState.TASK_STATE_CANCELED)
            completed = [event async for event in client.send_message(request=SendMessageRequest(message=Message(
                role=Role.ROLE_USER, message_id="msg-complete", parts=[Part(text="Deliver result")]
            )))]
            self.assertEqual(completed[0].task.status.state, TaskState.TASK_STATE_COMPLETED)
            await client.close()
        self.assertEqual(observed_auth, [False, True, True, True])
        self.assertEqual(handler.on_message_send.await_count, 2)
        handler.on_cancel_task.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
